"""Async wrapper that runs the synchronous pipeline in a thread pool."""
from __future__ import annotations
import asyncio

from config import CONFIG
from state import CampaignState
from agents import sourcer, lead_filter, owner_researcher, csv_assembler


async def run_pipeline(campaign_id: str) -> None:
    """Launch the pipeline for campaign_id in a thread (non-blocking)."""
    loop = asyncio.get_event_loop()
    await loop.run_in_executor(None, _run_sync, campaign_id)


def _run_sync(campaign_id: str) -> None:
    state = CampaignState.load(campaign_id)
    try:
        sourcer.run(state, CONFIG.google_places_key)
        lead_filter.run(state, CONFIG.anthropic_key)
        owner_researcher.run(state, CONFIG.anthropic_key)
        csv_assembler.run(state)
        state.save_leads()
        state.status = "completed"
        state.save()
    except Exception as exc:
        state.status = "failed"
        state.info("runner", f"Pipeline failed: {exc}", level="error")
        state.save()
        raise
