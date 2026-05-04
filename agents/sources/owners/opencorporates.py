"""Phase 3 — OpenCorporates business registry officer lookup.

Searches the OpenCorporates API for the company by name + state jurisdiction,
then returns the highest-priority officer (owner > president > CEO ...).
Free up to 50 lookups/day on the free tier. Returns confidence="none" on
429 rate-limit so the orchestrator falls through to Phase 4 silently.

UPGRADE REMINDER: Set OPENCORPORATES_API_KEY env var after upgrading
the plan at https://opencorporates.com/api_accounts/new
"""
from __future__ import annotations

from state import Lead
from tools import OpenCorporatesClient
from config import CONFIG


def lookup(lead: Lead, city: str, state_abbr: str, anthropic_key: str) -> dict:
    """Phase 3: OpenCorporates officer lookup for the business.

    anthropic_key is accepted to satisfy the uniform phase signature but is
    not used — this phase makes no LLM calls.

    Returns dict with: owner_full_name, confidence, source_url.
    Returns confidence="none" on 429, no results, or no matching officer.
    """
    client = OpenCorporatesClient(api_key=CONFIG.opencorporates_api_key)
    officers = client.search_company_officers(lead.business_name, state_abbr)
    if not officers:
        return {"owner_full_name": "", "confidence": "none"}

    name = client.pick_best_officer(officers)
    if not name:
        return {"owner_full_name": "", "confidence": "none"}

    return {
        "owner_full_name": name,
        "confidence": "high",
        "source_url": (
            f"https://opencorporates.com/companies/us_{state_abbr.lower()}"
            f"?q={lead.business_name.replace(' ', '+')}"
        ),
        "phase": "opencorporates",
    }
