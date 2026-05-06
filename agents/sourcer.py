"""Sourcer router — parallel fanout across Azure Maps + Yelp Fusion, with
cross-source dedup and website backfill via website_finder.

Cycle 4 refactor: this module used to call Google Places directly. It is now
a thin orchestrator that calls two source adapters concurrently
(`agents/sources/azure_maps.py`, `agents/sources/yelp_fusion.py`), merges
their normalized 9-key dicts via rapidfuzz token_sort_ratio, then
sequentially fills missing websites with `agents/website_finder.py`.

Architectural notes (CLAUDE.md):
  - Each parallel worker constructs its own AzureMapsClient / YelpFusionClient
    instance — those clients carry token-bucket state and an unguarded
    requests.Session and are NOT thread-safe. Sharing across workers would
    race the rate limiter.
  - One BraveSearchClient + one requests.Session are shared across the
    sequential website_finder phase. That phase is single-threaded so the
    thread-safety rule does not apply.
  - State checkpointing via state.is_done / state.mark_done is preserved so
    `python run.py --resume` continues to work.

Backward-compat: run.py calls `sourcer.run(state, places_key)`. We keep the
two-arg signature but ignore the second positional (Google Places is no
longer the data source) so run.py is untouched (Premise 5).
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

import requests
from rapidfuzz import fuzz

from config import CONFIG
from state import CampaignState, Lead
from tools import AzureMapsClient, BraveSearchClient, YelpFusionClient
from agents.sources import azure_maps as azure_source
from agents.sources import yelp_fusion as yelp_source
from agents.website_finder import find_website
from agents import leads_cache


# Number of source adapters fanned out in parallel. Two for now (Azure +
# Yelp); CLAUDE.md's MAX_PARALLEL=8 ceiling applies if more are added later.
_FANOUT_WORKERS = 2


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
    """Extract the 3-digit US area code from a phone string, or '' if not parseable."""
    digits = "".join(c for c in (phone or "") if c.isdigit())
    if len(digits) == 11 and digits.startswith("1"):
        digits = digits[1:]
    return digits[:3] if len(digits) >= 10 else ""


def _source_via_azure(state: CampaignState) -> list[dict]:
    """Worker A: construct an AzureMapsClient and source leads.

    Constructs a fresh client per worker invocation — the client's rate
    limiter and HTTP session are NOT thread-safe (see tools.AzureMapsClient
    docstring) so it must not be shared with the Yelp worker.
    """
    client = AzureMapsClient(
        api_key=CONFIG.azure_maps_key,
        rate_limit_qps=CONFIG.azure_maps_rate_limit_qps,
        jitter_ms=CONFIG.azure_maps_jitter_ms,
        max_retries=CONFIG.api_max_retries,
        backoff_base_s=CONFIG.api_backoff_base_s,
        backoff_max_s=CONFIG.api_backoff_max_s,
        request_timeout_s=CONFIG.api_request_timeout_s,
    )
    return azure_source.source_leads(
        client,
        state=state.state_abbr,
        city=state.city,
        niche=state.niche,
        count=state.target_count,
        radius_m=CONFIG.azure_maps_default_radius_m,
    )


def _source_via_yelp(state: CampaignState) -> list[dict]:
    """Worker B: construct a YelpFusionClient and source leads.

    Constructs a fresh client per worker invocation — same thread-safety
    rationale as the Azure worker.
    """
    client = YelpFusionClient(
        api_key=CONFIG.yelp_fusion_key,
        rate_limit_qps=CONFIG.yelp_rate_limit_qps,
        jitter_ms=CONFIG.yelp_jitter_ms,
        max_retries=CONFIG.api_max_retries,
        backoff_base_s=CONFIG.api_backoff_base_s,
        backoff_max_s=CONFIG.api_backoff_max_s,
        request_timeout_s=CONFIG.api_request_timeout_s,
    )
    return yelp_source.source_leads(
        client,
        state=state.state_abbr,
        city=state.city,
        niche=state.niche,
        count=state.target_count,
        radius_m=CONFIG.yelp_default_radius_m,
    )


def _dedupe_cross_source(leads: list[dict], threshold: int) -> list[dict]:
    """Merge cross-source duplicates by rapidfuzz token_sort_ratio.

    For each candidate, compare its "name + address" key against each existing
    survivor. If the score >= threshold, treat it as a duplicate of that
    survivor; we keep the Azure-side record (it carries more reliable
    websites + metadata) and tag the merged record's `source` so downstream
    can see it was confirmed by both providers.

    Note: this is O(N^2). At target counts of ~50-200 leads per city that
    is fine; if we ever push to 1000s/city, switch to a blocking key on
    the first 4 chars of the slug + address-postcode and only fuzz within
    blocks.
    """
    survivors: list[dict] = []
    for cand in leads:
        cand_key = f"{cand.get('business_name', '')} {cand.get('address', '')}"
        merged = False
        for i, surv in enumerate(survivors):
            surv_key = f"{surv.get('business_name', '')} {surv.get('address', '')}"
            score = fuzz.token_sort_ratio(cand_key, surv_key)
            if score >= threshold:
                # Azure wins on tie. If the survivor is already Azure, keep
                # it and stash the Yelp candidate's raw blob; if the survivor
                # is Yelp and the candidate is Azure, swap so Azure wins.
                if surv.get("source") == "azure_maps" and cand.get("source") == "yelp_fusion":
                    surv["source"] = "azure_maps+yelp_fusion"
                    surv["raw_yelp"] = cand.get("raw")
                # Defensive: handles the case where a future caller passes leads in
                # Yelp-first order. run() currently always passes Azure-first, but
                # this branch preserves the "Azure wins on tie" merge semantics.
                elif surv.get("source") == "yelp_fusion" and cand.get("source") == "azure_maps":
                    new_record = dict(cand)
                    new_record["source"] = "azure_maps+yelp_fusion"
                    new_record["raw_yelp"] = surv.get("raw")
                    survivors[i] = new_record
                # Same-source matches (rare, since each adapter dedupes
                # internally) are dropped silently — keep the original.
                merged = True
                break
        if not merged:
            survivors.append(cand)
    return survivors


def _enrich_websites(leads: list[dict], state: CampaignState) -> list[dict]:
    """Sequentially fill empty `website` fields via website_finder.

    Single-threaded by design: website_finder's HEAD checks and Brave calls
    are I/O-bound but the Brave client carries budget-counter state we don't
    want to race. One Brave client + one requests.Session is shared across
    every find_website call here.
    """
    brave_client: BraveSearchClient | None = None
    if CONFIG.brave_search_key:
        brave_client = BraveSearchClient(
            api_key=CONFIG.brave_search_key,
            rate_limit_qps=CONFIG.brave_rate_limit_qps,
            jitter_ms=CONFIG.brave_jitter_ms,
            max_retries=CONFIG.api_max_retries,
            backoff_base_s=CONFIG.api_backoff_base_s,
            backoff_max_s=CONFIG.api_backoff_max_s,
            request_timeout_s=CONFIG.api_request_timeout_s,
            max_monthly_queries=CONFIG.brave_max_monthly_queries,
            budget_state_path=None,  # tools.py picks the default monthly path
        )
    http_session = requests.Session()

    enriched_count = 0
    checked = 0
    for lead in leads:
        if lead.get("website"):
            continue
        checked += 1
        result = find_website(
            lead.get("business_name", ""),
            state.city,
            state.state_abbr,
            brave_client=brave_client,
            http_session=http_session,
        )
        if result:
            lead["website"] = result
            enriched_count += 1
        if checked % 10 == 0:
            state.info(
                "sourcer",
                "website-finder progress",
                checked=checked,
                enriched=enriched_count,
            )
    state.info(
        "sourcer",
        "website-finder done",
        checked=checked,
        enriched=enriched_count,
    )
    return leads


def _to_lead(normalized: dict) -> Lead:
    """Convert a 9-key normalized source dict into a `Lead` dataclass.

    `place_id` is mapped from `source_id` (legacy field name; `Lead` was
    designed when Google Places was the only source). `domain` and
    `area_code` are derived helpers consistent with the pre-Cycle-4 sourcer.
    `yelp_id` is the Yelp business alias, available when the source includes
    Yelp data — used by the yelp_profile owner-research phase.

    Defensive contract: optional fields (phone, website, address, lat, lon,
    raw) default to empty strings when missing — a buggy adapter returning
    a partial dict shouldn't crash the router. `business_name` and
    `source_id` are also resolved via `.get(..., "")` so a fully-malformed
    dict produces an empty-string Lead rather than a `KeyError`; callers
    should still treat them as required and surface upstream if absent.
    """
    website = normalized.get("website", "") or ""
    phone = normalized.get("phone", "") or ""
    source = normalized.get("source", "")

    # Determine Yelp alias. Yelp-only leads carry it as source_id.
    # Merged leads carry the Azure ID as source_id but the Yelp raw dict
    # is attached as raw_yelp by the merge step in _merge_sources().
    if source == "yelp_fusion":
        yelp_id = normalized.get("source_id", "") or ""
    elif source == "azure_maps+yelp_fusion":
        yelp_id = (normalized.get("raw_yelp") or {}).get("id", "") or ""
    else:
        yelp_id = ""

    return Lead(
        business_name=normalized.get("business_name", "") or "",
        phone=phone,
        website=website,
        address=normalized.get("address", "") or "",
        area_code=_area_code(phone),
        domain=_normalize_domain(website),
        place_id=normalized.get("source_id", "") or "",
        yelp_id=yelp_id,
    )


def run(state: CampaignState, _unused_places_key: str | None = None) -> None:
    """Source contractor leads via Azure Maps + Yelp Fusion in parallel.

    Steps:
      1. Short-circuit if state.is_done("sourcer") — preserves resume.
      2. Fanout: ThreadPoolExecutor(2) with one Azure worker + one Yelp worker.
         Each worker constructs its own client (thread-safety rule).
      3. Dedupe cross-source via rapidfuzz token_sort_ratio at the
         CONFIG.dedup_match_threshold ceiling. Azure wins on tie.
      4. For each surviving lead with empty website, call website_finder
         with one shared Brave client + requests.Session.
      5. Convert dicts to Lead dataclasses, append to state.leads up to
         target_count, mark_done.

    The second positional argument is accepted for backward-compat with
    run.py (which still passes the legacy Google Places API key) but is
    ignored — Google Places is no longer the source.
    """
    if state.is_done("sourcer"):
        state.info("sourcer", f"already complete, skipping ({len(state.leads)} leads)")
        return

    state.info(
        "sourcer",
        "starting",
        target=state.target_count,
        niche=state.niche,
        location=f"{state.city}, {state.state_abbr}",
    )

    # ---- 2. Parallel fanout ---------------------------------------------- #
    azure_results: list[dict] = []
    yelp_results: list[dict] = []
    with ThreadPoolExecutor(max_workers=_FANOUT_WORKERS) as pool:
        future_azure = pool.submit(_source_via_azure, state)
        future_yelp = pool.submit(_source_via_yelp, state)
        try:
            azure_results = future_azure.result()
        except Exception as e:  # external-source failure: log and continue
            state.info("sourcer", "azure source failed", error=f"{type(e).__name__}: {e}")
        try:
            yelp_results = future_yelp.result()
        except Exception as e:  # external-source failure: log and continue
            state.info("sourcer", "yelp source failed", error=f"{type(e).__name__}: {e}")

    state.info(
        "sourcer",
        "fanout complete",
        azure_count=len(azure_results),
        yelp_count=len(yelp_results),
    )

    # ---- 3. Cross-source dedup ------------------------------------------- #
    # Concatenate Azure first so it wins ties when survivors order is checked.
    combined = list(azure_results) + list(yelp_results)
    before = len(combined)
    deduped = _dedupe_cross_source(combined, threshold=CONFIG.dedup_match_threshold)
    after = len(deduped)
    state.info(
        "sourcer",
        "deduped",
        before=before,
        after=after,
        merged=before - after,
    )

    # ---- 4. Website backfill --------------------------------------------- #
    deduped = _enrich_websites(deduped, state)

    # ---- 4.5 Cross-run dedup cache --------------------------------------- #
    try:
        deduped = leads_cache.filter_unseen(
            deduped, state.city, state.state_abbr, CONFIG.leads_cache_ttl_days
        )
    except Exception as exc:
        state.info("sourcer", "leads_cache.filter_unseen error (non-fatal)", error=str(exc))

    # ---- 5. Convert + persist -------------------------------------------- #
    new_leads: list[dict] = []
    for normalized in deduped:
        if len(state.leads) >= state.target_count:
            break
        state.leads.append(_to_lead(normalized))
        new_leads.append(normalized)

    leads_cache.mark_seen(new_leads, state.city, state.state_abbr, state.campaign_id)

    if len(new_leads) < state.target_count:
        state.info(
            "sourcer", "cache filtered short",
            found=len(new_leads), target=state.target_count,
        )

    state.info("sourcer", "done", final_count=len(state.leads))
    state.mark_done("sourcer")
