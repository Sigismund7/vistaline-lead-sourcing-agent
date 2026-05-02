"""Sourcer — fetches contractor listings from Google Places API.

Runs multiple search queries (more keyword variations = better coverage,
since each Text Search query caps at ~60 results), deduplicates by place_id,
and stops once the target_count is reached.
"""
from __future__ import annotations

from state import CampaignState, Lead
from tools import google_places_search_all


# Niche-specific search keywords. The SOP recommends 5 keywords per niche to
# squeeze out coverage Google would otherwise miss. Each keyword is one Text
# Search query and returns up to 60 places, deduped across queries.
KEYWORDS_BY_NICHE = {
    "bathroom remodeling": [
        "bathroom remodeling",
        "master bathroom remodel",
        "bathroom renovation",
        "kitchen and bath remodeling",
        "home remodeling contractor",
    ],
    "kitchen remodeling": [
        "kitchen remodeling",
        "kitchen renovation",
        "kitchen and bath remodeling",
        "custom kitchen contractor",
        "home remodeling contractor",
    ],
}


def _normalize_domain(website: str) -> str:
    """Strip protocol + www, return bare domain. https://www.foo.com/x -> foo.com"""
    if not website:
        return ""
    w = website.strip().lower()
    for prefix in ("https://", "http://"):
        if w.startswith(prefix):
            w = w[len(prefix):]
    if w.startswith("www."):
        w = w[4:]
    return w.split("/")[0].split("?")[0]


def _area_code(phone: str) -> str:
    digits = "".join(c for c in (phone or "") if c.isdigit())
    if len(digits) == 11 and digits.startswith("1"):
        digits = digits[1:]
    return digits[:3] if len(digits) >= 10 else ""


def _keywords_for(niche: str) -> list[str]:
    return KEYWORDS_BY_NICHE.get(niche.lower(), [niche, f"{niche} contractor"])


def run(state: CampaignState, places_key: str) -> None:
    if state.is_done("sourcer"):
        state.info("sourcer", f"already complete, skipping ({len(state.leads)} leads)")
        return

    keywords = _keywords_for(state.niche)
    state.info("sourcer", f"sourcing up to {state.target_count} leads",
               keywords=keywords, location=f"{state.city}, {state.state_abbr}")

    seen_place_ids: set[str] = set()

    for kw in keywords:
        if len(state.leads) >= state.target_count:
            break

        query = f"{kw} in {state.city}, {state.state_abbr}"
        state.info("sourcer", f"query: {query!r}")
        try:
            places = google_places_search_all(places_key, query, max_results=60)
        except Exception as e:
            state.info("sourcer", f"WARN: query failed", query=query, error=str(e))
            continue

        new_in_this_query = 0
        for place in places:
            place_id = place.get("id", "")
            if not place_id or place_id in seen_place_ids:
                continue
            if place.get("businessStatus") and place["businessStatus"] != "OPERATIONAL":
                continue
            seen_place_ids.add(place_id)

            display_name = place.get("displayName", {})
            business_name = (display_name or {}).get("text", "") if isinstance(display_name, dict) else str(display_name)
            phone = place.get("nationalPhoneNumber", "")
            website = place.get("websiteUri", "")

            lead = Lead(
                business_name=business_name,
                phone=phone,
                website=website,
                address=place.get("formattedAddress", ""),
                area_code=_area_code(phone),
                domain=_normalize_domain(website),
                place_id=place_id,
            )
            state.leads.append(lead)
            new_in_this_query += 1
            if len(state.leads) >= state.target_count:
                break

        state.info("sourcer", f"  added {new_in_this_query} new leads (total: {len(state.leads)})")

    state.info("sourcer", f"done — {len(state.leads)} unique leads collected")
    state.mark_done("sourcer")
