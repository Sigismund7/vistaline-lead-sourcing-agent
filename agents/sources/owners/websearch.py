"""Open web search fallback owner lookup (Houzz, Google, review responses).

Uses Claude's web_search tool across non-BBB sources. BBB is no longer
searched here — it's owned by Phase 0 (bbb_direct + bbb_websearch). Paid:
~$0.04/lead reaching this phase. Toggleable via campaign.use_websearch.
"""
from __future__ import annotations

from anthropic import Anthropic

from state import Lead
from agents.sources.owners._utils import parse_owner_json

SYSTEM_PROMPT = """You are a research assistant finding the owner of a small remodeling-contractor business.

Use the web_search tool. Try each strategy in order — stop as soon as you find a real full name with clear ownership evidence. Do NOT search BBB.org — that source is already covered by an earlier phase, you would be duplicating work.

1. Houzz:  "{business_name}" {city} site:houzz.com
   If a Houzz pro profile appears, look for owner/founder language in the About section.

2. Google owner:  {business_name} owner {city} {state}

3. Review responses:  "{business_name}" {city} owner review
   Owner-signed review responses often say "Thanks — John Smith, Owner" or
   "John and his team appreciate your business." Check Google Maps and Yelp pages.

4. Google founder:  {business_name} {city} {state} owner OR founder

CONFIDENCE RULES:
- "high":   full first+last name with explicit title (Owner / Founder / President / Principal)
- "medium": full name found without explicit title, OR first name only with explicit title
            ("Thanks, John — Owner" or "John and his team" → medium, owner_full_name = first name only)
- "low":    name inferred without any ownership language
- "none":   nothing found — return empty

NEVER GUESS. If no name is found with at least medium confidence, return empty.

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
    client = Anthropic(api_key=anthropic_key, timeout=60.0, max_retries=10)
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
            tools=[{"type": "web_search_20250305", "name": "web_search", "max_uses": 7}],
            messages=[{"role": "user", "content": user_msg}],
        )
    except Exception as e:
        return {"owner_full_name": "", "confidence": "none", "phase": "web_search", "error": str(e)}

    text = "".join(
        b.text for b in response.content if getattr(b, "type", "") == "text"
    ).strip()
    result = parse_owner_json(text)
    result.setdefault("phase", "web_search")
    return result
