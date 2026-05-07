"""Phase 0 — Yelp profile page owner lookup.

Checks the 'Business Owner' labeled field in Yelp's 'About the Business'
section. Free: no LLM calls except when a truncated last-name initial is
found (e.g. 'John S.'), which triggers one web-search call to resolve the
full last name before returning.

The Yelp Fusion API is used only to resolve the Yelp business alias for
leads that weren't sourced from Yelp.

Failure modes: all silent fallthrough. A 403 block, no search results, or
a missing 'Business Owner' field all return confidence='none' so the
pipeline continues to Phase 1 (website crawl).
"""
from __future__ import annotations

import json
import re

from anthropic import Anthropic
from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout, Error as PlaywrightError
from rapidfuzz import fuzz

from config import CONFIG
from state import Lead
from tools import YelpFusionClient
from agents.sources.owners._utils import parse_owner_json


_SEARCH_CATEGORIES = "contractors,kitchen_and_bath,homeservices"
_FUZZY_THRESHOLD = 85
_PAGE_FETCH_TIMEOUT_MS = 15_000

# Matches "John S." or "Maria R." — first word + single capital + period.
_TRUNCATED_NAME_RE = re.compile(r"^[A-Za-z]+ [A-Z]\.$")

_EXPAND_SYSTEM_PROMPT = """You are a research assistant. Given a business name, city, and a partial owner name (first name + last initial), find the owner's full last name.

Use web_search with this exact query: {query}

Look at the top results. If a result clearly shows the same person as the business owner with a full last name matching the initial, return it. If nothing clearly matches, return empty.

NEVER guess or fabricate a last name.

Output JSON only:
{{"owner_full_name": "First Last", "source_url": "URL", "confidence": "high" | "none"}}
"""


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
    """Fetch the fully-rendered Yelp business profile page HTML via Playwright.

    Uses headless Chromium so Yelp's Cloudflare bot-detection sees a real
    browser rather than a plain HTTP client. Returns None on timeout, nav
    error, or any Playwright exception so callers fall through silently.
    """
    url = f"https://www.yelp.com/biz/{yelp_id}"
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            try:
                context = browser.new_context(
                    locale="en-US",
                    viewport={"width": 1280, "height": 800},
                )
                page = context.new_page()
                page.set_default_timeout(_PAGE_FETCH_TIMEOUT_MS)
                resp = page.goto(url, wait_until="domcontentloaded")
                if resp is None or not resp.ok:
                    return None
                # Wait briefly for any deferred React hydration that may inject
                # the Business Owner section after the initial DOM paint.
                page.wait_for_timeout(800)
                return page.content()
            finally:
                browser.close()
    except (PlaywrightTimeout, PlaywrightError):
        return None
    except Exception:
        return None


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


def _expand_truncated_name(
    partial_name: str,
    business_name: str,
    city: str,
    anthropic_key: str,
) -> dict | None:
    """Try to resolve a truncated last-name initial to a full last name.

    Performs one web_search call with query:
        {business_name} {city} {first_name} {last_initial}

    Returns a result dict with confidence='high' and the expanded name if a
    confident match is found, or None if the search fails or returns nothing
    useful. Never returns a fabricated name.
    """
    if not anthropic_key:
        return None

    parts = partial_name.split()
    first_name = parts[0]
    last_initial = parts[1][0]  # strip the trailing period
    query = f"{business_name} {city} {first_name} {last_initial}"

    try:
        client = Anthropic(api_key=anthropic_key, timeout=30.0)
        response = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=500,
            system=_EXPAND_SYSTEM_PROMPT.format(query=query),
            tools=[{"type": "web_search_20250305", "name": "web_search", "max_uses": 2}],
            messages=[{"role": "user", "content": f"Find the full last name for: {partial_name}, owner of {business_name} in {city}."}],
        )
    except Exception:
        return None

    text = "".join(
        b.text for b in response.content if getattr(b, "type", "") == "text"
    ).strip()
    result = parse_owner_json(text)

    expanded = result.get("owner_full_name", "").strip()
    if not expanded or result.get("confidence") != "high":
        return None

    # Sanity check: expanded name must start with the same first name and
    # the last name must start with the expected initial.
    exp_parts = expanded.split()
    if len(exp_parts) < 2:
        return None
    if exp_parts[0].lower() != first_name.lower():
        return None
    if exp_parts[-1][0].upper() != last_initial.upper():
        return None

    result["phase"] = "yelp_profile"
    return result


def lookup(lead: Lead, city: str, state_abbr: str, anthropic_key: str) -> dict:
    """Phase 0: scrape Yelp profile page for the 'Business Owner' field.

    When a name is found with a truncated last-name initial (e.g. 'John S.'),
    one follow-up web_search call is made to try to resolve the full last name.
    If the search succeeds, the expanded name is returned with confidence='high'.
    If not, the partial name is returned with confidence='partial' and
    needs_review=True so the CSV assembler can flag the row.

    Returns a dict with at minimum: owner_full_name (str), confidence (str).
    confidence is 'high' on a full labeled Yelp match, 'partial' when only a
    truncated name could be confirmed, and 'none' when nothing was found.
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

    if not name:
        return {"owner_full_name": "", "confidence": "none", "phase": "yelp_profile"}

    if _TRUNCATED_NAME_RE.match(name):
        expanded = _expand_truncated_name(name, lead.business_name, city, anthropic_key)
        if expanded:
            expanded.setdefault("source_url", profile_url)
            expanded.setdefault("evidence", "Yelp Business Owner labeled field (name expanded via web search)")
            return expanded
        # Could not confirm full name — return partial with review flag.
        return {
            "owner_full_name": name,
            "confidence": "partial",
            "needs_review": True,
            "phase": "yelp_profile",
            "source_url": profile_url,
            "evidence": "Yelp Business Owner labeled field (truncated last name, review before upload)",
        }

    return {
        "owner_full_name": name,
        "confidence": "high",
        "phase": "yelp_profile",
        "source_url": profile_url,
        "evidence": "Yelp Business Owner labeled field",
    }
