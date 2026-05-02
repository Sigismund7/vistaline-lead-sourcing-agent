"""Yelp Fusion source adapter.

Pure function: takes a YelpFusionClient + sourcing parameters, returns a
list of normalized lead dicts. No CampaignState integration — that is the
sourcer router's job (Cycle 4). No LLM calls.

Two diversity knobs are layered to honor Mitigation 11 (query-pattern
diversity):
  1. A category-alias filter narrows the result space to remodeling-adjacent
     businesses (Mitigation 12 — Yelp's right answer for our niche is
     contractors,kitchen_and_bath,homeservices).
  2. A rotation of `term` values broadens the surface within those
     categories. The rotation includes a `None` entry, which exercises a
     category-only sweep — Yelp often returns broader results when no text
     term is supplied.

Yelp's Business Search response intentionally does NOT carry the business's
own website URL — only the Yelp listing page. We therefore always return
`website=""` for Yelp leads. The website_finder agent (Cycle 3) is the
component that fills this gap.
"""
from __future__ import annotations

import requests

from tools import YelpFusionClient


# Yelp uses fixed category aliases (see https://www.yelp.com/developers/
# documentation/v3/all_category_list). For kitchen remodeling the right
# combination is contractors + kitchen_and_bath + homeservices — narrow
# enough to filter pizza joints, broad enough to catch the long tail of
# small operators that file under "homeservices" rather than "contractors".
_CATEGORIES_BY_NICHE: dict[str, str] = {
    "kitchen remodelers": "contractors,kitchen_and_bath,homeservices",
    "kitchen remodeling": "contractors,kitchen_and_bath,homeservices",
    "bathroom remodelers": "contractors,kitchen_and_bath,homeservices",
    "bathroom remodeling": "contractors,kitchen_and_bath,homeservices",
}

# Term rotations. None means "category-only sweep, no text term" — included
# deliberately because Yelp's relevance model returns broader results when
# the only filter is the category alias.
_TERMS_BY_NICHE: dict[str, list[str | None]] = {
    "kitchen remodelers": [
        "kitchen remodeling",
        "kitchen renovation",
        "kitchen contractor",
        None,
    ],
    "kitchen remodeling": [
        "kitchen remodeling",
        "kitchen renovation",
        "kitchen contractor",
        None,
    ],
    "bathroom remodelers": [
        "bathroom remodeling",
        "bathroom renovation",
        "bathroom contractor",
        None,
    ],
    "bathroom remodeling": [
        "bathroom remodeling",
        "bathroom renovation",
        "bathroom contractor",
        None,
    ],
}

# Yelp's Business Search caps at 50 results per page and offset 240 — i.e.
# 5 pages max. Past that the API just returns an error or empty results.
_PAGE_SIZE = 50
_MAX_OFFSET = 240


def _categories_for(niche: str) -> str:
    """Return the comma-separated Yelp category-alias filter for a niche."""
    key = (niche or "").strip().lower()
    if key in _CATEGORIES_BY_NICHE:
        return _CATEGORIES_BY_NICHE[key]
    # Fallback: drop the niche-specific kitchen_and_bath alias but keep the
    # contractor + homeservices floor so we don't sweep up restaurants etc.
    return "contractors,homeservices"


def _terms_for(niche: str) -> list[str | None]:
    """Return the term rotation for a niche, falling back to a generic split."""
    key = (niche or "").strip().lower()
    if key in _TERMS_BY_NICHE:
        return _TERMS_BY_NICHE[key]
    return [niche, f"{niche} contractor", None]


def _normalize_business(business: dict) -> dict:
    """Map a raw Yelp business dict into our source-neutral lead shape.

    `website` is intentionally always "" — Yelp's Business Search response
    only carries the Yelp listing URL (`url`), not the business's own
    website. The website_finder agent fills this gap downstream.
    """
    location = business.get("location") or {}
    coords = business.get("coordinates") or {}
    display_address = location.get("display_address") or []
    address = ", ".join(str(part) for part in display_address if part)
    return {
        "source": "yelp_fusion",
        "source_id": str(business.get("id") or ""),
        "business_name": str(business.get("name") or ""),
        "address": address,
        "phone": str(business.get("phone") or ""),
        "website": "",
        "lat": float(coords.get("latitude") or 0.0),
        "lon": float(coords.get("longitude") or 0.0),
        "raw": business,
    }


def source_leads(
    client: YelpFusionClient,
    *,
    state: str,
    city: str,
    niche: str,
    count: int,
    radius_m: int = 25000,
) -> list[dict]:
    """Source up to `count` deduped leads for one (city, state, niche) tuple.

    Steps:
      1. Resolve niche → (category-alias filter, term rotation).
      2. For each term in the rotation, walk pages with offset 0, 50, ...
         up to Yelp's max offset (240) until count is reached.
      3. Dedupe by Yelp business id within this adapter only — cross-source
         dedup is the router's job (Cycle 4).

    Yelp accepts `location` as a free-form string ("Orlando, FL"), so unlike
    the Azure adapter there is no separate geocode step.
    """
    location = f"{city}, {state}"
    categories = _categories_for(niche)
    terms = _terms_for(niche)

    seen_ids: set[str] = set()
    out: list[dict] = []

    for term in terms:
        if len(out) >= count:
            break
        offset = 0
        while offset <= _MAX_OFFSET:
            if len(out) >= count:
                break
            try:
                raw_results: list[dict] = client.search_businesses(
                    term=term,
                    location=location,
                    categories=categories,
                    radius_m=radius_m,
                    limit=_PAGE_SIZE,
                    offset=offset,
                )
            except (requests.HTTPError, requests.Timeout, requests.ConnectionError) as e:
                # External-API errors are expected churn (throttle, transient
                # 5xx that exhausted retries, network blips). Skip this
                # (term, offset) and continue — CLAUDE.md: external failures
                # get caught + logged, our bugs crash. Anything that isn't a
                # requests-layer error is allowed to propagate.
                print(
                    f"[yelp_fusion source] WARN: term={term!r} offset={offset} "
                    f"failed: {e}"
                )
                break

            if not raw_results:
                # Empty page — stop paginating this term and rotate.
                break

            for biz in raw_results:
                biz_id = str(biz.get("id") or "")
                if not biz_id or biz_id in seen_ids:
                    continue
                seen_ids.add(biz_id)
                out.append(_normalize_business(biz))
                if len(out) >= count:
                    break

            # Short page (< _PAGE_SIZE) means Yelp has no more results for
            # this term; no point asking for the next offset.
            if len(raw_results) < _PAGE_SIZE:
                break
            offset += _PAGE_SIZE

    return out[:count]
