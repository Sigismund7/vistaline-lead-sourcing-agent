"""Phase 0 — BBB.org direct-scrape owner lookup.

Two-step flow that replaces what previously fell to a Claude web_search call:

1. Free HTTP GET to https://www.bbb.org/search resolves candidate profile
   URLs for a (business_name, city, state) tuple. The search page is
   server-rendered HTML and not Cloudflare-protected. We fuzzy-match each
   `<a href*="/profile/">` anchor's normalized text against the lead's
   business name and pick the highest-scoring candidate above
   `_FUZZY_THRESHOLD`.

2. Fetch the resolved profile page through ScraperAPI's premium proxy
   (~10 credits / ~$0.005) because the profile path is 403-blocked by
   Cloudflare to direct HTTP.

Owner extraction prefers schema.org JSON-LD (a `Person` employee entry
with a `jobTitle` matching `_ROLE_PRIORITY`) and falls back to the
"Business Management" `<dl>` block in the rendered DOM.

Failure-mode contract: every external failure (no ScraperAPI key, no
search results, fuzzy match below threshold, Cloudflare block, missing
owner fields) returns a confidence='none' dict so the owner_researcher
falls through silently to the next phase. Only our own bugs raise.

Roughly 8x cheaper than the Claude web_search Phase 3 it replaces, at
comparable hit rate for SMB-contractor leads where the business is
BBB-listed.
"""
from __future__ import annotations

import json
import random
import re
import threading
import time

import requests
from bs4 import BeautifulSoup
from rapidfuzz import fuzz

from state import Lead
from agents.sources.owners._utils import (
    TRUNCATED_NAME_RE,
    build_scraperapi_client,
    expand_truncated_name,
)


_BBB_SEARCH_URL = "https://www.bbb.org/search"
_BBB_BASE = "https://www.bbb.org"
_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)
# BBB anchor text strips intraword spaces ("JacksonConstruction") so
# token_sort_ratio against the original business name is noisier than
# Yelp's case. 80 is empirically the lowest that still rejects clearly
# unrelated matches like "Lee Jackson Construction" when the target is
# "Jackson Construction".
_FUZZY_THRESHOLD = 80
_ROLE_PRIORITY = (
    "Owner",
    "President",
    "Founder",
    "Principal",
    "Manager",
    "License Holder",
)
_HONORIFICS_RE = re.compile(r"^(Mr\.|Mrs\.|Ms\.|Dr\.|Mx\.)\s+", re.IGNORECASE)
_NAME_SUFFIX_RE = re.compile(
    r",\s*(LLC|Inc\.?|Ltd\.?|Co\.?|Corp\.?|Company|DBA\s+.+)$",
    re.IGNORECASE,
)
_CAMELCASE_SPLIT_RE = re.compile(r"([a-z])([A-Z])")


# Module-level pacing state for the BBB search step. The owner_researcher
# runs MAX_PARALLEL workers, each importing this module fresh from the
# same process — module globals are shared across threads. The lock is
# held only for the few-microsecond timestamp arithmetic; the actual
# `time.sleep` happens after release so we never block other threads on
# IO-bound waits.
_search_pace_lock = threading.Lock()
_search_last_call: float = 0.0  # monotonic seconds


def _pace_search() -> None:
    """Throttle BBB search calls to ~1 qps with 200ms jitter.

    Thread-safe across owner_researcher workers via a module-level lock.
    """
    global _search_last_call
    with _search_pace_lock:
        now = time.monotonic()
        elapsed = now - _search_last_call
        wait = max(0.0, 1.0 - elapsed)
        _search_last_call = now + wait
    if wait > 0:
        time.sleep(wait + random.random() * 0.2)


def _normalize_candidate_name(text: str) -> str:
    """Clean a BBB search anchor's inner text for fuzzy matching.

    Three operations, in order:
      1. CamelCase split: BBB strips intraword spaces in anchor text, so
         "JacksonConstruction" becomes "Jackson Construction".
      2. Strip legal-entity suffixes (", LLC", ", Inc.", "DBA <text>") that
         appear inconsistently between the anchor and the lead's business
         name, dragging down token_sort_ratio.
      3. Collapse whitespace.
    """
    spaced = _CAMELCASE_SPLIT_RE.sub(r"\1 \2", text)
    stripped = _NAME_SUFFIX_RE.sub("", spaced)
    return " ".join(stripped.split()).strip()


def _search_bbb(
    business_name: str,
    city: str,
    state_abbr: str,
) -> list[tuple[str, str]]:
    """Return a list of (normalized_name, profile_href) candidates from BBB search.

    Silent fallthrough — any non-200 response or network error returns
    `[]` so the caller falls to the next phase. Dedupes by href (BBB
    sometimes repeats the same profile with an `/addressId/...` suffix).
    """
    _pace_search()
    try:
        resp = requests.get(
            _BBB_SEARCH_URL,
            params={
                "find_country": "USA",
                "find_text": business_name,
                "find_loc": f"{city}, {state_abbr}",
            },
            headers={"User-Agent": _USER_AGENT},
            timeout=15,
        )
    except Exception:
        return []

    if resp.status_code != 200:
        return []

    soup = BeautifulSoup(resp.text, "html.parser")
    seen: set[str] = set()
    candidates: list[tuple[str, str]] = []
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if "/profile/" not in href:
            continue
        if href in seen:
            continue
        seen.add(href)
        raw = a.get_text(strip=True)
        if not raw:
            continue
        candidates.append((_normalize_candidate_name(raw), href))
    return candidates


def _fuzzy_match_best(
    candidates: list[tuple[str, str]],
    business_name: str,
) -> str | None:
    """Return the highest-scoring profile href above `_FUZZY_THRESHOLD`, or None."""
    target = business_name.lower()
    best_href: str | None = None
    best_score = 0
    for name, href in candidates:
        score = fuzz.token_sort_ratio(target, name.lower())
        # Strictly greater preserves first-wins tiebreak ordering.
        if score > best_score:
            best_score = score
            best_href = href
    if best_score >= _FUZZY_THRESHOLD and best_href:
        return best_href
    return None


def _fetch_bbb_profile(href: str) -> str | None:
    """Fetch a BBB profile page through ScraperAPI's premium proxy.

    Returns None when SCRAPERAPI_KEY is unset, the monthly budget is
    exhausted, or ScraperAPI itself errors — all silent-fallthrough cases.
    """
    client = build_scraperapi_client()
    if client is None:
        return None
    return client.fetch_html(f"{_BBB_BASE}{href}", premium=True, render=False)


def _role_priority_index(job_title: str) -> int | None:
    """Return position of `job_title` in `_ROLE_PRIORITY`, case-insensitive."""
    lowered = job_title.strip().lower()
    for i, role in enumerate(_ROLE_PRIORITY):
        if role.lower() == lowered:
            return i
    return None


def _walk_for_persons(node: object, out: list[dict]) -> None:
    """Recursively collect dicts with @type == 'Person' from arbitrary JSON."""
    if isinstance(node, dict):
        if node.get("@type") == "Person":
            out.append(node)
        for v in node.values():
            _walk_for_persons(v, out)
    elif isinstance(node, list):
        for v in node:
            _walk_for_persons(v, out)


def _parse_owner_from_jsonld(html: str) -> str | None:
    """Extract the highest-priority Person+jobTitle owner from JSON-LD blocks.

    BBB profiles ship a `LocalBusiness` schema.org block whose `employee`
    array contains Person entries with `jobTitle` ("Owner", "License
    Holder", etc.). When multiple owner-ish roles are present, we pick
    the one earliest in `_ROLE_PRIORITY` (Owner beats License Holder).
    """
    soup = BeautifulSoup(html, "html.parser")
    persons: list[dict] = []
    for script in soup.find_all("script", attrs={"type": "application/ld+json"}):
        raw = script.string or script.get_text() or ""
        try:
            data = json.loads(raw)
        except (json.JSONDecodeError, ValueError):
            continue
        _walk_for_persons(data, persons)

    best_idx: int | None = None
    best_person: dict | None = None
    for person in persons:
        job = person.get("jobTitle") or ""
        idx = _role_priority_index(job)
        if idx is None:
            continue
        if best_idx is None or idx < best_idx:
            best_idx = idx
            best_person = person

    if best_person is None:
        return None

    given = (best_person.get("givenName") or "").strip()
    family = (best_person.get("familyName") or "").strip()
    if not given or not family:
        return None
    return " ".join(f"{given} {family}".split())


def _parse_owner_from_html(html: str) -> str | None:
    """DOM fallback: parse the Business Management `<dl>` block.

    Used when JSON-LD is missing or malformed. Looks for `<dt>` labels
    "Business Management" / "Principal Contacts" / "Customer Contacts",
    then for each `<dd>` sibling parses "Honorific Name, Role" and picks
    the role with the highest `_ROLE_PRIORITY` position.
    """
    soup = BeautifulSoup(html, "html.parser")
    # Strip non-rendered containers so we don't catch script-template DOM.
    for tag in soup(["script", "style", "template", "noscript"]):
        tag.decompose()

    target_labels = {"Business Management", "Principal Contacts", "Customer Contacts"}
    candidates: list[tuple[int, str]] = []  # (priority_index, name)

    for dt in soup.find_all("dt"):
        if dt.get_text(strip=True) not in target_labels:
            continue
        sib = dt.find_next_sibling()
        while sib is not None and sib.name == "dd":
            text = sib.get_text(" ", strip=True)
            if "," in text:
                # Split on the LAST comma — names can themselves contain commas
                # in pathological cases, but role is always the trailing token.
                name_part, role_part = text.rsplit(",", 1)
                name = _HONORIFICS_RE.sub("", name_part).strip()
                role = role_part.strip()
                idx = _role_priority_index(role)
                if idx is not None and name:
                    candidates.append((idx, name))
            sib = sib.find_next_sibling()

    if not candidates:
        return None

    candidates.sort(key=lambda c: c[0])
    return candidates[0][1]


def lookup(lead: Lead, city: str, state_abbr: str, anthropic_key: str) -> dict:
    """Phase 0: search BBB.org and scrape the matching profile for the owner.

    Returns a dict with at minimum `owner_full_name`, `confidence`, and
    `phase='bbb_direct'`. Confidence is 'high' on a clean BBB profile
    match, 'partial' when only a truncated last-name initial could be
    confirmed, and 'none' for any failure (no search hit, no fuzzy match,
    no ScraperAPI key/budget, Cloudflare block, missing owner fields).
    """
    candidates = _search_bbb(lead.business_name, city, state_abbr)
    if not candidates:
        return {"owner_full_name": "", "confidence": "none", "phase": "bbb_direct"}

    href = _fuzzy_match_best(candidates, lead.business_name)
    if not href:
        return {"owner_full_name": "", "confidence": "none", "phase": "bbb_direct"}

    html = _fetch_bbb_profile(href)
    if not html:
        return {"owner_full_name": "", "confidence": "none", "phase": "bbb_direct"}

    profile_url = f"{_BBB_BASE}{href}"

    name = _parse_owner_from_jsonld(html)
    evidence = "BBB profile (JSON-LD)"
    if not name:
        name = _parse_owner_from_html(html)
        evidence = "BBB profile (Business Management DOM)"

    if not name:
        return {"owner_full_name": "", "confidence": "none", "phase": "bbb_direct"}

    if TRUNCATED_NAME_RE.match(name):
        expanded = expand_truncated_name(
            name, lead.business_name, city, anthropic_key, phase="bbb_direct"
        )
        if expanded:
            expanded.setdefault("source_url", profile_url)
            expanded.setdefault(
                "evidence", "BBB profile (name expanded via web search)"
            )
            return expanded
        return {
            "owner_full_name": name,
            "confidence": "partial",
            "needs_review": True,
            "phase": "bbb_direct",
            "source_url": profile_url,
            "evidence": "BBB profile (truncated last name, review before upload)",
        }

    return {
        "owner_full_name": name,
        "confidence": "high",
        "phase": "bbb_direct",
        "source_url": profile_url,
        "evidence": evidence,
    }
