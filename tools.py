"""Thin wrappers around external APIs.

Google Places API (New) docs:
https://developers.google.com/maps/documentation/places/web-service/text-search
"""
from __future__ import annotations
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
