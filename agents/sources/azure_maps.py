"""Azure Maps source adapter.

Pure function: takes an AzureMapsClient + sourcing parameters, returns a
list of normalized lead dicts. No CampaignState integration — that is the
sourcer router's job (Cycle 4). No LLM calls.

Mitigation 11 (query-pattern diversity) is implemented by rotating through
a small per-niche keyword list rather than firing the same query repeatedly.
"""
from __future__ import annotations

from typing import Any

from tools import AzureMapsClient


# Per-niche keyword variants. The plan calls out kitchen remodeling
# explicitly; other niches fall through to a generic split. Keep the list
# short — pattern diversity, not coverage breadth, is the goal here.
_KEYWORDS_BY_NICHE: dict[str, list[str]] = {
    "kitchen remodelers": [
        "kitchen remodeling",
        "kitchen renovation",
        "kitchen contractor",
    ],
    "kitchen remodeling": [
        "kitchen remodeling",
        "kitchen renovation",
        "kitchen contractor",
    ],
    "bathroom remodelers": [
        "bathroom remodeling",
        "bathroom renovation",
        "bathroom contractor",
    ],
    "bathroom remodeling": [
        "bathroom remodeling",
        "bathroom renovation",
        "bathroom contractor",
    ],
}


def _keywords_for(niche: str) -> list[str]:
    """Return the keyword rotation for a niche, falling back to a generic split."""
    key = (niche or "").strip().lower()
    if key in _KEYWORDS_BY_NICHE:
        return _KEYWORDS_BY_NICHE[key]
    return [niche, f"{niche} contractor"]


def _normalize_poi(poi: dict) -> dict:
    """Map a raw Azure Maps POI result into our source-neutral lead shape.

    Azure's response nests business fields under `poi` and address fields
    under `address.freeformAddress`. Empty strings are preferred over None
    so downstream stages don't have to special-case both.
    """
    poi_block = poi.get("poi") or {}
    address_block = poi.get("address") or {}
    position = poi.get("position") or {}
    return {
        "source": "azure_maps",
        "source_id": str(poi.get("id") or ""),
        "business_name": str(poi_block.get("name") or ""),
        "address": str(address_block.get("freeformAddress") or ""),
        "phone": str(poi_block.get("phone") or ""),
        "website": str(poi_block.get("url") or ""),
        "lat": float(position.get("lat") or 0.0),
        "lon": float(position.get("lon") or 0.0),
        "raw": poi,
    }


def source_leads(
    client: AzureMapsClient,
    *,
    state: str,
    city: str,
    niche: str,
    count: int,
    radius_m: int = 25000,
) -> list[dict]:
    """Source up to `count` deduped leads for one (city, state, niche) tuple.

    Steps:
      1. Forward-geocode "city, state" to (lat, lon). Bail with [] on miss.
      2. Rotate niche keywords (Mitigation 11) calling search_poi until count
         unique POIs collected or all keywords exhausted.
      3. Dedupe by Azure Maps POI id within this adapter only — cross-source
         dedup is the router's job (Cycle 4).

    `category_set` is intentionally left None for now: Azure Maps category
    7320 ("Specialty Stores / Construction & Renovation") is the closest
    fit but excludes some legitimate kitchen remodelers that file under
    other categories. Free-text POI search with niche keywords is the
    safer default until smoke testing proves a category filter is worth it.
    """
    coords = client.geocode(f"{city}, {state}")
    if coords is None:
        return []
    lat, lon = coords

    keywords = _keywords_for(niche)
    seen_ids: set[str] = set()
    out: list[dict] = []

    for kw in keywords:
        if len(out) >= count:
            break
        try:
            raw_results: list[dict[str, Any]] = client.search_poi(
                query=kw,
                lat=lat,
                lon=lon,
                radius_m=radius_m,
                limit=100,
                category_set=None,
            )
        except Exception:
            # External-API errors are expected churn (throttle, transient
            # 5xx that exhausted retries). Skip the keyword and continue —
            # CLAUDE.md: external failures get caught + logged, our bugs crash.
            continue

        for poi in raw_results:
            poi_id = str(poi.get("id") or "")
            if not poi_id or poi_id in seen_ids:
                continue
            seen_ids.add(poi_id)
            out.append(_normalize_poi(poi))
            if len(out) >= count:
                break

    return out[:count]
