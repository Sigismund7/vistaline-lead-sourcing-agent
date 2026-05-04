"""Phase 4 — BBB + Google web search fallback owner lookup.

Uses Claude's web_search tool to search BBB.org, then Google "owner",
then Google "founder". Paid: ~$0.04/lead reaching this phase.
Toggleable via campaign.use_websearch.
"""
from __future__ import annotations

from anthropic import Anthropic

from state import Lead
from agents.sources.owners._utils import parse_owner_json

SYSTEM_PROMPT = """You are a research assistant finding the owner of a small remodeling-contractor business.

Use the web_search tool. Strategy in this order, stop when you find a real name:
1. Search:  "{business_name}" {city} BBB
   If a BBB.org result appears, look for "Principal" / "Owner" / "President".
2. Search:  {business_name} owner {city}
3. Search:  {business_name} {city} {state} owner OR founder

NEVER GUESS. If no name is found, return empty.

Output JSON only:
{{
  "owner_full_name": "First Last",
  "source_url": "the URL where you found the name",
  "confidence": "high" | "medium" | "low" | "none"
}}
"""


def lookup(lead: Lead, city: str, state_abbr: str, anthropic_key: str) -> dict:
    """Phase 4: BBB + Google web search via Claude's web_search tool.

    Returns a dict with at minimum: owner_full_name (str), confidence (str).
    """
    client = Anthropic(api_key=anthropic_key, timeout=60.0)
    user_msg = (
        f"Business: {lead.business_name}\n"
        f"City: {city}, {state_abbr}\n"
        f"Website: {lead.website or '(none)'}\n\n"
        "Find the owner's full name via BBB or Google search. Return JSON only."
    )

    try:
        response = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=2000,
            system=SYSTEM_PROMPT.format(
                business_name=lead.business_name, city=city, state=state_abbr,
            ),
            tools=[{"type": "web_search_20250305", "name": "web_search", "max_uses": 4}],
            messages=[{"role": "user", "content": user_msg}],
        )
    except Exception as e:
        return {"owner_full_name": "", "confidence": "none", "error": str(e)}

    text = "".join(
        b.text for b in response.content if getattr(b, "type", "") == "text"
    ).strip()
    result = parse_owner_json(text)
    result.setdefault("phase", "web_search")
    return result
