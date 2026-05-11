"""Compare-mode phase — BBB owner lookup via Claude's web_search tool.

This module is the A/B counterpart to `agents/sources/owners/bbb_direct.py`.
Both phases run on every kept lead during the compare-mode window so we can
measure whether the new BBB-direct HTTP scrape (Phase 0) actually outperforms
the existing indirect approach of letting Claude's `web_search_20250305` tool
hit BBB via Google.

Design doc: ~/.gstack/projects/Vistaline-LeadSourcingAgent/
            daschelgorgenyi-main-design-20260511-120036.md

This file is intentionally temporary. After ~3 compare-mode campaigns the
winner is locked in and the loser (this file or `bbb_direct.py`) gets deleted.
Do not build on top of it.

Scope is narrower than `websearch.py` (BBB only, no Houzz / Google fallback)
so the comparison is apples-to-apples against the BBB-direct scrape.
"""
from __future__ import annotations

from anthropic import Anthropic

from state import Lead
from agents.sources.owners._utils import parse_owner_json


SYSTEM_PROMPT = """You are a research assistant finding the owner of a small remodeling-contractor business by searching BBB.org.

Use the web_search tool. Every query MUST include `site:bbb.org` so results are restricted to BBB listings. Try strategies in order — stop as soon as you find a real full name with clear ownership evidence on a BBB listing.

1. Exact name:  "{business_name}" {city} site:bbb.org
2. Owner keyword:  {business_name} owner {city} {state} site:bbb.org
3. Principal/contacts label:  {business_name} {city} {state} site:bbb.org principal contacts

On a BBB.org listing, look for the "Principal" / "Owner" / "President" / "Business Contacts" fields. That labeled field is the strongest signal.

CONFIDENCE RULES:
- "high":   full first+last name pulled from a BBB labeled field (Principal / Owner / President / Contact)
- "medium": full name found on a BBB page without an explicit owner-title label
- "low":    name inferred from BBB without any ownership language
- "none":   nothing found on BBB — return empty

NEVER GUESS. If no name appears on a BBB.org page with at least medium confidence, return empty. Do not fall back to non-BBB sources — this phase is BBB-only by design.

Output JSON only:
{{
  "owner_full_name": "First Last",
  "source_url": "the bbb.org URL where you found the name",
  "confidence": "high" | "medium" | "low" | "none"
}}
"""


def lookup(lead: Lead, city: str, state_abbr: str, anthropic_key: str) -> dict:
    """Compare-mode phase: BBB owner lookup via Claude web_search.

    Single Anthropic call with the `web_search_20250305` tool constrained
    via prompt to `site:bbb.org`. Mirrors `agents/sources/owners/websearch.py`
    but narrower in scope (BBB only vs BBB + Houzz + Google) so it can be
    compared head-to-head against `bbb_direct.py`.

    Returns a dict with at minimum: owner_full_name (str), confidence (str),
    phase='bbb_websearch'. On any Anthropic exception returns the same shape
    with an `error` key set rather than propagating — owner research must
    not crash the pipeline.
    """
    # Anthropic SDK is not thread-safe; constructed per-call. timeout/retries
    # mirror the rate-limit fix from the rest of the owner-research path.
    client = Anthropic(api_key=anthropic_key, timeout=60.0, max_retries=10)
    user_msg = (
        f"Business: {lead.business_name}\n"
        f"City: {city}, {state_abbr}\n"
        f"Website: {lead.website or '(none)'}\n\n"
        "Find the owner's full name via BBB.org search only. Return JSON only."
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
        return {
            "owner_full_name": "",
            "confidence": "none",
            "phase": "bbb_websearch",
            "error": str(e),
        }

    text = "".join(
        b.text for b in response.content if getattr(b, "type", "") == "text"
    ).strip()
    result = parse_owner_json(text)
    result["phase"] = "bbb_websearch"
    return result
