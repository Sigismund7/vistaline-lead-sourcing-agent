"""Personalizer — fills X Project + Y Detail for kept-leads-with-email by
visually inspecting the contractor's gallery page or, as fallback, a Yelp
photo. Operates only on leads that already have an email (so we never burn
vision tokens on leads FindyMail couldn't find an inbox for).

This module's pure functions (parse_vision_response, build_messages) are
unit-tested. The vision call itself is integration-tested via a smoke run.
"""
from __future__ import annotations
import base64
import io
import json
import re
from pathlib import Path

import requests
from PIL import Image

from tools import YelpFusionClient


# Anthropic accepts images up to 5 MB (decoded bytes). Base64 encoding adds
# ~33%, so raw bytes must stay under ~3.75 MB to be safe. Full-page Playwright
# screenshots of gallery pages routinely exceed this because gallery pages are
# tall scrolls.
#
# Compression strategy:
#   1. Crop the screenshot to the first _VISION_CROP_HEIGHT pixels. Gallery
#      thumbnails near the top of the page give Claude enough signal to pick
#      the standout project; content below 4500 px rarely adds new projects.
#   2. Keep width intact (never scale horizontally) — gallery cards are
#      typically 300-400 px wide and must remain readable.
#   3. JPEG-encode at 85% quality (lossless-quality for thumbnails).
#   4. If the result still exceeds _VISION_MAX_BYTES, scale height down further
#      in 500 px steps until it fits (defensive; rarely triggered after step 1).
_VISION_MAX_BYTES = 3_600_000   # ~3.6 MB raw → safely under 5 MB base64
_VISION_CROP_HEIGHT = 4500      # px — how much of the page to show Claude


def _compress_for_vision(image_png: bytes) -> tuple[bytes, str]:
    """Crop and JPEG-compress a PNG screenshot so it fits Anthropic's 5 MB limit.

    Returns (compressed_bytes, media_type). If the original is already small
    enough, returns it unchanged as image/png. Otherwise crops to the first
    _VISION_CROP_HEIGHT pixels (preserving full width so gallery cards remain
    readable) and JPEG-encodes.
    """
    if len(image_png) <= _VISION_MAX_BYTES:
        return image_png, "image/png"
    img = Image.open(io.BytesIO(image_png))
    w, h = img.size
    # Crop to first _VISION_CROP_HEIGHT rows; clamp so we don't over-crop.
    crop_h = min(h, _VISION_CROP_HEIGHT)
    img = img.crop((0, 0, w, crop_h))
    # Cap width at 1280 px — Anthropic rejects images wider than 8000 px, and
    # Playwright's viewport is already set to 1280, but retina/HiDPI captures
    # can produce 2x-wide screenshots (e.g. 2560 px) that trigger the limit.
    if img.width > 1280:
        ratio = 1280 / img.width
        img = img.resize((1280, int(img.height * ratio)), Image.LANCZOS)
    # Convert RGBA/P to RGB before JPEG encoding (JPEG doesn't support alpha).
    if img.mode in ("RGBA", "P", "LA"):
        img = img.convert("RGB")
    # Iteratively reduce crop height until the encoded JPEG fits. This handles
    # unusually image-dense gallery pages; each iteration drops 500 px.
    quality = 85
    while True:
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=quality, optimize=True)
        compressed = buf.getvalue()
        if len(compressed) <= _VISION_MAX_BYTES:
            break
        # Reduce height by 500 px and retry.
        _, cur_h = img.size
        new_h = cur_h - 500
        if new_h < 500:
            # Pathological image; drop quality as last resort.
            quality = max(quality - 10, 50)
            new_h = cur_h
        img = img.crop((0, 0, w, new_h))
    return compressed, "image/jpeg"


def parse_vision_response(raw: str) -> dict[str, str]:
    """Extract {x_project, y_detail, chosen_project} from Claude's reply.

    Claude is prompted to return strict JSON, but vision models occasionally
    wrap output in ```json``` fences or add a trailing sentence. This parser
    tolerates those by stripping fences and matching the first {...} block.
    Always returns a dict with the three keys; missing or malformed values
    become empty strings (callers treat empty strings as 'vision_failed').
    """
    blank = {"x_project": "", "y_detail": "", "chosen_project": ""}
    if not raw:
        return blank
    cleaned = raw.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
        cleaned = re.sub(r"\s*```$", "", cleaned)
    match = re.search(r"\{.*\}", cleaned, flags=re.DOTALL)
    if not match:
        return blank
    try:
        data = json.loads(match.group(0))
    except json.JSONDecodeError:
        return blank
    return {
        "x_project": str(data.get("x_project", "") or "").strip(),
        "y_detail": str(data.get("y_detail", "") or "").strip(),
        "chosen_project": str(data.get("chosen_project", "") or "").strip(),
    }


# ---------------------------------------------------------------------------
# Vision extraction
# ---------------------------------------------------------------------------

from anthropic import Anthropic  # noqa: E402 — deferred to keep top-of-file clean


_FEWSHOT_PATH = Path(__file__).parent.parent / "docs" / "personalization-fewshot.md"


_VISION_SYSTEM = """You are a copywriter generating cold-email personalization fields for a remodeling contractor.

You will be shown a screenshot of the contractor's project gallery page.

Your job:
1. Scan ALL projects visible. Pick the SINGLE most prominent / distinctive one
   (the one a passerby's eye would stop on).
2. Describe it as X Project: 3-5 words. Format = "<aesthetic> <room> <project type>".
   Examples: "dark modern kitchen remodel", "white shaker kitchen remodel",
   "frameless glass shower bath".
3. Describe Y Detail: 4-6 words naming a SPECIFIC visible feature in that
   project that makes it memorable. Y Detail must be a thing the homeowner
   would proudly remember about their project.

ALLOWED Y Detail subjects: countertops, islands, range hoods, light fixtures,
vanities, sinks, faucets, cabinet hardware, backsplash patterns, fireplace
surrounds, shower niches, accent strips, soaking tubs, glass enclosures.

FORBIDDEN Y Detail subjects: walls (unless they ARE the feature, e.g. accent
brick wall), flooring, ceilings, trim, grout, paint colors alone, generic
"clean lines" / "modern look" / "spacious feel".

NEVER guess. If you cannot see a clear standout project, return empty strings.

Output STRICT JSON only — no prose, no markdown fence:
{
  "x_project": "...",
  "y_detail": "...",
  "chosen_project": "short phrase identifying which project you picked"
}
"""


def _load_fewshot_block() -> str:
    """Load the few-shot table from docs/personalization-fewshot.md."""
    if not _FEWSHOT_PATH.exists():
        return ""
    return _FEWSHOT_PATH.read_text(encoding="utf-8")


def extract_xy(
    image_png: bytes,
    *,
    anthropic_key: str,
    model: str,
) -> dict[str, str]:
    """Send a screenshot to Claude vision; return parsed {x_project, y_detail,
    chosen_project}. External errors are caught and surfaced as an empty
    dict so the caller can mark personalization_status = "vision_failed".
    """
    client = Anthropic(api_key=anthropic_key, max_retries=10)
    fewshot = _load_fewshot_block()
    user_text = (
        "Reference style examples (match this shape):\n\n"
        f"{fewshot}\n\n"
        "Now examine the gallery screenshot and return the JSON."
    )
    image_bytes, media_type = _compress_for_vision(image_png)
    b64 = base64.standard_b64encode(image_bytes).decode("ascii")
    try:
        resp = client.messages.create(
            model=model,
            max_tokens=400,
            system=_VISION_SYSTEM,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image",
                            "source": {
                                "type": "base64",
                                "media_type": media_type,
                                "data": b64,
                            },
                        },
                        {"type": "text", "text": user_text},
                    ],
                }
            ],
        )
    except Exception as e:
        print(f"[personalizer] WARN: vision call failed: {type(e).__name__} {e}")
        return parse_vision_response("")  # all-empty
    raw = "".join(b.text for b in resp.content if hasattr(b, "text"))
    return parse_vision_response(raw)


# ---------------------------------------------------------------------------
# Yelp photo fallback
# ---------------------------------------------------------------------------


def _yelp_photo_bytes(business_name: str, address: str, *, yelp_key: str) -> bytes | None:
    """Fetch the first usable photo from a business's Yelp listing as PNG/JPEG bytes.

    Two-step: business search by (name, location) -> business details for
    photo URLs -> HTTP GET on the first photo URL. Returns None if any step
    fails or the business has no photos. External failures are caught and
    logged (CLAUDE.md).
    """
    if not yelp_key or not business_name:
        return None
    client = YelpFusionClient(api_key=yelp_key)
    try:
        results = client.search_businesses(
            term=business_name,
            location=address or "United States",
            categories="contractors,homeservices",
            radius_m=10000,
            limit=1,
        )
    except (requests.HTTPError, requests.Timeout, requests.ConnectionError) as e:
        print(f"[personalizer] WARN: yelp search {business_name!r}: {type(e).__name__} {e}")
        return None
    if not results:
        return None
    business_id = str(results[0].get("id") or "")
    if not business_id:
        return None
    try:
        details = client.get_business_details(business_id=business_id)
    except (requests.HTTPError, requests.Timeout, requests.ConnectionError) as e:
        print(f"[personalizer] WARN: yelp details {business_id}: {type(e).__name__} {e}")
        return None
    photos = details.get("photos") or []
    if not photos:
        return None
    photo_url = str(photos[0])
    try:
        resp = requests.get(photo_url, timeout=15)
        resp.raise_for_status()
    except (requests.HTTPError, requests.Timeout, requests.ConnectionError) as e:
        print(f"[personalizer] WARN: yelp photo fetch {photo_url}: {type(e).__name__} {e}")
        return None
    return resp.content


# ---------------------------------------------------------------------------
# Parallel orchestrator
# ---------------------------------------------------------------------------

import concurrent.futures as futures  # noqa: E402

from state import CampaignState, Lead  # noqa: E402
from agents.gallery_finder import find_and_screenshot  # noqa: E402


STEP_NAME = "personalizer"


def _one_lead(
    lead: Lead,
    *,
    anthropic_key: str,
    yelp_key: str,
    model: str,
    timeout_s: int,
) -> dict[str, str]:
    """Process a single lead. Returns the field updates as a dict.

    Skips leads with no email (post-FindyMail gating). Tries website gallery
    first, falls back to Yelp photo. Each call constructs its own Anthropic
    client (CLAUDE.md: never share clients across threads).
    """
    if not lead.email:
        return {"personalization_status": "no_email_skip"}

    img, source_url = find_and_screenshot(lead.website, timeout_s=timeout_s)
    y_source = "website_gallery" if img else ""

    if img is None and yelp_key:
        img = _yelp_photo_bytes(lead.business_name, lead.address, yelp_key=yelp_key)
        y_source = "yelp_photo" if img else ""

    if img is None:
        return {"personalization_status": "no_gallery"}

    parsed = extract_xy(img, anthropic_key=anthropic_key, model=model)
    if not parsed["x_project"] or not parsed["y_detail"]:
        return {"personalization_status": "vision_failed", "y_source": y_source}

    return {
        "x_project": parsed["x_project"],
        "y_detail": parsed["y_detail"],
        "y_source": y_source,
        "personalization_status": "ok",
    }


def run(
    state: CampaignState,
    anthropic_key: str,
    *,
    yelp_key: str,
    model: str,
    max_parallel: int,
    timeout_s: int,
) -> None:
    """Fill x_project / y_detail / y_source / personalization_status on every
    kept lead with an email. Idempotent — re-running on the same state skips
    leads that already have personalization_status set.
    """
    if state.is_done(STEP_NAME):
        state.info(STEP_NAME, "already done, skipping")
        return

    targets = [
        l for l in state.leads
        if l.kept and l.email and not l.personalization_status
    ]
    skipped_no_email = sum(1 for l in state.leads if l.kept and not l.email)
    state.info(
        STEP_NAME,
        f"processing {len(targets)} leads (skipping {skipped_no_email} with no email)",
    )

    with futures.ThreadPoolExecutor(max_workers=max_parallel) as ex:
        future_to_lead = {
            ex.submit(
                _one_lead,
                lead,
                anthropic_key=anthropic_key,
                yelp_key=yelp_key,
                model=model,
                timeout_s=timeout_s,
            ): lead
            for lead in targets
        }
        for fut in futures.as_completed(future_to_lead):
            lead = future_to_lead[fut]
            try:
                update = fut.result()
            except Exception as e:
                state.info(
                    STEP_NAME,
                    f"crash on {lead.business_name!r}: {type(e).__name__} {e}",
                    level="error",
                )
                lead.personalization_status = "vision_failed"
                continue
            for k, v in update.items():
                setattr(lead, k, v)
            state.info(
                STEP_NAME,
                f"{lead.business_name}: status={lead.personalization_status} "
                f"x={lead.x_project!r} y={lead.y_detail!r}",
            )

    state.mark_done(STEP_NAME)
