"""Background runner for the post-FindyMail personalization flow.

Mirrors api/runner.py. Called by BackgroundTasks after POST /campaigns/{id}/enrich
writes emails onto leads and sets campaign status to "personalizing".
"""
from __future__ import annotations
import asyncio

from config import CONFIG
from state import CampaignState
from agents import personalizer, linkedin_finder


async def run_personalization(campaign_id: str) -> None:
    """Launch personalization for campaign_id in a thread (non-blocking)."""
    loop = asyncio.get_running_loop()
    await loop.run_in_executor(None, _run_sync, campaign_id)


def _run_sync(campaign_id: str) -> None:
    state = CampaignState.load(campaign_id)
    try:
        # Clear personalizer/linkedin_finder checkpoints so they re-run even if
        # a previous personalization attempt was made.
        state.completed_steps = [
            s for s in state.completed_steps
            if s not in (personalizer.STEP_NAME, linkedin_finder.STEP_NAME)
        ]
        state.info("runner_personalize", "Personalization started")
        personalizer.run(
            state,
            CONFIG.anthropic_key,
            yelp_key=CONFIG.yelp_fusion_key,
            model=CONFIG.personalizer_vision_model,
            max_parallel=CONFIG.personalizer_max_parallel,
            timeout_s=CONFIG.personalizer_screenshot_timeout_s,
        )
        linkedin_finder.run(
            state,
            CONFIG.anthropic_key,
            max_parallel=CONFIG.personalizer_max_parallel,
        )
        state.save_leads()
        state.status = "completed"
        state.save()
    except Exception as exc:
        state.status = "failed"
        state.info("runner_personalize", f"Personalization failed: {exc}", level="error")
        state.save()
        raise
