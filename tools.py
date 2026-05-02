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

import random
import time
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
            resp = self._session.get(url, params=params, timeout=self._timeout)
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
