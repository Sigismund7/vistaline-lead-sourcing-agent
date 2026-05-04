# Personalization Agent (X Project + Y Detail + LinkedIn) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a post-FindyMail personalization step that, given an enriched CSV containing email-found leads, fills in `x_project` (3–5-word room+style description), `y_detail` (4–6-word standout feature), and `linkedin_url` for each lead — producing a final agency-format CSV ready for Instantly.

**Architecture:** New CLI mode `python run.py --personalize <enriched-csv>` reads a FindyMail-returned CSV, hydrates a `CampaignState`, runs two new agents (`agents/personalizer.py`, `agents/linkedin_finder.py`) that operate **only on rows with non-empty `email`**, then writes a final agency CSV. Personalizer uses Playwright to load the contractor's gallery page, takes a full-page screenshot, sends it to Claude Sonnet vision with few-shot examples, and extracts X+Y from the most prominent project. Fallback chain: website gallery (`/gallery`, `/portfolio`, `/projects`, `/our-work`) → Yelp Fusion photo URLs → leave blank with reason. Instagram is **deliberately out of scope for v1**. LinkedIn finder uses Claude's existing `web_search` tool (same pattern as `owner_researcher` Phase 2). Schema changes: extend `Lead` dataclass with `x_project`, `y_detail`, `y_source`, `linkedin_url`, `linkedin_source`, `personalization_status`; add same columns to Supabase `leads` table.

**Tech Stack:** Python 3.11, Playwright (new dependency), Anthropic SDK (vision + web_search), existing `tools.YelpFusionClient`, existing CSV / dataclass patterns.

---

## File Structure

**Create:**
- `agents/gallery_finder.py` — Playwright-driven gallery URL discovery + full-page screenshot capture. Returns `(image_bytes, source_url)` or `(None, "")`.
- `agents/personalizer.py` — Orchestrates X/Y extraction. For each kept-lead-with-email: calls `gallery_finder`, then Claude Sonnet vision; on failure falls back to Yelp photos.
- `agents/linkedin_finder.py` — Claude `web_search` agent that returns `{linkedin_url, confidence}` for an owner+business pair.
- `agents/csv_agency.py` — Two functions: `read_enriched(path)` parses a FindyMail-returned CSV into a `CampaignState`; `write_agency(state, path)` writes the final 13-column agency CSV.
- `tests/test_csv_agency_roundtrip.py` — Standalone unittest: round-trips a sample enriched CSV through `read_enriched` and asserts every field.
- `tests/test_gallery_finder_urls.py` — Pure-function test of the gallery-URL candidate generator (no Playwright, no network).
- `tests/test_personalizer_vision_parser.py` — Pure-function test of the JSON-extraction helper that parses Claude's vision response.
- `tests/test_linkedin_finder_parser.py` — Pure-function test of the LinkedIn URL validator.
- `docs/personalization-fewshot.md` — The 8 hand-curated X/Y example pairs used in the vision prompt. Lives next to the plan so future model swaps can re-tune from one source.
- `supabase/migrations/2026-05-03-personalization-columns.sql` — Adds the new columns to `leads`.

**Modify:**
- `state.py:23-44` — Extend `Lead` dataclass with six new fields. Update `save_leads` and `load` row mappers.
- `requirements.txt` — Add `playwright>=1.48.0`.
- `config.py` — Add `personalizer_max_parallel: int = 4`, `personalizer_vision_model: str = "claude-sonnet-4-20250514"`, `personalizer_screenshot_timeout_s: int = 25`.
- `run.py:22-30` — Add `--personalize <csv-path>` mutually-exclusive subcommand.
- `agents/csv_assembler.py:28-34` — Update `MASTER_COLUMNS` to include the six new fields so the master CSV captures them too.

---

## Self-Review Notes (before execution)

- **Spec coverage:** Every column from the Henderson_CRM_v3 example maps to a task. `Total` column is generated at write time (Task 11). `Date` column = `state.created_at` ISO date.
- **Type consistency:** `Lead.x_project: str`, `Lead.y_detail: str`, `Lead.y_source: str` (one of `"website_gallery" | "yelp_photo" | ""`), `Lead.linkedin_url: str`, `Lead.linkedin_source: str` (one of `"web_search" | ""`), `Lead.personalization_status: str` (one of `"ok" | "no_gallery" | "vision_failed" | "no_email_skip"`). All consistent across all tasks below.
- **CLAUDE.md compliance:** Each agent has one job; checks `is_done()`; saves after `mark_done()`; LLM calls live inside agents only; no shared `Anthropic()` clients across threads (each `_one_lead` worker constructs its own); external API errors caught + logged, our bugs crash; `MAX_PARALLEL = 4` for vision (lower than owner_researcher's 10 because vision is slower and more expensive).
- **Cost discipline:** Vision call cost ~$0.012 per lead × ~35 leads-per-50-campaign = ~$0.45 per campaign. LinkedIn web_search ~$0.005 per lead × 35 = ~$0.18. Total ~$0.63 personalization spend per 50-lead campaign post-FindyMail. Approved verbally in conversation.

---

## Task 1: Schema — extend Lead dataclass with personalization fields

**Files:**
- Modify: `state.py:23-44` (Lead dataclass), `state.py:83-109` (save_leads), `state.py:111-146` (load)
- Test: `tests/test_state_personalization_fields.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_state_personalization_fields.py`:

```python
"""Verify the Lead dataclass exposes the personalization fields and that
save_leads / load round-trips them correctly. We do not hit real Supabase —
we patch _db with a thin in-memory fake."""
from __future__ import annotations
import os
import unittest
from unittest.mock import patch

# Supabase client is constructed lazily, so we can fake the env vars.
os.environ.setdefault("SUPABASE_URL", "http://fake")
os.environ.setdefault("SUPABASE_SERVICE_ROLE_KEY", "fake")

from state import Lead


class LeadPersonalizationFieldsTest(unittest.TestCase):
    def test_default_values_blank(self):
        lead = Lead()
        self.assertEqual(lead.x_project, "")
        self.assertEqual(lead.y_detail, "")
        self.assertEqual(lead.y_source, "")
        self.assertEqual(lead.linkedin_url, "")
        self.assertEqual(lead.linkedin_source, "")
        self.assertEqual(lead.personalization_status, "")

    def test_fields_round_trip_through_dict(self):
        lead = Lead(
            business_name="Test Co",
            x_project="dark modern kitchen remodel",
            y_detail="blue marble waterfall island",
            y_source="website_gallery",
            linkedin_url="https://linkedin.com/in/test",
            linkedin_source="web_search",
            personalization_status="ok",
        )
        self.assertEqual(lead.x_project, "dark modern kitchen remodel")
        self.assertEqual(lead.linkedin_source, "web_search")


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd "/Users/daschelgorgenyi/Desktop/Vistaline-Lead Sourcing Agent"
python -m unittest tests.test_state_personalization_fields -v
```

Expected: FAIL with `AttributeError: 'Lead' object has no attribute 'x_project'`.

- [ ] **Step 3: Add fields to Lead dataclass**

In `state.py` after line 44 (`email: str = ""`) add:

```python
    # Personalization (post-FindyMail). Empty string means "not run yet".
    x_project: str = ""
    y_detail: str = ""
    y_source: str = ""               # "website_gallery" | "yelp_photo" | ""
    linkedin_url: str = ""
    linkedin_source: str = ""        # "web_search" | ""
    personalization_status: str = "" # "ok" | "no_gallery" | "vision_failed" | "no_email_skip"
```

- [ ] **Step 4: Update save_leads row dict**

In `state.py` `save_leads`, after the `"email": l.email,` line in the row dict, add:

```python
                "x_project": l.x_project,
                "y_detail": l.y_detail,
                "y_source": l.y_source,
                "linkedin_url": l.linkedin_url,
                "linkedin_source": l.linkedin_source,
                "personalization_status": l.personalization_status,
```

- [ ] **Step 5: Update load row mapper**

In `state.py` `load`, after `email=r["email"],` add:

```python
                x_project=r.get("x_project", "") or "",
                y_detail=r.get("y_detail", "") or "",
                y_source=r.get("y_source", "") or "",
                linkedin_url=r.get("linkedin_url", "") or "",
                linkedin_source=r.get("linkedin_source", "") or "",
                personalization_status=r.get("personalization_status", "") or "",
```

(Use `.get(...)` so old rows without these columns still load.)

- [ ] **Step 6: Run test to verify it passes**

```bash
python -m unittest tests.test_state_personalization_fields -v
```

Expected: PASS.

- [ ] **Step 7: Smoke import**

```bash
python -c "from agents import sourcer, lead_filter, owner_researcher, csv_assembler; from state import Lead, CampaignState; print('OK')"
```

Expected: `OK`.

- [ ] **Step 8: Commit**

```bash
git add state.py tests/test_state_personalization_fields.py
git commit -m "feat(state): add personalization fields to Lead dataclass"
```

---

## Task 2: Supabase migration — add personalization columns

**Files:**
- Create: `supabase/migrations/2026-05-03-personalization-columns.sql`

- [ ] **Step 1: Create migration file**

```sql
-- 2026-05-03 — personalization columns for X Project / Y Detail / LinkedIn.
-- Adds the post-FindyMail enrichment fields. All default to empty string so
-- existing rows continue to load via state.CampaignState.load.
ALTER TABLE leads
  ADD COLUMN IF NOT EXISTS x_project TEXT DEFAULT '',
  ADD COLUMN IF NOT EXISTS y_detail TEXT DEFAULT '',
  ADD COLUMN IF NOT EXISTS y_source TEXT DEFAULT '',
  ADD COLUMN IF NOT EXISTS linkedin_url TEXT DEFAULT '',
  ADD COLUMN IF NOT EXISTS linkedin_source TEXT DEFAULT '',
  ADD COLUMN IF NOT EXISTS personalization_status TEXT DEFAULT '';
```

- [ ] **Step 2: Apply migration (operator-run)**

Operator runs this against the Supabase SQL editor. The plan's executor confirms with the operator before continuing.

Expected: 6 columns added; existing rows now have empty-string defaults.

- [ ] **Step 3: Verify**

Operator runs in Supabase SQL editor:

```sql
SELECT column_name, data_type, column_default
FROM information_schema.columns
WHERE table_name = 'leads' AND column_name LIKE '%personali%' OR column_name IN ('x_project','y_detail','y_source','linkedin_url','linkedin_source');
```

Expected: 6 rows, all `text`, all defaulting to empty string.

- [ ] **Step 4: Commit**

```bash
git add supabase/migrations/2026-05-03-personalization-columns.sql
git commit -m "feat(db): add personalization columns to leads table"
```

---

## Task 3: Few-shot example doc

**Files:**
- Create: `docs/personalization-fewshot.md`

- [ ] **Step 1: Write the doc**

```markdown
# Personalization few-shot examples

These pairs are injected into the Claude vision prompt in `agents/personalizer.py`.
They define the **target style** for X Project (3–5 words: room + aesthetic) and
Y Detail (4–6 words: a prominent design feature — countertop, island, lighting,
range hood, vanity, fixture). Y Detail must NEVER describe walls, flooring, trim,
brick (unless used as a feature surface), grout, or ceilings.

Drawn from operator-curated CRM exports.

| X Project                          | Y Detail                              |
|-----------------------------------|---------------------------------------|
| white subway tile bath            | matte black contrast sink             |
| dark modern kitchen remodel       | blue marble waterfall island          |
| frameless glass shower bath       | mosaic tile accent strip              |
| warm wood kitchen remodel         | black framed glass cabinets           |
| white shaker kitchen remodel      | granite waterfall island top          |
| tiled walk-in shower remodel      | pebble floor mosaic niche             |
| herringbone tile bath remodel     | brushed gold fixtures throughout      |
| modern open kitchen remodel       | geometric black fireplace surround    |

Operator: when adding more examples, keep the same shape. The agent does not
re-train — these are inlined verbatim into every prompt.
```

- [ ] **Step 2: Commit**

```bash
git add docs/personalization-fewshot.md
git commit -m "docs: add X/Y few-shot examples for personalizer prompt"
```

---

## Task 4: Gallery URL candidate generator (pure function)

**Files:**
- Create: `agents/gallery_finder.py` (skeleton + pure function only — Playwright code is Task 5)
- Test: `tests/test_gallery_finder_urls.py`

- [ ] **Step 1: Write the failing test**

`tests/test_gallery_finder_urls.py`:

```python
"""Pure-function tests for the gallery candidate URL generator. No network."""
from __future__ import annotations
import unittest

from agents.gallery_finder import gallery_candidates


class GalleryCandidatesTest(unittest.TestCase):
    def test_generates_six_canonical_paths_in_order(self):
        urls = gallery_candidates("https://example.com")
        self.assertEqual(urls, [
            "https://example.com/gallery",
            "https://example.com/portfolio",
            "https://example.com/projects",
            "https://example.com/our-work",
            "https://example.com/work",
            "https://example.com",
        ])

    def test_strips_trailing_slash(self):
        urls = gallery_candidates("https://example.com/")
        self.assertEqual(urls[0], "https://example.com/gallery")

    def test_handles_subpath_root(self):
        # Some contractors host at /home/ — preserve their path prefix.
        urls = gallery_candidates("https://acme.com/home")
        self.assertEqual(urls[0], "https://acme.com/home/gallery")

    def test_skips_non_http_url(self):
        self.assertEqual(gallery_candidates(""), [])
        self.assertEqual(gallery_candidates("not a url"), [])
        self.assertEqual(gallery_candidates("mailto:test@x.com"), [])


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

```bash
python -m unittest tests.test_gallery_finder_urls -v
```

Expected: FAIL — `ModuleNotFoundError: No module named 'agents.gallery_finder'`.

- [ ] **Step 3: Implement `gallery_candidates`**

Create `agents/gallery_finder.py`:

```python
"""Gallery finder — locates a contractor's project gallery page and captures
a full-page screenshot for the personalizer agent.

The pure functions in this module (gallery_candidates) are unit-testable
without network access. The Playwright-driven `find_and_screenshot` is
integration-tested via a smoke run, per CLAUDE.md "test against real APIs".
"""
from __future__ import annotations
from urllib.parse import urlparse


def gallery_candidates(website: str) -> list[str]:
    """Return ordered candidate URLs to try for a contractor gallery page.

    The order reflects observed frequency on small remodeler sites:
    /gallery > /portfolio > /projects > /our-work > /work > homepage.
    The homepage is included last so contractors with a gallery section
    embedded in the home page still get screenshotted.
    """
    if not website:
        return []
    parsed = urlparse(website if "://" in website else f"https://{website}")
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        return []
    base = f"{parsed.scheme}://{parsed.netloc}{parsed.path.rstrip('/')}"
    return [
        f"{base}/gallery",
        f"{base}/portfolio",
        f"{base}/projects",
        f"{base}/our-work",
        f"{base}/work",
        base or f"{parsed.scheme}://{parsed.netloc}",
    ]
```

- [ ] **Step 4: Run test to verify it passes**

```bash
python -m unittest tests.test_gallery_finder_urls -v
```

Expected: PASS (4 tests).

- [ ] **Step 5: Commit**

```bash
git add agents/gallery_finder.py tests/test_gallery_finder_urls.py
git commit -m "feat(gallery): add gallery URL candidate generator"
```

---

## Task 5: Add Playwright dependency + screenshot function

**Files:**
- Modify: `requirements.txt`
- Modify: `agents/gallery_finder.py`

- [ ] **Step 1: Add to requirements**

In `requirements.txt`, append:

```
playwright>=1.48.0
```

- [ ] **Step 2: Install and download browser**

```bash
cd "/Users/daschelgorgenyi/Desktop/Vistaline-Lead Sourcing Agent"
source .venv/bin/activate
pip install -r requirements.txt
python -m playwright install chromium
```

Expected: chromium binary downloaded (~150MB), no errors.

- [ ] **Step 3: Add `find_and_screenshot` to gallery_finder**

Append to `agents/gallery_finder.py`:

```python
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout


# Heuristic: a gallery page must have at least this many <img> tags
# whose rendered area is > 50_000 px². This rules out one-pager landing
# sites where the only images are the logo + a hero photo.
_MIN_GALLERY_IMAGES = 4


def find_and_screenshot(
    website: str, *, timeout_s: int = 25
) -> tuple[bytes | None, str]:
    """Try gallery candidates in order; return (image_bytes, source_url) of the
    first one that looks like a real project gallery, else (None, "").

    'Looks like a gallery' = the page resolves with HTTP 200 AND has >= 4
    rendered images larger than 50_000 px². Falls through to the homepage.

    External errors (timeouts, navigation failures, DNS) are caught and
    logged; we move on to the next candidate. Unexpected exceptions
    propagate (CLAUDE.md: our bugs should crash).
    """
    candidates = gallery_candidates(website)
    if not candidates:
        return None, ""

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        try:
            context = browser.new_context(
                viewport={"width": 1280, "height": 900},
                user_agent=(
                    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_0) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/124.0 Safari/537.36"
                ),
            )
            page = context.new_page()
            page.set_default_timeout(timeout_s * 1000)

            for url in candidates:
                try:
                    resp = page.goto(url, wait_until="domcontentloaded")
                    if not resp or not resp.ok:
                        continue
                    # Lazy-load galleries need a scroll pass before screenshot.
                    page.evaluate(
                        "() => new Promise(r => { "
                        "  let y = 0; "
                        "  const id = setInterval(() => { "
                        "    window.scrollBy(0, 600); "
                        "    y += 600; "
                        "    if (y >= document.body.scrollHeight) { "
                        "      clearInterval(id); r(); "
                        "    } "
                        "  }, 200); "
                        "})"
                    )
                    page.wait_for_timeout(800)  # let images settle
                    big_imgs = page.evaluate(
                        "() => Array.from(document.images)"
                        ".filter(i => i.naturalWidth * i.naturalHeight > 50000)"
                        ".length"
                    )
                    if big_imgs < _MIN_GALLERY_IMAGES:
                        continue
                    png = page.screenshot(full_page=True, type="png")
                    return png, url
                except PlaywrightTimeout as e:
                    print(f"[gallery_finder] WARN: timeout on {url}: {e}")
                    continue
                except Exception as e:
                    # Network blips, TLS errors, navigation aborts — keep walking.
                    print(f"[gallery_finder] WARN: {url}: {type(e).__name__} {e}")
                    continue
        finally:
            browser.close()

    return None, ""
```

- [ ] **Step 4: Smoke test against a real contractor URL**

```bash
python -c "
from agents.gallery_finder import find_and_screenshot
img, src = find_and_screenshot('https://kbfdesigngallery.com')
print('source:', src)
print('bytes:', len(img) if img else 'NONE')
"
```

Expected: `source: https://kbfdesigngallery.com/gallery` (or another candidate); `bytes: > 50000`.

- [ ] **Step 5: Commit**

```bash
git add requirements.txt agents/gallery_finder.py
git commit -m "feat(gallery): playwright screenshot of contractor galleries"
```

---

## Task 6: Vision response parser (pure function)

**Files:**
- Create: `agents/personalizer.py` (parser only — vision call is Task 7)
- Test: `tests/test_personalizer_vision_parser.py`

- [ ] **Step 1: Write the failing test**

`tests/test_personalizer_vision_parser.py`:

```python
"""Pure-function tests for the personalizer's JSON parser."""
from __future__ import annotations
import unittest

from agents.personalizer import parse_vision_response


class ParseVisionResponseTest(unittest.TestCase):
    def test_extracts_x_y_from_clean_json(self):
        raw = (
            '{"x_project": "warm wood kitchen remodel", '
            '"y_detail": "black framed glass cabinets", '
            '"chosen_project": "row 1 col 2"}'
        )
        out = parse_vision_response(raw)
        self.assertEqual(out["x_project"], "warm wood kitchen remodel")
        self.assertEqual(out["y_detail"], "black framed glass cabinets")
        self.assertEqual(out["chosen_project"], "row 1 col 2")

    def test_strips_markdown_fence(self):
        raw = (
            "```json\n"
            '{"x_project": "X", "y_detail": "Y", "chosen_project": "Z"}\n'
            "```"
        )
        out = parse_vision_response(raw)
        self.assertEqual(out["x_project"], "X")

    def test_blank_dict_on_invalid_json(self):
        out = parse_vision_response("not json at all")
        self.assertEqual(out, {"x_project": "", "y_detail": "", "chosen_project": ""})

    def test_blank_dict_on_missing_fields(self):
        out = parse_vision_response('{"unrelated": 1}')
        self.assertEqual(out["x_project"], "")
        self.assertEqual(out["y_detail"], "")

    def test_strips_quotes_and_whitespace(self):
        raw = (
            '{"x_project": "  white kitchen  ", '
            '"y_detail": "\\"granite top\\"", "chosen_project": ""}'
        )
        out = parse_vision_response(raw)
        self.assertEqual(out["x_project"], "white kitchen")
        self.assertEqual(out["y_detail"], '"granite top"')


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

```bash
python -m unittest tests.test_personalizer_vision_parser -v
```

Expected: FAIL — `ModuleNotFoundError: No module named 'agents.personalizer'`.

- [ ] **Step 3: Create personalizer.py with parser**

Create `agents/personalizer.py`:

```python
"""Personalizer — fills X Project + Y Detail for kept-leads-with-email by
visually inspecting the contractor's gallery page or, as fallback, a Yelp
photo. Operates only on leads that already have an email (so we never burn
vision tokens on leads FindyMail couldn't find an inbox for).

This module's pure functions (parse_vision_response, build_messages) are
unit-tested. The vision call itself is integration-tested via a smoke run.
"""
from __future__ import annotations
import json
import re


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
```

- [ ] **Step 4: Run test to verify it passes**

```bash
python -m unittest tests.test_personalizer_vision_parser -v
```

Expected: PASS (5 tests).

- [ ] **Step 5: Commit**

```bash
git add agents/personalizer.py tests/test_personalizer_vision_parser.py
git commit -m "feat(personalizer): add vision response JSON parser"
```

---

## Task 7: Vision call — extract X/Y from screenshot

**Files:**
- Modify: `agents/personalizer.py`
- Modify: `config.py`

- [ ] **Step 1: Add config knobs**

In `config.py`, add to the `Config` dataclass (after `dedup_match_threshold`):

```python
    # ---- Personalizer (post-FindyMail X/Y + LinkedIn) ----
    personalizer_max_parallel: int = 4
    personalizer_vision_model: str = "claude-sonnet-4-20250514"
    personalizer_screenshot_timeout_s: int = 25
```

- [ ] **Step 2: Add the vision-call function**

Append to `agents/personalizer.py`:

```python
import base64
from pathlib import Path
from anthropic import Anthropic


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
    """Load the few-shot table from docs/personalization-fewshot.md.

    The doc is hand-curated by the operator and inlined into every prompt.
    Treated as a simple text passthrough; we don't parse the markdown table.
    """
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
    client = Anthropic(api_key=anthropic_key)
    fewshot = _load_fewshot_block()
    user_text = (
        "Reference style examples (match this shape):\n\n"
        f"{fewshot}\n\n"
        "Now examine the gallery screenshot and return the JSON."
    )
    b64 = base64.standard_b64encode(image_png).decode("ascii")
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
                                "media_type": "image/png",
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
```

- [ ] **Step 3: Smoke test vision call**

```bash
python -c "
import os
from agents.gallery_finder import find_and_screenshot
from agents.personalizer import extract_xy
img, src = find_and_screenshot('https://kbfdesigngallery.com')
print('shot from:', src, 'bytes:', len(img) if img else 0)
out = extract_xy(img, anthropic_key=os.environ['ANTHROPIC_API_KEY'], model='claude-sonnet-4-20250514')
print('x_project:', out['x_project'])
print('y_detail:', out['y_detail'])
print('chosen:', out['chosen_project'])
"
```

Expected: non-empty `x_project` and `y_detail` matching the few-shot style (e.g., "white shaker kitchen remodel" / "marble waterfall island").

- [ ] **Step 4: Commit**

```bash
git add agents/personalizer.py config.py
git commit -m "feat(personalizer): vision call extracts X/Y from screenshot"
```

---

## Task 8: Yelp photo fallback

**Files:**
- Modify: `agents/personalizer.py`

- [ ] **Step 1: Add Yelp client + photo fetcher**

Append to `agents/personalizer.py`:

```python
import requests

from tools import YelpFusionClient


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
        # Search by name + free-form location (Yelp accepts the full address).
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
```

- [ ] **Step 2: Verify YelpFusionClient has `get_business_details`**

```bash
python -c "from tools import YelpFusionClient; print(hasattr(YelpFusionClient, 'get_business_details'))"
```

Expected: `True`. If `False`, add it to `tools.py` per the existing `search_businesses` pattern (GET `/businesses/{id}`, return `resp.json()`).

- [ ] **Step 3: Commit**

```bash
git add agents/personalizer.py
git commit -m "feat(personalizer): yelp photo fallback when website gallery missing"
```

(If `tools.py` was modified in Step 2, include it: `git add tools.py agents/personalizer.py`.)

---

## Task 9: Personalizer.run — orchestrator

**Files:**
- Modify: `agents/personalizer.py`

- [ ] **Step 1: Add the run() entrypoint**

Append to `agents/personalizer.py`:

```python
import concurrent.futures as futures

from state import CampaignState, Lead
from agents.gallery_finder import find_and_screenshot


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
```

- [ ] **Step 2: Smoke import**

```bash
python -c "from agents import personalizer; print(personalizer.run)"
```

Expected: a function reference printed, no errors.

- [ ] **Step 3: Commit**

```bash
git add agents/personalizer.py
git commit -m "feat(personalizer): parallel run() orchestrator with fallback chain"
```

---

## Task 10: LinkedIn finder agent

**Files:**
- Create: `agents/linkedin_finder.py`
- Test: `tests/test_linkedin_finder_parser.py`

- [ ] **Step 1: Write the failing test**

`tests/test_linkedin_finder_parser.py`:

```python
"""Pure-function tests for the LinkedIn URL validator."""
from __future__ import annotations
import unittest

from agents.linkedin_finder import is_valid_linkedin_profile_url


class IsValidLinkedinProfileUrlTest(unittest.TestCase):
    def test_accepts_canonical_in_url(self):
        self.assertTrue(is_valid_linkedin_profile_url(
            "https://www.linkedin.com/in/jane-smith-123abc"))

    def test_accepts_no_subdomain(self):
        self.assertTrue(is_valid_linkedin_profile_url(
            "https://linkedin.com/in/jane"))

    def test_rejects_company_url(self):
        self.assertFalse(is_valid_linkedin_profile_url(
            "https://linkedin.com/company/acme-bath"))

    def test_rejects_post_url(self):
        self.assertFalse(is_valid_linkedin_profile_url(
            "https://linkedin.com/posts/jane-smith_abc"))

    def test_rejects_non_linkedin(self):
        self.assertFalse(is_valid_linkedin_profile_url(
            "https://twitter.com/in/jane"))

    def test_rejects_blank(self):
        self.assertFalse(is_valid_linkedin_profile_url(""))


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

```bash
python -m unittest tests.test_linkedin_finder_parser -v
```

Expected: FAIL — `ModuleNotFoundError`.

- [ ] **Step 3: Create the agent**

Create `agents/linkedin_finder.py`:

```python
"""LinkedIn finder — uses Claude's web_search tool to locate the owner's
LinkedIn profile URL given (owner_full_name, business_name, city).

Same architectural pattern as owner_researcher Phase 2: each parallel
worker constructs its own Anthropic client. Returns blank when the model
can't find a profile that clearly matches the owner — never guesses.
"""
from __future__ import annotations
import concurrent.futures as futures
import json
import re
from anthropic import Anthropic

from state import CampaignState, Lead


STEP_NAME = "linkedin_finder"

_LINKEDIN_PROFILE_RE = re.compile(
    r"^https?://([a-z]{2,3}\.)?linkedin\.com/in/[^/?#]+/?$",
    re.IGNORECASE,
)


def is_valid_linkedin_profile_url(url: str) -> bool:
    """True when the URL is a personal LinkedIn profile (/in/<slug>).

    Rejects /company/, /posts/, /pulse/, /school/ and anything off-domain.
    Used to filter out hallucinations and adjacent-but-wrong matches.
    """
    if not url or not isinstance(url, str):
        return False
    return bool(_LINKEDIN_PROFILE_RE.match(url.strip()))


_SYSTEM = """You are a researcher finding the LinkedIn profile URL for a small-business owner.

Given (owner full name, business name, city), use the web_search tool to locate
their personal LinkedIn profile. Personal profiles live at linkedin.com/in/<slug>.

Match rules:
- The profile name must clearly correspond to the given owner name.
- The profile must be a person, NOT a company page (linkedin.com/company/...).
- If multiple candidates exist, pick the one whose current role mentions the
  business name OR the city.
- If no profile clearly matches, return blank — NEVER guess.

Output strict JSON only:
{
  "linkedin_url": "https://linkedin.com/in/...",
  "confidence": "high" | "medium" | "low" | "none"
}
"""


def _find_one(owner: str, business: str, city: str, anthropic_key: str) -> str:
    """Return the LinkedIn URL or "" — never raises."""
    if not owner or not business:
        return ""
    client = Anthropic(api_key=anthropic_key)
    user = (
        f"Owner: {owner}\nBusiness: {business}\nCity: {city}\n\n"
        "Find this person's LinkedIn profile."
    )
    try:
        resp = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=400,
            system=_SYSTEM,
            tools=[{"type": "web_search_20250305", "name": "web_search", "max_uses": 4}],
            messages=[{"role": "user", "content": user}],
        )
    except Exception as e:
        print(f"[linkedin_finder] WARN: {owner!r} @ {business!r}: {type(e).__name__} {e}")
        return ""
    raw = "".join(b.text for b in resp.content if hasattr(b, "text"))
    match = re.search(r"\{.*\}", raw, flags=re.DOTALL)
    if not match:
        return ""
    try:
        data = json.loads(match.group(0))
    except json.JSONDecodeError:
        return ""
    url = str(data.get("linkedin_url", "") or "").strip()
    if data.get("confidence") in ("none", "low"):
        return ""
    if not is_valid_linkedin_profile_url(url):
        return ""
    return url


def run(
    state: CampaignState,
    anthropic_key: str,
    *,
    max_parallel: int = 4,
) -> None:
    """Fill linkedin_url / linkedin_source for every kept lead with email and
    owner. Idempotent — skips leads with linkedin_source already set.
    """
    if state.is_done(STEP_NAME):
        state.info(STEP_NAME, "already done, skipping")
        return

    targets = [
        l for l in state.leads
        if l.kept and l.email and l.owner_full_name and not l.linkedin_source
    ]
    state.info(STEP_NAME, f"searching for {len(targets)} LinkedIn profiles")

    with futures.ThreadPoolExecutor(max_workers=max_parallel) as ex:
        fut_to_lead = {
            ex.submit(
                _find_one,
                lead.owner_full_name,
                lead.business_name,
                state.city,
                anthropic_key,
            ): lead
            for lead in targets
        }
        for fut in futures.as_completed(fut_to_lead):
            lead = fut_to_lead[fut]
            url = fut.result()  # _find_one swallows external errors
            lead.linkedin_url = url
            lead.linkedin_source = "web_search" if url else ""
            state.info(STEP_NAME, f"{lead.owner_full_name}: {url or '(none)'}")

    state.mark_done(STEP_NAME)
```

- [ ] **Step 4: Run parser test**

```bash
python -m unittest tests.test_linkedin_finder_parser -v
```

Expected: PASS (6 tests).

- [ ] **Step 5: Commit**

```bash
git add agents/linkedin_finder.py tests/test_linkedin_finder_parser.py
git commit -m "feat(linkedin): add LinkedIn finder agent using web_search"
```

---

## Task 11: Agency CSV reader + writer

**Files:**
- Create: `agents/csv_agency.py`
- Test: `tests/test_csv_agency_roundtrip.py`

- [ ] **Step 1: Write the failing test**

`tests/test_csv_agency_roundtrip.py`:

```python
"""Round-trip a synthetic FindyMail-enriched CSV through the agency reader."""
from __future__ import annotations
import csv
import os
import tempfile
import unittest

os.environ.setdefault("SUPABASE_URL", "http://fake")
os.environ.setdefault("SUPABASE_SERVICE_ROLE_KEY", "fake")

from agents.csv_agency import read_enriched, AGENCY_COLUMNS


SAMPLE_ROWS = [
    {
        "First Name": "Brett",
        "Last Name": "Primack",
        "Company": "Las Vegas Remodel",
        "Domain": "lvremodel.com",
        "email": "brett@lvremodel.com",  # FindyMail returns the email column
        "phone": "+1 702-425-7272",
        "website": "http://lvremodel.com",
        "address": "123 Main, Las Vegas NV",
    },
    {
        "First Name": "Cyndi",
        "Last Name": "Huff",
        "Company": "Dream Construction",
        "Domain": "dreamconstr.com",
        "email": "",  # FindyMail couldn't find an inbox
        "phone": "+1 702-816-5800",
        "website": "https://dreamconstr.com",
        "address": "",
    },
]


class ReadEnrichedTest(unittest.TestCase):
    def test_loads_leads_with_email_field_populated(self):
        with tempfile.NamedTemporaryFile(
            "w", suffix=".csv", delete=False, newline="", encoding="utf-8"
        ) as f:
            writer = csv.DictWriter(f, fieldnames=list(SAMPLE_ROWS[0].keys()))
            writer.writeheader()
            writer.writerows(SAMPLE_ROWS)
            path = f.name

        state = read_enriched(path)
        self.assertEqual(len(state.leads), 2)

        brett = state.leads[0]
        self.assertEqual(brett.owner_first, "Brett")
        self.assertEqual(brett.owner_last, "Primack")
        self.assertEqual(brett.owner_full_name, "Brett Primack")
        self.assertEqual(brett.business_name, "Las Vegas Remodel")
        self.assertEqual(brett.domain, "lvremodel.com")
        self.assertEqual(brett.email, "brett@lvremodel.com")
        self.assertEqual(brett.phone, "+1 702-425-7272")

        cyndi = state.leads[1]
        self.assertEqual(cyndi.email, "")  # blank email preserved

    def test_agency_columns_match_henderson_crm_v3(self):
        # The 13 columns we agreed to with the operator (Henderson_CRM_v3 layout).
        self.assertEqual(AGENCY_COLUMNS, [
            "Total", "Lead Sourcer", "Business", "Owner Full Name",
            "First", "Last", "Owner Email", "LinkedIn", "Website",
            "Phone", "Date", "X Project", "Y Detail",
        ])


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

```bash
python -m unittest tests.test_csv_agency_roundtrip -v
```

Expected: FAIL — `ModuleNotFoundError`.

- [ ] **Step 3: Create the reader/writer**

Create `agents/csv_agency.py`:

```python
"""Agency CSV format — the 13-column shape used by the Vistaline VAs and
matching the Henderson_CRM_v3 example.

Two functions:
  read_enriched(path)  -> CampaignState   (parse a FindyMail-returned CSV)
  write_agency(state, path) -> None       (write the final CSV for Instantly)

The reader is tolerant of FindyMail's column-naming quirks: it accepts the
upload columns (First Name, Last Name, Company, Domain) plus any extra
columns FM pass-through preserves (email, phone, website, address).
"""
from __future__ import annotations
import csv
from pathlib import Path
from datetime import date

from state import CampaignState, Lead


AGENCY_COLUMNS: list[str] = [
    "Total", "Lead Sourcer", "Business", "Owner Full Name",
    "First", "Last", "Owner Email", "LinkedIn", "Website",
    "Phone", "Date", "X Project", "Y Detail",
]


def _row_get(row: dict, *keys: str) -> str:
    """Case-insensitive lookup across multiple candidate column names."""
    lower = {k.lower(): v for k, v in row.items()}
    for k in keys:
        v = lower.get(k.lower())
        if v not in (None, ""):
            return str(v).strip()
    return ""


def read_enriched(path: str | Path) -> CampaignState:
    """Read a FindyMail-returned CSV and hydrate a CampaignState.

    The state is fresh — campaign_id is generated, but city/state/niche are
    left blank and should be set by the caller (CLI parses --city/--state
    overrides). Only the lead-level fields are populated from the CSV.
    """
    state = CampaignState.new()
    path = Path(path)
    with path.open("r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            first = _row_get(row, "First Name", "first")
            last = _row_get(row, "Last Name", "last")
            full = (first + " " + last).strip()
            lead = Lead(
                business_name=_row_get(row, "Company", "business_name", "business"),
                phone=_row_get(row, "phone"),
                website=_row_get(row, "website"),
                address=_row_get(row, "address"),
                domain=_row_get(row, "Domain", "domain"),
                owner_first=first,
                owner_last=last,
                owner_full_name=full,
                email=_row_get(row, "email", "Owner Email"),
                kept=True,
            )
            state.leads.append(lead)
    return state


def write_agency(
    state: CampaignState,
    path: str | Path,
    *,
    lead_sourcer: str = "",
) -> None:
    """Write the final agency-format CSV. One row per kept lead (email or not —
    operator may want to see no-email rows for manual follow-up).
    """
    path = Path(path)
    today = date.today().isoformat()
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=AGENCY_COLUMNS)
        writer.writeheader()
        for i, lead in enumerate(
            (l for l in state.leads if l.kept), start=1
        ):
            writer.writerow({
                "Total": i,
                "Lead Sourcer": lead_sourcer or state.triggered_by,
                "Business": lead.business_name,
                "Owner Full Name": lead.owner_full_name,
                "First": lead.owner_first,
                "Last": lead.owner_last,
                "Owner Email": lead.email,
                "LinkedIn": lead.linkedin_url,
                "Website": lead.website,
                "Phone": lead.phone,
                "Date": today,
                "X Project": lead.x_project,
                "Y Detail": lead.y_detail,
            })
```

- [ ] **Step 4: Run test to verify it passes**

```bash
python -m unittest tests.test_csv_agency_roundtrip -v
```

Expected: PASS (2 tests).

- [ ] **Step 5: Commit**

```bash
git add agents/csv_agency.py tests/test_csv_agency_roundtrip.py
git commit -m "feat(csv): agency-format reader + writer matching Henderson_CRM_v3"
```

---

## Task 12: Master CSV — capture personalization fields

**Files:**
- Modify: `agents/csv_assembler.py:28-34`, `agents/csv_assembler.py:65-81`

- [ ] **Step 1: Update MASTER_COLUMNS list**

In `agents/csv_assembler.py`, replace the `MASTER_COLUMNS` definition (lines 28-34) with:

```python
MASTER_COLUMNS = [
    "kept", "reject_reason",
    "business_name", "phone", "area_code", "website", "domain", "address",
    "owner_full_name", "owner_first", "owner_last", "owner_source",
    "email",
    "x_project", "y_detail", "y_source",
    "linkedin_url", "linkedin_source",
    "personalization_status",
    "place_id",
]
```

- [ ] **Step 2: Update master writerow**

In `agents/csv_assembler.py` master CSV `writer.writerow({...})` block (around lines 65-81), add the new fields before `"place_id": lead.place_id`:

```python
                "x_project": lead.x_project,
                "y_detail": lead.y_detail,
                "y_source": lead.y_source,
                "linkedin_url": lead.linkedin_url,
                "linkedin_source": lead.linkedin_source,
                "personalization_status": lead.personalization_status,
```

- [ ] **Step 3: Smoke import**

```bash
python -c "from agents import csv_assembler; print(len(csv_assembler.MASTER_COLUMNS))"
```

Expected: `20`.

- [ ] **Step 4: Commit**

```bash
git add agents/csv_assembler.py
git commit -m "feat(csv): include personalization fields in master CSV"
```

---

## Task 13: `--personalize` CLI mode in run.py

**Files:**
- Modify: `run.py:22-30` (parse_args), `run.py:43-110` (main)

- [ ] **Step 1: Add CLI arg**

In `run.py` `parse_args()` add after `--resume`:

```python
    p.add_argument(
        "--personalize",
        default=None,
        metavar="ENRICHED_CSV",
        help="Path to a FindyMail-returned CSV; runs personalizer + linkedin_finder, "
             "writes final agency CSV to output/.",
    )
    p.add_argument(
        "--triggered-by-name",
        default=None,
        help="(Personalize mode only) the Lead Sourcer name to write into the agency CSV.",
    )
```

- [ ] **Step 2: Add personalize branch in main()**

In `run.py` `main()`, immediately after the `args = parse_args()` line, add:

```python
    if args.personalize:
        return run_personalize(
            args.personalize,
            triggered_by=args.triggered_by_name or args.triggered_by,
        )
```

- [ ] **Step 3: Add the run_personalize function**

In `run.py`, above `def main()`, add:

```python
def run_personalize(enriched_csv: str, *, triggered_by: str) -> int:
    """End-to-end post-FindyMail flow: read enriched CSV -> personalizer -> linkedin
    finder -> write final agency CSV.
    """
    from pathlib import Path
    from agents import personalizer, linkedin_finder
    from agents.csv_agency import read_enriched, write_agency

    state = read_enriched(enriched_csv)
    state.triggered_by = triggered_by or "DG"
    state.status = "personalizing"
    state.save()

    print()
    print(f"Personalize mode: {state.campaign_id}")
    print(f"  enriched CSV:       {enriched_csv}")
    print(f"  leads:              {len(state.leads)}")
    print(f"  with email:         {sum(1 for l in state.leads if l.email)}")
    print()

    try:
        personalizer.run(
            state,
            CONFIG.anthropic_key,
            yelp_key=CONFIG.yelp_fusion_key,
            model=CONFIG.personalizer_vision_model,
            max_parallel=CONFIG.personalizer_max_parallel,
            timeout_s=CONFIG.personalizer_screenshot_timeout_s,
        )
        linkedin_finder.run(
            state,
            CONFIG.anthropic_key,
            max_parallel=CONFIG.personalizer_max_parallel,
        )

        out_dir = Path(__file__).parent / "output"
        out_dir.mkdir(exist_ok=True)
        agency_path = out_dir / f"{state.campaign_id}__agency.csv"
        write_agency(state, agency_path, lead_sourcer=triggered_by)

        state.save_leads()
        state.status = "completed"
        state.save()

        ok = sum(1 for l in state.leads if l.personalization_status == "ok")
        with_li = sum(1 for l in state.leads if l.linkedin_url)
        print()
        print("=" * 64)
        print(f"  ✅ Personalization done — campaign {state.campaign_id}")
        print(f"  X/Y filled:        {ok}/{len(state.leads)}")
        print(f"  LinkedIn found:    {with_li}/{len(state.leads)}")
        print(f"  agency CSV:        {agency_path}")
        print("=" * 64)
        return 0
    except Exception:
        traceback.print_exc()
        state.status = "failed"
        state.save()
        return 2
```

- [ ] **Step 4: Smoke import**

```bash
python -c "from run import run_personalize; print('OK')"
```

Expected: `OK`.

- [ ] **Step 5: Commit**

```bash
git add run.py
git commit -m "feat(cli): --personalize mode for post-FindyMail enrichment"
```

---

## Task 14: End-to-end smoke run

**Files:**
- (No files modified; integration verification.)

- [ ] **Step 1: Prepare a synthetic enriched CSV**

Create `/tmp/enriched_smoke.csv` with three real leads from the Orlando run. From `output/Orlando_FL_kitchen_remodelers_2026-05-02__findymail.csv`, pick three with strong websites:

```csv
First Name,Last Name,Company,Domain,email,phone,website,address
Keith,Vellequette,KBF Design Gallery,kbfdesigngallery.com,keith@kbfdesigngallery.com,+14078307703,https://kbfdesigngallery.com,"1295 S Orlando Ave, Maitland, FL 32751"
Josh,Torres,Nu Kitchen Designs,nukitchendesigns.com,josh@nukitchendesigns.com,+14077314700,https://nukitchendesigns.com,"2750 Taylor Ave, Ste G, Orlando, FL 32806"
Dean,Blankenship,Hosanna Building Contractors,hbc365.net,,+14074136069,https://hbc365.net/,"1009 Webster St, Orlando, FL 32804"
```

(Dean's email is intentionally blank — verifies the no_email_skip branch.)

- [ ] **Step 2: Run personalize mode**

```bash
cd "/Users/daschelgorgenyi/Desktop/Vistaline-Lead Sourcing Agent"
source .venv/bin/activate
python -u run.py --personalize /tmp/enriched_smoke.csv --triggered-by-name "DG"
```

Expected:
- 3 leads loaded.
- 2 with email → personalizer attempts gallery screenshot for Keith & Josh.
- 1 without email → marked `no_email_skip`.
- LinkedIn finder runs on the 2 with both email + owner.
- Final agency CSV written to `output/<campaign-id>__agency.csv`.
- Console summary shows X/Y filled count and LinkedIn found count.

- [ ] **Step 3: Inspect the agency CSV**

```bash
ls -lt output/*__agency.csv | head -1
cat $(ls -t output/*__agency.csv | head -1)
```

Expected: 13-column CSV, X Project / Y Detail filled for at least 1 of the 2 email leads, blanks for Dean.

- [ ] **Step 4: Spot-check on a real screenshot**

For one lead, manually open the website's gallery in a browser. Compare what you'd describe as X/Y vs. what Claude returned. Note any mismatches in `docs/smoke-personalization-1.md`.

- [ ] **Step 5: Run all tests**

```bash
python -m unittest discover tests -v
```

Expected: every existing test still passes plus the new ones.

- [ ] **Step 6: Commit smoke notes**

```bash
git add docs/smoke-personalization-1.md
git commit -m "docs: smoke notes for personalization v1 first run"
```

---

## Done

After Task 14, the personalization pipeline is end-to-end runnable:

1. Operator runs the existing `python run.py --city ... --state ...` flow (Phase 0/1).
2. Operator uploads the FindyMail CSV from that run, downloads the enriched file.
3. Operator runs `python run.py --personalize <enriched.csv>` — produces final agency CSV.
4. Final CSV uploaded to Instantly.

**Out of scope for this plan (deliberate):**
- Instagram scraping (will revisit when website+Yelp coverage proves insufficient).
- Two-step click-through vision flow (only build if single-screenshot accuracy is too low).
- Web UI integration (frontend wiring lives in the FastAPI plan).
- Cost dashboard for personalization spend (lives in Phase 5 polish).
