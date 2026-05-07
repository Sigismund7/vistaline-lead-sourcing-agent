"""Owner Researcher — finds the owner's full name for every kept lead.

Four-phase strategy per lead, phases run sequentially and short-circuit on
the first high/medium-confidence result. Phases 2 and 3 are independently
toggleable from the campaign row (use_registry, use_websearch).
Phases 1 and 4 (yelp_profile and website crawl) always run.

  Phase 0: yelp_profile.lookup   — Yelp Business Owner labeled field. Free.
  Phase 1: website.lookup        — crawl own website, ask Claude. Free.
  Phase 2: opencorporates.lookup — OpenCorporates officer API. Free tier.
  Phase 3: websearch.lookup      — BBB + Houzz + Google + review responses
                                   via Claude web_search. ~$0.05/lead.

Hit rate expectation (all phases on):
  Phase 0 alone:          ~10-15%
  + Phase 1 (website):    ~55%
  + Phase 2 (OC):         ~65%
  + Phase 3 (web search): ~85-90%

Never guesses. If all phases fail, owner fields stay blank.
"""
from __future__ import annotations
import concurrent.futures as futures
from typing import Callable

from state import CampaignState, Lead
from agents.sources.owners import yelp_profile, website, opencorporates, websearch
from agents.sources.owners._utils import split_name


MAX_PARALLEL = 4  # Each worker can fire 2-3 Sonnet calls per lead (Phase 1
# website crawl + Phase 3 web_search). At 8 workers we burst past the org's
# 30k input-tokens-per-minute cap; 4 keeps us under while still beating
# sequential. Anthropic SDK max_retries=10 handles residual 429 via retry-after.

# Uniform phase signature
PhaseFn = Callable[[Lead, str, str, str], dict]

# Words that disqualify a token from being part of a person's name.
_NON_NAME_WORDS = frozenset({
    # Articles / determiners
    "the", "a", "an",
    # Business entity suffixes
    "inc", "llc", "ltd", "corp", "company", "co",
    # Trade / service words
    "construction", "design", "build", "remodel", "remodeling", "renovation",
    "renovations", "builder", "builders", "contractor", "contractors",
    "improvement", "improvements", "services", "service", "solutions",
    "concepts", "studio", "projects", "properties", "management",
    "kitchen", "bath", "tile", "flooring", "cabinets", "cabinet",
    "interior", "exterior", "home", "homes", "house",
    # Generic descriptor words that appear in business names
    "group", "associates", "partners", "team", "guys", "brothers",
    "general", "level", "next", "top", "best", "pro", "new", "old",
    "classic", "modern", "custom", "premier", "elite", "quality",
    "advanced", "professional", "professionals", "expert", "experts",
    "master", "masters", "local", "national", "american", "total",
    "complete", "all", "first", "premier",
})


def _eponymous_owner(business_name: str) -> str | None:
    """Return 'First Last' if the business name is clearly a person's name.

    Requires exactly two words, both purely alphabetic, title-cased, neither
    all-caps (rules out acronyms like RRH or JFK), and neither matching the
    non-name word list. Returns None in all other cases.
    """
    words = business_name.strip().split()
    if len(words) != 2:
        return None
    first, last = words[0], words[1]
    for w in (first, last):
        if not w.isalpha():
            return None
        if not w[0].isupper():
            return None
        # Reject acronyms (RRH, JFK) — all letters uppercase
        if w == w.upper():
            return None
        if w.lower() in _NON_NAME_WORDS:
            return None
    return f"{first} {last}"


def _build_phase_list(state: CampaignState) -> list[PhaseFn]:
    """Build the ordered list of phases to run based on campaign toggles.

    yelp_profile always runs first — it's free (no LLM) and silently
    falls through when Yelp is unavailable or the owner field is absent.
    """
    phases: list[PhaseFn] = [yelp_profile.lookup, website.lookup]
    if state.use_registry:
        phases.append(opencorporates.lookup)
    if state.use_websearch:
        phases.append(websearch.lookup)
    return phases


def _research_one(
    lead: Lead,
    city: str,
    state_abbr: str,
    anthropic_key: str,
    phases: list[PhaseFn],
) -> dict:
    """Run phases sequentially, short-circuit on first high/medium confidence."""
    if not lead.kept or not lead.business_name:
        return {"owner_full_name": "", "confidence": "none", "phase": "skipped"}

    # Free pre-check: eponymous businesses ("Andrew Roby") — no API call needed.
    eponymous = _eponymous_owner(lead.business_name)
    if eponymous:
        return {"owner_full_name": eponymous, "confidence": "medium", "phase": "name_heuristic"}

    for phase_fn in phases:
        try:
            result = phase_fn(lead, city, state_abbr, anthropic_key)
        except Exception:
            continue  # external failure — try next phase
        if result.get("owner_full_name") and result.get("confidence") in ("high", "medium"):
            return result

    return {"owner_full_name": "", "confidence": "none", "phase": "not_found"}


def run(state: CampaignState, anthropic_key: str) -> None:
    """Research owner names for all kept leads with no existing owner name."""
    phases = _build_phase_list(state)
    phase_names = [fn.__module__.split(".")[-1] for fn in phases]
    targets = [l for l in state.leads if l.kept and not l.owner_full_name]
    state.info(
        "owner_researcher",
        f"researching {len(targets)} owners (parallel × {MAX_PARALLEL})",
        phases=phase_names,
    )

    phase_counts: dict[str, int] = {}
    not_found = 0
    pre_enriched = 0

    with futures.ThreadPoolExecutor(max_workers=MAX_PARALLEL) as pool:
        future_map = {
            pool.submit(
                _research_one, lead, state.city, state.state_abbr, anthropic_key, phases
            ): lead
            for lead in targets
        }
        for fut in futures.as_completed(future_map):
            lead = future_map[fut]
            try:
                result = fut.result()
            except Exception as e:
                state.info(
                    "owner_researcher",
                    f"error on {lead.business_name}",
                    error=str(e),
                )
                result = {"owner_full_name": "", "confidence": "none"}

            full = (result.get("owner_full_name") or "").strip()
            if full and result.get("confidence") in ("high", "medium"):
                lead.owner_full_name = full
                lead.owner_first, lead.owner_last = split_name(full)
                lead.owner_source = result.get("phase", "")
                phase_counts[lead.owner_source] = phase_counts.get(lead.owner_source, 0) + 1
                email = (result.get("owner_email") or "").strip().lower()
                if email and result.get("phase") == "website":
                    lead.email = email
                    pre_enriched += 1
            else:
                not_found += 1

            # Per-lead checkpoint: write to Supabase immediately so --resume works.
            state.save_leads()

    state.info(
        "owner_researcher",
        "done",
        by_phase=phase_counts,
        not_found=not_found,
        pre_enriched=pre_enriched,
    )
