"""Phase 2 — Houzz profile scrape owner lookup.

Searches Houzz by business name, fuzzy-matches results to the target city,
fetches the matched profile's About section, and asks Claude to extract the
owner name. Free (direct HTTP). Falls through silently on Cloudflare blocks,
no results, or confidence < medium.
"""
from __future__ import annotations

from rapidfuzz import fuzz
from anthropic import Anthropic

from state import Lead
from tools import HouzzClient
from agents.sources.owners._utils import parse_owner_json

CITY_MATCH_THRESHOLD = 85  # rapidfuzz token_sort_ratio minimum

SYSTEM_PROMPT = """You are reading the About/Overview section of a remodeling contractor's Houzz profile.

Find the owner, founder, or president of the business.

Rules:
- Only accept names with explicit ownership language: "owner", "founder", "president",
  "started by", "owned and operated by", "principal", "founded by".
- Never guess from a name alone without a title.
- Return empty if no ownership language is present.

Output JSON only:
{
  "owner_full_name": "First Last",
  "source_url": "the Houzz profile URL",
  "evidence": "the exact phrase that confirmed ownership",
  "confidence": "high" | "medium" | "low" | "none"
}
"""


def _best_match(results: list[dict], city: str) -> dict | None:
    """Return the Houzz search result whose location best matches city (score >= threshold)."""
    best_score = 0
    best_result = None
    for r in results:
        city_part = r.get("location", "").split(",")[0].strip()
        score = fuzz.token_sort_ratio(city_part.lower(), city.lower())
        if score > best_score:
            best_score = score
            best_result = r
    if best_score >= CITY_MATCH_THRESHOLD:
        return best_result
    return None


def lookup(lead: Lead, city: str, state_abbr: str, anthropic_key: str) -> dict:
    """Phase 2: search Houzz by business name, match to city, parse About text.

    Returns dict with: owner_full_name, confidence, source_url, evidence.
    Returns confidence="none" on any failure (Cloudflare, no match, etc.).
    """
    client_houzz = HouzzClient()
    results = client_houzz.search(lead.business_name)
    if not results:
        return {"owner_full_name": "", "confidence": "none"}

    match = _best_match(results, city)
    if not match:
        return {"owner_full_name": "", "confidence": "none"}

    about_text = client_houzz.get_profile_text(match["profile_url"])
    if not about_text or len(about_text.strip()) < 50:
        return {"owner_full_name": "", "confidence": "none"}

    user_msg = (
        f"Business: {lead.business_name}\n"
        f"City: {city}, {state_abbr}\n"
        f"Houzz profile URL: {match['profile_url']}\n\n"
        f"About section text:\n{about_text}"
    )

    client_claude = Anthropic(api_key=anthropic_key)
    try:
        response = client_claude.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=500,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_msg}],
        )
    except Exception as e:
        return {"owner_full_name": "", "confidence": "none", "error": str(e)}

    result = parse_owner_json(response.content[0].text.strip())
    result.setdefault("phase", "houzz")
    result.setdefault("source_url", match["profile_url"])
    return result
