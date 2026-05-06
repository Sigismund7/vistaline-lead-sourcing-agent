"""Phase 0 — Yelp profile page owner lookup.

Checks the 'Business Owner' labeled field in Yelp's 'About the Business'
section. Free: no LLM calls. The Yelp Fusion API is used only to resolve
the Yelp business alias for leads that weren't sourced from Yelp.

Failure modes: all silent fallthrough. A 403 block, no search results, or
a missing 'Business Owner' field all return confidence='none' so the
pipeline continues to Phase 1 (website crawl).
"""
from __future__ import annotations

import json
import time
import random

import requests
from bs4 import BeautifulSoup
from rapidfuzz import fuzz

from config import CONFIG
from state import Lead
from tools import YelpFusionClient


_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)
_HEADERS = {
    "User-Agent": _USER_AGENT,
    "Accept-Language": "en-US,en;q=0.9",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}
_SEARCH_CATEGORIES = "contractors,kitchen_and_bath,homeservices"
_FUZZY_THRESHOLD = 85
_PAGE_FETCH_TIMEOUT_S = 15


def _resolve_yelp_id(lead: Lead, city: str, state_abbr: str, yelp_key: str) -> str | None:
    """Return Yelp business alias for this lead.

    Uses lead.yelp_id directly if already set (no API call). Otherwise
    searches Yelp by business name + city and fuzzy-matches the top results.
    Writes the found alias back to lead.yelp_id in-memory so --resume
    (which checkpoints via state.save_leads()) skips the search next time.
    """
    if lead.yelp_id:
        return lead.yelp_id

    if not yelp_key:
        return None

    try:
        client = YelpFusionClient(api_key=yelp_key, rate_limit_qps=1.0, jitter_ms=200)
        results = client.search_businesses(
            term=lead.business_name,
            location=f"{city}, {state_abbr}",
            categories=_SEARCH_CATEGORIES,
            limit=5,
        )
    except Exception:
        return None

    best_alias: str | None = None
    best_score = 0
    for biz in results:
        result_name = biz.get("name") or ""
        score = fuzz.token_sort_ratio(lead.business_name.lower(), result_name.lower())
        if score > best_score:
            best_score = score
            best_alias = biz.get("id") or None

    if best_score >= _FUZZY_THRESHOLD and best_alias:
        lead.yelp_id = best_alias
        return best_alias

    return None


def _fetch_yelp_page(yelp_id: str) -> str | None:
    """Fetch the Yelp business profile page HTML.

    Returns None on any HTTP error or timeout so callers can silently
    fall through to the next owner-research phase.
    """
    url = f"https://www.yelp.com/biz/{yelp_id}"
    time.sleep(random.uniform(0.5, 1.5))
    try:
        resp = requests.get(url, headers=_HEADERS, timeout=_PAGE_FETCH_TIMEOUT_S)
    except requests.RequestException:
        return None

    if resp.status_code in (403, 429, 503):
        return None
    if not resp.ok:
        return None

    return resp.text


def _parse_owner_from_jsonld(html: str) -> str | None:
    """Extract owner name from JSON-LD structured data embedded in page.

    Yelp embeds schema.org Person entities for business owners in some
    markets. Returns None when no Person with an owner-role jobTitle is found.
    """
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(tag.string or "")
        except (json.JSONDecodeError, TypeError):
            continue
        items = data if isinstance(data, list) else [data]
        for item in items:
            if not isinstance(item, dict):
                continue
            if (item.get("@type") == "Person"
                    and "owner" in (item.get("jobTitle") or "").lower()
                    and item.get("name")):
                return item["name"].strip()
    return None


def _parse_owner_from_html(html: str) -> str | None:
    """Extract owner name from the 'Business Owner' label in the page HTML.

    Yelp renders 'Business Owner' as a visible text label adjacent to the
    owner's name in the 'About the Business' section. We walk every element
    containing that label text and extract the adjacent non-label text.
    """
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup.find_all(True):
        if "Business Owner" not in tag.get_text():
            continue

        block_text = tag.get_text(separator="\n", strip=True)
        lines = block_text.split("\n")
        # Only inspect lines that follow the "Business Owner" sentinel so we
        # don't accidentally return section headings that appear before it.
        found_label = False
        for line in lines:
            line = line.strip()
            if not line:
                continue
            if line == "Business Owner":
                found_label = True
                continue
            if not found_label:
                continue
            words = line.split()
            if len(words) >= 2 and not any(ch.isdigit() for ch in line):
                return line

    return None


def lookup(lead: Lead, city: str, state_abbr: str, anthropic_key: str) -> dict:
    """Phase 0: scrape Yelp profile page for the 'Business Owner' field.

    `anthropic_key` is accepted to satisfy the PhaseFn signature but is
    not used — this phase makes no LLM calls.

    Returns a dict with at minimum: owner_full_name (str), confidence (str).
    confidence is 'high' on a labeled Yelp match, 'none' otherwise.
    """
    yelp_key = CONFIG.yelp_fusion_key

    yelp_id = _resolve_yelp_id(lead, city, state_abbr, yelp_key)
    if not yelp_id:
        return {"owner_full_name": "", "confidence": "none", "phase": "yelp_profile"}

    html = _fetch_yelp_page(yelp_id)
    if not html:
        return {"owner_full_name": "", "confidence": "none", "phase": "yelp_profile"}

    profile_url = f"https://www.yelp.com/biz/{yelp_id}"

    name = _parse_owner_from_jsonld(html)
    if not name:
        name = _parse_owner_from_html(html)

    if name:
        return {
            "owner_full_name": name,
            "confidence": "high",
            "phase": "yelp_profile",
            "source_url": profile_url,
            "evidence": "Yelp Business Owner labeled field",
        }

    return {"owner_full_name": "", "confidence": "none", "phase": "yelp_profile"}
