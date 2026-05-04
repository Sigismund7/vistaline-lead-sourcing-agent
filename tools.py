"""Thin wrappers around external APIs.

Google Places API (New) docs:
https://developers.google.com/maps/documentation/places/web-service/text-search

Azure Maps Search APIs (Geocoding + POI Search):
https://learn.microsoft.com/en-us/rest/api/maps/search

This module is for external API clients ONLY — no business logic, no LLM
calls. The AzureMapsClient class is an intentional break from the existing
module-level-function pattern in here: it has to carry rate-limiter state
across calls (last-call timestamp), so a class is the right shape. Google
Places functions stay as plain functions because they are stateless.
"""
from __future__ import annotations

import json
import os
import pathlib
import random
import time
from datetime import datetime, timezone
from typing import Any

import requests


PLACES_TEXT_SEARCH_URL = "https://places.googleapis.com/v1/places:searchText"

# We request only the fields we need, via the X-Goog-FieldMask header. This
# matters: Google bills based on the "highest SKU" your fields require, so
# being explicit keeps cost predictable. websiteUri + nationalPhoneNumber
# fall under the Pro tier — that's the cost we're accepting in exchange for
# real contact data.
PLACES_FIELD_MASK = (
    "places.id,"
    "places.displayName,"
    "places.formattedAddress,"
    "places.nationalPhoneNumber,"
    "places.websiteUri,"
    "places.types,"
    "places.businessStatus,"
    "nextPageToken"
)


def google_places_text_search(api_key: str, query: str, page_size: int = 20,
                              page_token: str | None = None) -> dict:
    """One Text Search call. Returns the parsed JSON response.

    Pagination: pass nextPageToken back in as page_token to get more results.
    Google caps Text Search at ~60 results across 3 pages per query.
    """
    headers = {
        "Content-Type": "application/json",
        "X-Goog-Api-Key": api_key,
        "X-Goog-FieldMask": PLACES_FIELD_MASK,
    }
    body: dict = {"textQuery": query, "pageSize": page_size}
    if page_token:
        body["pageToken"] = page_token
    r = requests.post(PLACES_TEXT_SEARCH_URL, headers=headers, json=body, timeout=30)
    r.raise_for_status()
    return r.json()


def google_places_search_all(api_key: str, query: str, max_results: int = 60) -> list[dict]:
    """Pull up to max_results places for a single query, paginating."""
    out: list[dict] = []
    token: str | None = None
    while len(out) < max_results:
        data = google_places_text_search(api_key, query, page_size=20, page_token=token)
        out.extend(data.get("places", []))
        token = data.get("nextPageToken")
        if not token:
            break
    return out[:max_results]


# --------------------------------------------------------------------------- #
# Azure Maps client                                                           #
# --------------------------------------------------------------------------- #


class AzureMapsClient:
    """Rate-limited client for Azure Maps Search APIs.

    Carries token-bucket state (last-call timestamp) across calls — that is
    why this is a class, not a free function. Authentication uses the
    subscription-key query parameter (Azure Maps' shared-key style), not a
    header.

    Mitigations honored (see docs/plan-tightening-v1.md, Mitigation Stack):
    - 10: token-bucket rate limiter at `rate_limit_qps` plus random jitter.
    - 13: exponential back-off on 429/5xx with cap.

    Not thread-safe; construct a separate instance per worker thread. The
    `_last_call_ts` token-bucket state and the underlying `requests.Session`
    are unguarded — sharing across `ThreadPoolExecutor` workers would race
    the rate limiter and could corrupt the session's connection pool. Same
    rule as the Anthropic client per CLAUDE.md.
    """

    BASE_URL = "https://atlas.microsoft.com"
    GEOCODE_PATH = "/search/address/json"
    POI_SEARCH_PATH = "/search/poi/category/json"
    POI_TEXT_SEARCH_PATH = "/search/poi/json"
    API_VERSION = "1.0"

    def __init__(
        self,
        api_key: str,
        rate_limit_qps: float = 1.5,
        jitter_ms: int = 200,
        max_retries: int = 5,
        backoff_base_s: float = 1.0,
        backoff_max_s: float = 60.0,
        request_timeout_s: int = 30,
        session: requests.Session | None = None,
    ) -> None:
        if not api_key:
            raise RuntimeError(
                "AzureMapsClient requires an api_key. Set AZURE_MAPS_KEY in .env."
            )
        self._api_key = api_key
        self._rate_limit_qps = float(rate_limit_qps) if rate_limit_qps else 0.0
        self._min_interval_s = (
            1.0 / self._rate_limit_qps if self._rate_limit_qps > 0 else 0.0
        )
        self._jitter_ms = max(0, int(jitter_ms))
        self._max_retries = max(0, int(max_retries))
        self._backoff_base_s = float(backoff_base_s)
        self._backoff_max_s = float(backoff_max_s)
        self._timeout = int(request_timeout_s)
        self._session = session if session is not None else requests.Session()

        # Token-bucket state. monotonic() because it never goes backwards
        # under NTP adjustments. -inf means "no prior call yet, don't sleep."
        self._last_call_ts: float = float("-inf")

    # ------------------------------------------------------------------ #
    # Public API                                                          #
    # ------------------------------------------------------------------ #

    def geocode(self, query: str) -> tuple[float, float] | None:
        """Forward-geocode a free-text query to (lat, lon).

        Returns None when Azure returns no results, or when the top result
        is missing a position (defensive — we treat partial responses as a
        miss rather than crashing the pipeline).
        """
        params = {
            "api-version": self.API_VERSION,
            "subscription-key": self._api_key,
            "query": query,
            "limit": 1,
        }
        data = self._get_with_retries(self.BASE_URL + self.GEOCODE_PATH, params)
        results = data.get("results") or []
        if not results:
            return None
        position = results[0].get("position") or {}
        lat = position.get("lat")
        lon = position.get("lon")
        if lat is None or lon is None:
            return None
        return float(lat), float(lon)

    def search_poi(
        self,
        query: str,
        lat: float,
        lon: float,
        radius_m: int = 25000,
        limit: int = 100,
        category_set: str | None = None,
    ) -> list[dict]:
        """POI Search around (lat, lon).

        When `category_set` is given, hits the category-search endpoint;
        otherwise free-text POI search. Returns the raw `results` list so
        adapters can pull whichever fields they need.
        """
        if category_set:
            url = self.BASE_URL + self.POI_SEARCH_PATH
        else:
            url = self.BASE_URL + self.POI_TEXT_SEARCH_PATH
        params: dict[str, Any] = {
            "api-version": self.API_VERSION,
            "subscription-key": self._api_key,
            "query": query,
            "lat": lat,
            "lon": lon,
            "radius": int(radius_m),
            "limit": int(limit),
        }
        if category_set:
            params["categorySet"] = category_set
        data = self._get_with_retries(url, params)
        return list(data.get("results") or [])

    # ------------------------------------------------------------------ #
    # Internals                                                           #
    # ------------------------------------------------------------------ #

    def _respect_rate_limit(self) -> None:
        """Token-bucket pacing + jitter (Mitigation 10)."""
        if self._min_interval_s <= 0:
            return
        now = time.monotonic()
        elapsed = now - self._last_call_ts
        wait = self._min_interval_s - elapsed
        if wait > 0:
            jitter_s = (
                random.random() * (self._jitter_ms / 1000.0)
                if self._jitter_ms > 0
                else 0.0
            )
            time.sleep(wait + jitter_s)

    def _get_with_retries(self, url: str, params: dict[str, Any]) -> dict:
        """GET with exponential back-off on 429/5xx (Mitigation 13).

        Other 4xx errors raise immediately — those are bug signal, not
        throttle signal, and per CLAUDE.md our own bugs should crash so we
        see them.
        """
        last_resp: requests.Response | None = None
        for attempt in range(self._max_retries + 1):
            self._respect_rate_limit()
            # try/finally so rate-limit pacing carries forward even when the
            # request itself raises (Timeout, ConnectionError). Otherwise a
            # network blip retries with no spacing and stomps Azure.
            try:
                resp = self._session.get(url, params=params, timeout=self._timeout)
            finally:
                self._last_call_ts = time.monotonic()
            last_resp = resp

            status = resp.status_code
            if status < 400:
                return resp.json()

            retryable = status == 429 or 500 <= status < 600
            if not retryable or attempt >= self._max_retries:
                resp.raise_for_status()
                # raise_for_status should have raised; defense in depth.
                raise RuntimeError(
                    f"AzureMapsClient: unexpected non-2xx without exception "
                    f"(status={status})"
                )

            backoff = min(
                self._backoff_max_s, self._backoff_base_s * (2 ** attempt)
            )
            jitter_s = (
                random.random() * (self._jitter_ms / 1000.0)
                if self._jitter_ms > 0
                else 0.0
            )
            time.sleep(backoff + jitter_s)

        # Loop exited without returning — surface the last HTTP error.
        if last_resp is not None:
            last_resp.raise_for_status()
        raise RuntimeError("AzureMapsClient: retries exhausted with no response")


# --------------------------------------------------------------------------- #
# Yelp Fusion client                                                          #
# --------------------------------------------------------------------------- #


class YelpFusionClient:
    """Rate-limited client for the Yelp Fusion Business Search API.

    Mirrors the AzureMapsClient shape (token-bucket rate limiter, jitter,
    exponential back-off on 429/5xx) but differs in two ways:
      - Authenticates via an Authorization: Bearer <key> header rather than a
        query-string parameter.
      - Exposes a single Business Search endpoint; pagination via `offset` is
        the caller's responsibility, since adapters often want to interleave
        offset paging with category/term rotation (Mitigation 11).

    Mitigations honored (see docs/plan-tightening-v1.md, Mitigation Stack):
    - 10: token-bucket rate limiter at `rate_limit_qps` plus random jitter.
      Yelp's free tier ceiling is 5 calls/sec; we pace at 1.0 qps + 300 ms
      jitter to stay well under that and to keep daily call volume sane
      against the 5000/day cap.
    - 13: exponential back-off on 429/5xx with cap.

    Not thread-safe; construct a separate instance per worker thread. The
    `_last_call_ts` token-bucket state and the underlying `requests.Session`
    are unguarded — sharing across `ThreadPoolExecutor` workers would race
    the rate limiter and could corrupt the session's connection pool. Same
    rule as the Anthropic client per CLAUDE.md.
    """

    BASE_URL = "https://api.yelp.com/v3"
    BUSINESS_SEARCH_PATH = "/businesses/search"

    # Yelp documents these as hard ceilings on the Business Search endpoint.
    # Clamping (rather than erroring) keeps the client tolerant of callers
    # that pass through user-supplied counts without policing them.
    MAX_LIMIT = 50
    MAX_RADIUS_M = 40000

    def __init__(
        self,
        api_key: str,
        rate_limit_qps: float = 1.0,
        jitter_ms: int = 300,
        max_retries: int = 5,
        backoff_base_s: float = 1.0,
        backoff_max_s: float = 60.0,
        request_timeout_s: int = 30,
        session: requests.Session | None = None,
    ) -> None:
        if not api_key:
            raise RuntimeError(
                "YelpFusionClient requires an api_key. Set YELP_FUSION_KEY in .env."
            )
        self._api_key = api_key
        self._rate_limit_qps = float(rate_limit_qps) if rate_limit_qps else 0.0
        self._min_interval_s = (
            1.0 / self._rate_limit_qps if self._rate_limit_qps > 0 else 0.0
        )
        self._jitter_ms = max(0, int(jitter_ms))
        self._max_retries = max(0, int(max_retries))
        self._backoff_base_s = float(backoff_base_s)
        self._backoff_max_s = float(backoff_max_s)
        self._timeout = int(request_timeout_s)
        self._session = session if session is not None else requests.Session()

        # Token-bucket state. monotonic() because it never goes backwards
        # under NTP adjustments. -inf means "no prior call yet, don't sleep."
        self._last_call_ts: float = float("-inf")

    # ------------------------------------------------------------------ #
    # Public API                                                          #
    # ------------------------------------------------------------------ #

    def search_businesses(
        self,
        *,
        term: str | None = None,
        location: str,
        categories: str | None = None,
        radius_m: int = 25000,
        limit: int = 50,
        offset: int = 0,
    ) -> list[dict]:
        """Yelp Business Search. Returns the raw `businesses` list.

        `location` is a free-form string ("Orlando, FL"); Yelp geocodes it
        internally so we skip the separate geocode step Azure requires.
        `categories` is a comma-separated alias list (e.g.
        "contractors,kitchen_and_bath,homeservices"); see Mitigation 12.

        `limit` is clamped to MAX_LIMIT (50) and `radius_m` to MAX_RADIUS_M
        (40000) — Yelp's documented ceilings. Pagination beyond 50 results
        is the caller's responsibility via the `offset` argument (max 240).
        """
        params: dict[str, Any] = {
            "location": location,
            "limit": min(int(limit), self.MAX_LIMIT),
            "radius": min(int(radius_m), self.MAX_RADIUS_M),
            "offset": int(offset),
        }
        if term:
            params["term"] = term
        if categories:
            params["categories"] = categories

        data = self._get_with_retries(
            self.BASE_URL + self.BUSINESS_SEARCH_PATH, params
        )
        return list(data.get("businesses") or [])

    def get_business_details(self, *, business_id: str) -> dict:
        """Yelp Business Details for a single business ID.

        Returns the full details dict including the `photos` list (up to 3
        photo URLs on the free tier). Uses the same rate-limited, retrying
        transport as `search_businesses` — callers should treat a missing or
        empty `photos` key as "no photos available" rather than an error.
        """
        url = f"{self.BASE_URL}/businesses/{business_id}"
        # Details endpoint takes no query params beyond auth; pass empty dict
        # so _get_with_retries' signature is satisfied.
        return self._get_with_retries(url, {})

    # ------------------------------------------------------------------ #
    # Internals                                                           #
    # ------------------------------------------------------------------ #

    def _respect_rate_limit(self) -> None:
        """Token-bucket pacing + jitter (Mitigation 10)."""
        if self._min_interval_s <= 0:
            return
        now = time.monotonic()
        elapsed = now - self._last_call_ts
        wait = self._min_interval_s - elapsed
        if wait > 0:
            jitter_s = (
                random.random() * (self._jitter_ms / 1000.0)
                if self._jitter_ms > 0
                else 0.0
            )
            time.sleep(wait + jitter_s)

    def _get_with_retries(self, url: str, params: dict[str, Any]) -> dict:
        """GET with Bearer auth + exponential back-off on 429/5xx (Mitigation 13).

        Other 4xx errors raise immediately — those are bug signal, not throttle
        signal, and per CLAUDE.md our own bugs should crash so we see them.
        """
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Accept": "application/json",
        }
        last_resp: requests.Response | None = None
        for attempt in range(self._max_retries + 1):
            self._respect_rate_limit()
            # try/finally so rate-limit pacing carries forward even when the
            # request itself raises (Timeout, ConnectionError). Otherwise a
            # network blip retries with no spacing and stomps Yelp.
            try:
                resp = self._session.get(
                    url, params=params, headers=headers, timeout=self._timeout
                )
            finally:
                self._last_call_ts = time.monotonic()
            last_resp = resp

            status = resp.status_code
            if status < 400:
                return resp.json()

            retryable = status == 429 or 500 <= status < 600
            if not retryable or attempt >= self._max_retries:
                resp.raise_for_status()
                raise RuntimeError(
                    f"YelpFusionClient: unexpected non-2xx without exception "
                    f"(status={status})"
                )

            backoff = min(
                self._backoff_max_s, self._backoff_base_s * (2 ** attempt)
            )
            jitter_s = (
                random.random() * (self._jitter_ms / 1000.0)
                if self._jitter_ms > 0
                else 0.0
            )
            time.sleep(backoff + jitter_s)

        if last_resp is not None:
            last_resp.raise_for_status()
        raise RuntimeError("YelpFusionClient: retries exhausted with no response")


# --------------------------------------------------------------------------- #
# Brave Search client                                                         #
# --------------------------------------------------------------------------- #


class BraveBudgetExceededError(RuntimeError):
    """Raised when the Brave search monthly query budget would be exceeded."""


class BraveSearchClient:
    """Rate-limited client for the Brave Web Search API.

    Mirrors the AzureMapsClient/YelpFusionClient shape (token-bucket rate
    limiter, jitter, exponential back-off on 429/5xx) with two Brave-specific
    differences:
      - Authenticates via an `X-Subscription-Token: <key>` header (NOT Bearer,
        NOT a query-string parameter).
      - Adds a per-month query *budget guard*. Before each call the client
        reads a counter file at `budget_state_path`; if the next call would
        push it past `max_monthly_queries` the call is aborted with a
        `BraveBudgetExceededError` BEFORE the HTTP request fires. This is the
        operator-side defense-in-depth complement to the dashboard cap (see
        docs/plan-tightening-v1.md). Counter file is one-per-month
        (`state/brave_budget_<YYYY-MM>.json`); a new month begins fresh.

    Mitigations honored (see docs/plan-tightening-v1.md, Mitigation Stack):
    - 10: token-bucket rate limiter at `rate_limit_qps` plus random jitter.
      Brave's free tier ceiling is 1 query/sec; we pace at 1.0 qps + 200 ms
      jitter to stay under that.
    - 13: exponential back-off on 429/5xx with cap.

    Not thread-safe; construct one per worker. The budget guard has
    at-most-once-fail-loose semantics: a single-process crash between the
    counter read and the atomic write may lose at most one increment,
    granting one extra call past cap. Multiple processes sharing the same
    `budget_state_path` will additionally race on the read-modify-write
    cycle and may both believe they are under budget on the boundary call.
    Both are acceptable for the single-operator workflow per CLAUDE.md.
    The same thread-safety caveat applies to the rate limiter and the
    underlying `requests.Session`. Same rule as the Anthropic client per
    CLAUDE.md.
    """

    BASE_URL = "https://api.search.brave.com/res/v1"
    WEB_SEARCH_PATH = "/web/search"
    MAX_COUNT = 20

    def __init__(
        self,
        api_key: str,
        rate_limit_qps: float = 1.0,
        jitter_ms: int = 200,
        max_retries: int = 5,
        backoff_base_s: float = 1.0,
        backoff_max_s: float = 60.0,
        request_timeout_s: int = 30,
        max_monthly_queries: int = 2000,
        budget_state_path: pathlib.Path | None = None,
        session: requests.Session | None = None,
    ) -> None:
        if not api_key:
            raise RuntimeError(
                "BraveSearchClient requires an api_key. Set BRAVE_SEARCH_KEY in .env."
            )
        self._api_key = api_key
        self._rate_limit_qps = float(rate_limit_qps) if rate_limit_qps else 0.0
        self._min_interval_s = (
            1.0 / self._rate_limit_qps if self._rate_limit_qps > 0 else 0.0
        )
        self._jitter_ms = max(0, int(jitter_ms))
        self._max_retries = max(0, int(max_retries))
        self._backoff_base_s = float(backoff_base_s)
        self._backoff_max_s = float(backoff_max_s)
        self._timeout = int(request_timeout_s)
        self._session = session if session is not None else requests.Session()

        self._max_monthly_queries = int(max_monthly_queries)
        if budget_state_path is None:
            # Default file path includes the current UTC month — month rollover
            # naturally produces a fresh counter file the next time the client
            # is constructed.
            month = datetime.now(timezone.utc).strftime("%Y-%m")
            budget_state_path = pathlib.Path("state") / f"brave_budget_{month}.json"
        self._budget_state_path = pathlib.Path(budget_state_path)

        # Token-bucket state. monotonic() because it never goes backwards
        # under NTP adjustments. -inf means "no prior call yet, don't sleep."
        self._last_call_ts: float = float("-inf")

    # ------------------------------------------------------------------ #
    # Public API                                                          #
    # ------------------------------------------------------------------ #

    def search_web(
        self,
        *,
        query: str,
        count: int = 10,
        country: str = "US",
    ) -> list[dict]:
        """Brave Web Search. Returns the raw `web.results` list.

        `count` is clamped to MAX_COUNT (20) — Brave's documented per-request
        ceiling. The full response wraps results under `web.results`; missing
        keys yield an empty list rather than raising, so a callers iterating
        results don't have to special-case it.

        Budget guard: increments and persists the per-month counter BEFORE
        the HTTP call. When the next increment would exceed
        `max_monthly_queries`, raises `BraveBudgetExceededError` and the
        request is not sent.
        """
        # Reserve a budget slot first; if we're over the cap, we want to
        # abort BEFORE the rate limiter sleep and BEFORE the HTTP call.
        self._reserve_budget_slot()

        params: dict[str, Any] = {
            "q": query,
            "count": min(int(count), self.MAX_COUNT),
            "country": country,
            "safesearch": "moderate",
        }
        data = self._get_with_retries(
            self.BASE_URL + self.WEB_SEARCH_PATH, params
        )
        return list(data.get("web", {}).get("results") or [])

    # ------------------------------------------------------------------ #
    # Internals                                                           #
    # ------------------------------------------------------------------ #

    def _reserve_budget_slot(self) -> None:
        """Read counter, raise if next call would exceed cap, otherwise
        increment and atomically persist.

        Atomicity: write to a sibling temp file in the same directory then
        os.replace() onto the target. os.replace() is atomic on POSIX and on
        Windows for files on the same volume, so a crash mid-write leaves the
        previous good counter file intact rather than producing a half-written
        JSON.
        """
        path = self._budget_state_path
        path.parent.mkdir(parents=True, exist_ok=True)

        current_month = datetime.now(timezone.utc).strftime("%Y-%m")
        count = 0
        if path.exists():
            try:
                data = json.loads(path.read_text())
                # If the on-disk month doesn't match (e.g. someone reused an
                # explicit path across months) start fresh — the cap is a
                # *monthly* budget, not a perpetual one.
                if data.get("month") == current_month:
                    count = int(data.get("count", 0))
            except (json.JSONDecodeError, ValueError, OSError):
                # Corrupt counter file: treat as zero rather than crashing the
                # pipeline. The next successful write will heal it.
                count = 0

        if count + 1 > self._max_monthly_queries:
            raise BraveBudgetExceededError(
                f"Brave monthly query budget exceeded for {current_month}: "
                f"{count} of {self._max_monthly_queries} used; "
                f"next call would be #{count + 1}."
            )

        new_count = count + 1
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(json.dumps({"month": current_month, "count": new_count}))
        os.replace(tmp, path)

    def _respect_rate_limit(self) -> None:
        """Token-bucket pacing + jitter (Mitigation 10)."""
        if self._min_interval_s <= 0:
            return
        now = time.monotonic()
        elapsed = now - self._last_call_ts
        wait = self._min_interval_s - elapsed
        if wait > 0:
            jitter_s = (
                random.random() * (self._jitter_ms / 1000.0)
                if self._jitter_ms > 0
                else 0.0
            )
            time.sleep(wait + jitter_s)

    def _get_with_retries(self, url: str, params: dict[str, Any]) -> dict:
        """GET with X-Subscription-Token auth + exp back-off on 429/5xx (Mit. 13).

        Other 4xx errors raise immediately — those are bug signal, not throttle
        signal, and per CLAUDE.md our own bugs should crash so we see them.
        """
        headers = {
            "X-Subscription-Token": self._api_key,
            "Accept": "application/json",
        }
        last_resp: requests.Response | None = None
        for attempt in range(self._max_retries + 1):
            self._respect_rate_limit()
            # try/finally so rate-limit pacing carries forward even when the
            # request itself raises (Timeout, ConnectionError). Otherwise a
            # network blip retries with no spacing and stomps Brave.
            try:
                resp = self._session.get(
                    url, params=params, headers=headers, timeout=self._timeout
                )
            finally:
                self._last_call_ts = time.monotonic()
            last_resp = resp

            status = resp.status_code
            if status < 400:
                return resp.json()

            retryable = status == 429 or 500 <= status < 600
            if not retryable or attempt >= self._max_retries:
                resp.raise_for_status()
                raise RuntimeError(
                    f"BraveSearchClient: unexpected non-2xx without exception "
                    f"(status={status})"
                )

            backoff = min(
                self._backoff_max_s, self._backoff_base_s * (2 ** attempt)
            )
            jitter_s = (
                random.random() * (self._jitter_ms / 1000.0)
                if self._jitter_ms > 0
                else 0.0
            )
            time.sleep(backoff + jitter_s)

        if last_resp is not None:
            last_resp.raise_for_status()
        raise RuntimeError("BraveSearchClient: retries exhausted with no response")


# --------------------------------------------------------------------------- #
# Houzz scraper client                                                        #
# --------------------------------------------------------------------------- #


class HouzzClient:
    """Minimal HTTP scraper for Houzz professional search + profile pages.

    Not rate-limited beyond the implicit throttle of MAX_PARALLEL=10 leads
    running concurrently (each lead makes at most 2 requests). Cloudflare
    protection on Houzz means a 403 or JS-challenge page is possible — both
    are treated as a miss and the caller falls through to the next phase.

    Not thread-safe; construct one per worker thread (CLAUDE.md rule).
    """

    SEARCH_URL = "https://www.houzz.com/professionals/search"
    USER_AGENT = (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    )

    def __init__(self, timeout_s: int = 15) -> None:
        self._timeout = timeout_s
        self._session = requests.Session()
        self._session.headers.update({
            "User-Agent": self.USER_AGENT,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
            "Accept-Encoding": "gzip, deflate, br",
        })

    def search(self, business_name: str) -> list[dict]:
        """Search Houzz for a business name.

        Returns a list of dicts with keys: name, location, profile_url.
        Returns [] on any HTTP error or Cloudflare block.
        """
        try:
            resp = self._session.get(
                self.SEARCH_URL,
                params={"q": business_name},
                timeout=self._timeout,
                allow_redirects=True,
            )
        except requests.RequestException:
            return []
        if resp.status_code != 200:
            return []
        return self._parse_search_results(resp.text)

    def get_profile_text(self, profile_url: str) -> str:
        """Fetch a Houzz profile page and return About-section text (max 4000 chars).

        Returns "" on any error or Cloudflare block.
        """
        try:
            resp = self._session.get(profile_url, timeout=self._timeout, allow_redirects=True)
        except requests.RequestException:
            return ""
        if resp.status_code != 200:
            return ""
        return self._parse_profile_text(resp.text)

    def _parse_search_results(self, html: str) -> list[dict]:
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(html, "html.parser")
        results: list[dict] = []
        cards = (
            soup.select("[data-component='ProCard']")
            or soup.select(".hz-pro-search-result")
            or soup.select("li.search-results__item")
        )
        for card in cards:
            name_el = (
                card.select_one("[data-component='ProName']")
                or card.select_one(".hz-pro-search-result__title")
                or card.select_one("h2")
            )
            loc_el = (
                card.select_one("[data-component='ProLocation']")
                or card.select_one(".hz-pro-search-result__location")
                or card.select_one(".pro-location")
            )
            link_el = card.select_one("a[href]")
            if not name_el or not link_el:
                continue
            href = link_el["href"]
            results.append({
                "name": name_el.get_text(strip=True),
                "location": loc_el.get_text(strip=True) if loc_el else "",
                "profile_url": href if href.startswith("http") else f"https://www.houzz.com{href}",
            })
        return results

    def _parse_profile_text(self, html: str) -> str:
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(html, "html.parser")
        about = (
            soup.select_one("[data-component='AboutSection']")
            or soup.select_one(".hz-pro-profile__about")
            or soup.select_one("#about")
            or soup.select_one(".pro-description")
        )
        if about:
            return about.get_text(separator=" ", strip=True)[:4000]
        return " ".join(p.get_text(strip=True) for p in soup.find_all("p"))[:4000]


# --------------------------------------------------------------------------- #
# OpenCorporates client                                                       #
# --------------------------------------------------------------------------- #


class OpenCorporatesClient:
    """Client for the OpenCorporates v0.4 companies API.

    Used by Phase 3 of owner_researcher to look up LLC/Corp officer names.
    Handles 429 rate-limit gracefully (returns []) so the caller can fall
    through to the next phase.

    Free tier: 50 lookups/day unauthenticated (or with free API key).
    Paid tier ($0.50/1000): set OPENCORPORATES_API_KEY. See spec alert.

    Not thread-safe; construct one per worker thread (CLAUDE.md rule).
    """

    BASE_URL = "https://api.opencorporates.com/v0.4"

    ROLE_PRIORITY = ["owner", "president", "ceo", "principal", "founder", "manager", "director"]

    def __init__(self, api_key: str = "", timeout_s: int = 15) -> None:
        self._api_key = api_key
        self._timeout = timeout_s
        self._session = requests.Session()

    def search_company_officers(
        self, business_name: str, state_abbr: str
    ) -> list[dict]:
        """Search for a company and return its current officers.

        Returns a list of dicts with keys: name (str), role (str), is_current (bool).
        Returns [] on 429, network error, no results, or parse failure.
        """
        params: dict[str, Any] = {
            "q": business_name,
            "jurisdiction_code": f"us_{state_abbr.lower()}",
            "include_officers": "true",
        }
        if self._api_key:
            params["api_token"] = self._api_key

        try:
            resp = self._session.get(
                f"{self.BASE_URL}/companies/search",
                params=params,
                timeout=self._timeout,
            )
        except requests.RequestException:
            return []

        if resp.status_code == 429:
            return []
        if not resp.ok:
            return []

        try:
            data = resp.json()
        except ValueError:
            return []

        companies = data.get("results", {}).get("companies") or []
        if not companies:
            return []

        company = companies[0].get("company", {})
        officers_raw = company.get("officers") or []
        return [
            {
                "name": o.get("officer", {}).get("name", ""),
                "role": (
                    o.get("officer", {}).get("position")
                    or o.get("officer", {}).get("title")
                    or ""
                ).lower(),
                "is_current": o.get("officer", {}).get("end_date") is None,
            }
            for o in officers_raw
            if o.get("officer", {}).get("name")
        ]

    def pick_best_officer(self, officers: list[dict]) -> str | None:
        """Return the name of the highest-priority current officer, or None.

        Priority: owner > president > ceo > principal > founder > manager > director.
        Falls back to any current officer if no priority role matches.
        """
        if not officers:
            return None
        current = [o for o in officers if o.get("is_current", True)] or officers
        for role_keyword in self.ROLE_PRIORITY:
            for o in current:
                if role_keyword in o.get("role", "").lower():
                    return o["name"] or None
        return current[0]["name"] or None
