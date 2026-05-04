"""Find a single business's website URL.

Two-stage strategy, cheapest-first:

  Stage 1 — pattern-guess + HEAD validation. Slugify the business name, try
  common TLDs (.com / .net / .co), HEAD-check each candidate. Free; no API
  call. Catches the long tail of contractor sites that follow the obvious
  slug-of-the-business-name pattern.

  Stage 2 — Brave Web Search (paid). Only fires if Stage 1 missed AND a
  Brave client is supplied. Filters results against a directory blocklist
  (yelp/bbb/angi/houzz/social), HEAD-validates the first survivor.

This module is NOT a source adapter (different shape than
`agents/sources/*.py`). It takes a single business name + city + state and
returns one URL or None — the router in Cycle 4 will call it per-lead and
write the URL back to the Lead object. Stays out of CampaignState entirely.
"""
from __future__ import annotations

import re
from urllib.parse import urlparse

import requests

from tools import BraveBudgetExceededError, BraveSearchClient


# Directory hosts to exclude from Stage 2 results — we want the contractor's
# OWN site, not their listing on a marketplace or social network. Suffix
# match (so "www.yelp.com" matches "yelp.com").
_DIRECTORY_DOMAINS = frozenset({
    "yelp.com", "bbb.org", "angi.com", "homeadvisor.com", "houzz.com",
    "facebook.com", "instagram.com", "linkedin.com", "mapquest.com",
    "yellowpages.com", "manta.com", "thumbtack.com", "porch.com",
    "nextdoor.com", "google.com", "maps.google.com", "twitter.com",
    "x.com", "youtube.com", "pinterest.com",
    # News and press-release hosts — Brave returns these for contractors
    # mentioned in awards/permits coverage. Not business homepages.
    "businessinsider.com", "prnewswire.com", "prweb.com",
    "globenewswire.com", "accesswire.com", "einpresswire.com",
    "newswire.com",
})


# Business-name suffixes / filler words to drop before slugifying. Lowercase
# match. "&" gets dropped as a separate punctuation step.
_BUSINESS_SUFFIX_TOKENS = frozenset({
    "llc", "inc", "incorporated", "corp", "corporation", "ltd", "limited",
    "co", "company", "the", "and", "of",
})


# Parking-page provider hosts — if the final URL after redirect lands on
# one of these we treat the candidate as not-a-real-site.
_PARKING_DOMAINS = frozenset({
    "sedoparking.com", "parkingcrew.net", "bodis.com", "above.com",
    "dan.com", "uniregistry.com", "godaddy.com", "domainmarket.com",
    "hugedomains.com", "afternic.com",
})


# A response with Content-Length below this is treated as a parked / placeholder
# page even on a 200, on the assumption that real contractor sites ship at
# least a few KB of HTML. This is a heuristic; sites without the header pass.
_MIN_REAL_CONTENT_LENGTH = 1024


def find_website(
    business_name: str,
    city: str,
    state: str,
    *,
    brave_client: BraveSearchClient | None = None,
    http_session: requests.Session | None = None,
) -> str | None:
    """Try to find `business_name`'s website. Returns a URL or None.

    Stage 1 is always attempted (free). Stage 2 fires only if `brave_client`
    is provided and Stage 1 missed; on Brave budget exhaustion or transport
    failure we degrade to None rather than crashing the calling pipeline.
    """
    session = http_session if http_session is not None else requests.Session()

    slug = _slugify(business_name)
    if not slug:
        # Non-empty business_name that slugified to empty (e.g. all tokens were
        # filler suffixes, or the name was entirely non-ASCII). Operators need
        # a signal here — otherwise this lead silently skips Stage 1 and burns
        # Brave budget with no indication why.
        if business_name:
            print(
                f"[website_finder] WARN: business_name {business_name!r} "
                "slugified to empty; skipping Stage 1 pattern-guess"
            )
    else:
        for candidate_host in _pattern_candidates(slug):
            candidate_url = f"https://{candidate_host}"
            if _head_check(candidate_url, session):
                return candidate_url

    if brave_client is None:
        return None

    try:
        results = brave_client.search_web(
            query=f'"{business_name}" {city} {state}',
            count=10,
        )
    except (
        requests.HTTPError,
        requests.Timeout,
        requests.ConnectionError,
        BraveBudgetExceededError,
    ) as e:
        status = getattr(getattr(e, "response", None), "status_code", "?")
        print(
            f"[website_finder] WARN: Brave search for {business_name!r} failed: "
            f"{type(e).__name__} status={status} {e}"
        )
        return None

    for hit in results:
        url = hit.get("url")
        if not url or _is_directory(url):
            continue
        if _head_check(url, session):
            return url

    return None


# --------------------------------------------------------------------------- #
# Helpers                                                                     #
# --------------------------------------------------------------------------- #


def _slugify(name: str) -> str:
    """Lowercase, strip business suffixes, collapse to alnum-only.

    "ABC Renovations LLC" -> "abcrenovations"
    "The Smith & Jones Co." -> "smithjones"
    """
    if not name:
        return ""
    # Replace "&" and punctuation with whitespace so suffix-token splitting
    # doesn't fuse e.g. "Smith&Jones" into one word.
    cleaned = re.sub(r"[^A-Za-z0-9\s]", " ", name).lower()
    tokens = [t for t in cleaned.split() if t and t not in _BUSINESS_SUFFIX_TOKENS]
    return "".join(tokens)


def _pattern_candidates(slug: str) -> list[str]:
    """Common TLDs in priority order — .com first because it's overwhelmingly
    the most likely match for a U.S. SMB contractor.
    """
    return [f"{slug}.com", f"{slug}.net", f"{slug}.co"]


def _head_check(url: str, http_session: requests.Session) -> bool:
    """HEAD-check `url`. True if the URL resolves to a plausibly-real page.

    Network errors are expected during the pattern-guess phase (most candidate
    domains don't exist) so they're swallowed silently. We follow redirects
    so a candidate that 301s to a real site still validates, but we then
    sanity-check the FINAL URL against the parking-domain blocklist.
    """
    try:
        resp = http_session.head(url, timeout=3, allow_redirects=True)
    except (requests.HTTPError, requests.Timeout, requests.ConnectionError):
        return False

    status = getattr(resp, "status_code", 0)
    if status not in (200, 301, 302):
        return False

    final_url = getattr(resp, "url", url) or url
    if _is_directory(final_url) or _is_parking(final_url):
        return False

    # Content-Length is optional in HEAD responses; only enforce the minimum
    # when the header is actually present so sites that omit it (common with
    # chunked transfer-encoding) aren't penalized.
    headers = getattr(resp, "headers", {}) or {}
    cl_raw = headers.get("Content-Length")
    if cl_raw is not None:
        try:
            if int(cl_raw) < _MIN_REAL_CONTENT_LENGTH:
                return False
        except (TypeError, ValueError):
            pass

    return True


def _is_directory(url: str) -> bool:
    """True when the URL's host (or any parent suffix) is in the blocklist."""
    host = _hostname(url)
    return _suffix_match(host, _DIRECTORY_DOMAINS)


def _is_parking(url: str) -> bool:
    """True when the URL's host is a known parking-page provider."""
    host = _hostname(url)
    return _suffix_match(host, _PARKING_DOMAINS)


def _hostname(url: str) -> str:
    """Best-effort hostname extraction (no scheme implied -> empty)."""
    try:
        parsed = urlparse(url)
    except ValueError:
        return ""
    host = (parsed.hostname or "").lower()
    return host


def _suffix_match(host: str, domains: frozenset[str]) -> bool:
    """True if `host` equals or ends with `.<d>` for any d in `domains`."""
    if not host:
        return False
    for d in domains:
        if host == d or host.endswith("." + d):
            return True
    return False
