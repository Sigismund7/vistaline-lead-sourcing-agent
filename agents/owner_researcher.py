"""Owner Researcher — finds the owner's full name for every kept lead.

Phase order (after the BBB Phase 0 reshape):

  Phase 0a: yelp_profile.lookup   — Yelp Business Owner field. OPTIONAL,
                                    gated by ``CONFIG.yelp_phase0_enabled``.
  Phase 0b: bbb_direct.lookup     — BBB.org search + ScraperAPI profile +
                                    JSON-LD/DOM owner parse. ~$0.005/lead.
  Phase 0c: bbb_websearch.lookup  — Claude web_search constrained to
                                    bbb.org. ~$0.01/lead.
  Phase 1:  website.lookup        — crawl own website, ask Claude. Free.
  Phase 2:  websearch.lookup      — open Claude web_search across Houzz,
                                    Google, review responses. ~$0.05/lead.

Compare mode (``CONFIG.bbb_compare_mode``): when both ``bbb_direct`` and
``bbb_websearch`` are enabled, BOTH run on every kept lead — no
short-circuit — so we can A/B their hit rates side-by-side. Per-phase
results land on ``lead.bbb_direct_*`` and ``lead.bbb_websearch_*`` for
later analytics. Resolution: direct wins on tie or conflict.

Outside compare mode, phases run sequentially and short-circuit on the
first high/medium-confidence (or `partial`) result. Never guesses — if
all phases fail, owner fields stay blank.
"""
from __future__ import annotations
import concurrent.futures as futures
from typing import Callable

from config import CONFIG
from state import CampaignState, Lead
from agents.sources.owners import bbb_direct, bbb_websearch, website, websearch
from agents.sources.owners._utils import split_name


MAX_PARALLEL = 4  # Each worker can fire 2-3 Sonnet calls per lead (Phase 1
# website crawl + Phase 3 web_search). At 8 workers we burst past the org's
# 30k input-tokens-per-minute cap; 4 keeps us under while still beating
# sequential. Anthropic SDK max_retries=10 handles residual 429 via retry-after.

# Confidence levels that count as a valid stop / commit-to-CSV. 'partial' is
# included so truncated-name fallbacks (e.g. BBB returned "John O." and the
# web_search expansion couldn't confirm the full last name) still ship the
# partial result with needs_review=True instead of being silently dropped.
_STOP_CONFIDENCES = ("high", "medium", "partial")

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
    """Build the ordered list of phases to run based on config + campaign toggles.

    Order: yelp_profile (optional) → bbb_direct → bbb_websearch → website →
    websearch (open). The BBB pair is run in compare mode inside
    ``_research_one``; the order here is just for fall-through after the
    BBB block.
    """
    phases: list[PhaseFn] = []
    if CONFIG.yelp_phase0_enabled:
        # Lazy import keeps the optional ScraperAPI/Yelp dep out of the
        # import graph when the flag is off.
        from agents.sources.owners import yelp_profile  # noqa: WPS433
        phases.append(yelp_profile.lookup)
    if CONFIG.bbb_direct_enabled:
        phases.append(bbb_direct.lookup)
    if CONFIG.bbb_websearch_enabled:
        phases.append(bbb_websearch.lookup)
    phases.append(website.lookup)
    if state.use_websearch:
        phases.append(websearch.lookup)
    return phases


def _phase_name(phase_fn: PhaseFn) -> str:
    """Return the source-module short name (e.g. ``bbb_direct``)."""
    return phase_fn.__module__.split(".")[-1]


def _record_bbb_result_on_lead(lead: Lead, phase_name: str, result: dict) -> None:
    """Persist a BBB phase's result onto the compare-mode artifact fields."""
    name = (result.get("owner_full_name") or "").strip()
    url = (result.get("source_url") or "").strip()
    if phase_name == "bbb_direct":
        lead.bbb_direct_name = name
        lead.bbb_direct_url = url
    elif phase_name == "bbb_websearch":
        lead.bbb_websearch_name = name
        lead.bbb_websearch_url = url


def _research_one(
    lead: Lead,
    city: str,
    state_abbr: str,
    anthropic_key: str,
    phases: list[PhaseFn],
) -> dict:
    """Run the per-lead phase pipeline with BBB compare-mode semantics.

    Compare mode (``CONFIG.bbb_compare_mode`` AND both BBB phases enabled):
    both ``bbb_direct`` and ``bbb_websearch`` run — even if the first returns
    a high-confidence hit — so we can record both for A/B analytics. Direct
    wins on conflict. ``lead.bbb_conflict`` is set when both produce
    non-empty, case-folded-distinct names.

    Outside compare mode, all phases run sequentially and short-circuit on
    the first owner name with confidence in {high, medium, partial}.
    """
    if not lead.kept or not lead.business_name:
        return {"owner_full_name": "", "confidence": "none", "phase": "skipped"}

    # Free pre-check: eponymous businesses ("Andrew Roby") — no API call needed.
    eponymous = _eponymous_owner(lead.business_name)
    if eponymous:
        return {"owner_full_name": eponymous, "confidence": "medium", "phase": "name_heuristic"}

    bbb_phases_in_list = [p for p in phases if p in (bbb_direct.lookup, bbb_websearch.lookup)]
    other_phases = [p for p in phases if p not in (bbb_direct.lookup, bbb_websearch.lookup)]

    if CONFIG.bbb_compare_mode and len(bbb_phases_in_list) == 2:
        # Run BOTH BBB phases unconditionally — measurement comes first.
        bbb_results: dict[str, dict] = {}
        for phase_fn in bbb_phases_in_list:
            name = _phase_name(phase_fn)
            try:
                bbb_results[name] = phase_fn(lead, city, state_abbr, anthropic_key)
            except Exception:
                bbb_results[name] = {"owner_full_name": "", "confidence": "none"}

        d = bbb_results.get("bbb_direct", {})
        w = bbb_results.get("bbb_websearch", {})
        _record_bbb_result_on_lead(lead, "bbb_direct", d)
        _record_bbb_result_on_lead(lead, "bbb_websearch", w)

        if (
            lead.bbb_direct_name
            and lead.bbb_websearch_name
            and lead.bbb_direct_name.lower().strip() != lead.bbb_websearch_name.lower().strip()
        ):
            lead.bbb_conflict = True

        # Resolution: direct wins on tie/conflict; websearch only if direct empty.
        for candidate in (d, w):
            if candidate.get("owner_full_name") and candidate.get("confidence") in _STOP_CONFIDENCES:
                return candidate
    else:
        # Compare mode off (or only one BBB phase enabled). Sequential +
        # short-circuit, but still record per-phase artifacts.
        for phase_fn in bbb_phases_in_list:
            try:
                result = phase_fn(lead, city, state_abbr, anthropic_key)
            except Exception:
                continue
            _record_bbb_result_on_lead(lead, _phase_name(phase_fn), result)
            if result.get("owner_full_name") and result.get("confidence") in _STOP_CONFIDENCES:
                return result

    # Phase 1+: standard sequential fall-through.
    for phase_fn in other_phases:
        try:
            result = phase_fn(lead, city, state_abbr, anthropic_key)
        except Exception:
            continue
        if result.get("owner_full_name") and result.get("confidence") in _STOP_CONFIDENCES:
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
            if full and result.get("confidence") in _STOP_CONFIDENCES:
                lead.owner_full_name = full
                lead.owner_first, lead.owner_last = split_name(full)
                lead.owner_source = result.get("phase", "")
                # Propagate the partial-name review flag so the analyst can
                # filter on it before FindyMail upload. Phases set this when
                # they shipped a truncated name they couldn't confidently expand.
                if result.get("needs_review"):
                    lead.needs_review = True
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
