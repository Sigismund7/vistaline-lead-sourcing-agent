"""Async wrapper that runs the synchronous quota-fulfillment pipeline in a thread pool."""
from __future__ import annotations
import asyncio
import math

from config import CONFIG
from state import CampaignState
from agents import sourcer, lead_filter, owner_researcher, csv_assembler

MAX_SOURCING_ROUNDS = 5
_KEEP_EST = 0.45
_HIT_EST = 0.65


def _leads_per_round(target: int) -> int:
    """Raw leads to source per round so MAX_SOURCING_ROUNDS rounds at expected rates fills quota."""
    return max(50, math.ceil(target / (_KEEP_EST * _HIT_EST) / MAX_SOURCING_ROUNDS * 1.2))


async def run_pipeline(campaign_id: str) -> None:
    """Launch the quota-fulfillment pipeline for campaign_id in a thread (non-blocking)."""
    loop = asyncio.get_event_loop()
    await loop.run_in_executor(None, _run_sync, campaign_id)


def _run_sync(campaign_id: str) -> None:
    """Run the quota-fulfillment pipeline synchronously.

    Loops up to MAX_SOURCING_ROUNDS, sourcing a batch of leads each round and
    filtering/researching incrementally until target_count named leads are found
    or the geographic area is exhausted.
    """
    state = CampaignState.load(campaign_id)
    try:
        if state.is_done("pipeline_complete"):
            return

        batch = _leads_per_round(state.target_count)
        state.info("runner", f"quota loop: target={state.target_count}, {batch} raw/round")

        for round_n in range(MAX_SOURCING_ROUNDS):
            if not state.is_done(f"sourcer_round_{round_n}"):
                new = sourcer.run(state, CONFIG.google_places_key, round_n=round_n, batch_size=batch)
                if new == 0:
                    state.mark_done("sourcer_exhausted")
                    state.info("runner", f"area exhausted after {round_n} rounds")
                    break

            lead_filter.run(state, CONFIG.anthropic_key)
            owner_researcher.run(state, CONFIG.anthropic_key)

            named = sum(1 for l in state.leads if l.kept and l.owner_first)
            state.info("runner", f"round {round_n} done", named=named, target=state.target_count)

            if named >= state.target_count or state.is_done("sourcer_exhausted"):
                break

        csv_assembler.run(state)
        state.save_leads()
        state.mark_done("pipeline_complete")
        state.status = "completed"
        state.save()
    except Exception as exc:
        state.status = "failed"
        state.info("runner", f"Pipeline failed: {exc}", level="error")
        state.save()
        raise
