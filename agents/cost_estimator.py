# agents/cost_estimator.py
"""Pre-run Anthropic API cost projector for the Vistaline lead pipeline.

Projects spend (USD) given a target number of named leads.
Uses empirical token counts calibrated from real runs. No API calls — pure math.
"""
from __future__ import annotations
import math
from dataclasses import dataclass

# claude-sonnet-4-20250514 pricing (May 2026)
_SONNET_INPUT_PER_MTOK: float = 3.00    # USD per million input tokens
_SONNET_OUTPUT_PER_MTOK: float = 15.00  # USD per million output tokens

# Lead filter: system ~500t + 80t/lead × 25-lead batch. Output ~20t/lead.
_FILTER_SYSTEM_TOKENS: int = 500
_FILTER_TOKENS_PER_LEAD: int = 80
_FILTER_OUTPUT_TOKENS_PER_LEAD: int = 20
_FILTER_BATCH_SIZE: int = 25

# Owner researcher Phase 1 (website crawl + Claude parse): ~2500t input, ~300t output per lead
_OWNER_P1_INPUT_TOKENS: int = 2500
_OWNER_P1_OUTPUT_TOKENS: int = 300

# Owner researcher Phase 3 (web_search with max_uses=7): ~$0.04/lead per codebase docstring
_OWNER_P3_COST_PER_LEAD: float = 0.04

# Default empirical rates (calibrated from smoke-test observations)
_DEFAULT_KEEP_RATE: float = 0.45
_DEFAULT_PHASE1_HIT_RATE: float = 0.55
_DEFAULT_PHASE2_HIT_RATE: float = 0.20
_DEFAULT_TOTAL_HIT_RATE: float = 0.65


@dataclass
class CostEstimate:
    """Projected cost breakdown for one pipeline run."""
    target_named_leads: int
    estimated_raw_to_source: int
    estimated_kept: int
    keep_rate: float
    total_owner_hit_rate: float
    lead_filter_usd: float
    owner_phase1_usd: float
    owner_phase3_usd: float
    total_usd: float

    def summary(self) -> str:
        """Human-readable multi-line cost breakdown for CLI banner."""
        return (
            f"  est. raw to source:    {self.estimated_raw_to_source} businesses\n"
            f"  est. kept after filter:{self.estimated_kept}\n"
            f"  lead filter cost:      ${self.lead_filter_usd:.3f}\n"
            f"  owner phase-1 cost:    ${self.owner_phase1_usd:.3f}\n"
            f"  owner phase-3 cost:    ${self.owner_phase3_usd:.3f}\n"
            f"  ── projected total:    ${self.total_usd:.3f}\n"
        )


def estimate(
    target_named: int,
    *,
    keep_rate: float = _DEFAULT_KEEP_RATE,
    total_hit_rate: float = _DEFAULT_TOTAL_HIT_RATE,
    phase1_hit_rate: float = _DEFAULT_PHASE1_HIT_RATE,
    phase2_hit_rate: float = _DEFAULT_PHASE2_HIT_RATE,
) -> CostEstimate:
    """Project Anthropic API spend for a run targeting target_named owner-name leads.

    Args:
        target_named: desired count of leads with owner_first populated.
        keep_rate: fraction of raw sourced leads that pass lead_filter.
        total_hit_rate: fraction of kept leads that get an owner name across all phases.
        phase1_hit_rate: fraction of kept leads found by website crawl phase.
        phase2_hit_rate: fraction of phase-1 misses found by OpenCorporates (free tier).
    """
    if target_named <= 0:
        return CostEstimate(
            target_named_leads=0, estimated_raw_to_source=0, estimated_kept=0,
            keep_rate=keep_rate, total_owner_hit_rate=total_hit_rate,
            lead_filter_usd=0.0, owner_phase1_usd=0.0, owner_phase3_usd=0.0, total_usd=0.0,
        )

    raw = math.ceil(target_named / (keep_rate * total_hit_rate))
    kept = math.ceil(raw * keep_rate)

    # Lead filter
    filter_batches = math.ceil(raw / _FILTER_BATCH_SIZE)
    filter_input = filter_batches * (_FILTER_SYSTEM_TOKENS + _FILTER_TOKENS_PER_LEAD * _FILTER_BATCH_SIZE)
    filter_output = filter_batches * (_FILTER_OUTPUT_TOKENS_PER_LEAD * _FILTER_BATCH_SIZE)
    filter_usd = (
        filter_input * _SONNET_INPUT_PER_MTOK + filter_output * _SONNET_OUTPUT_PER_MTOK
    ) / 1_000_000

    # Owner Phase 1
    p1_input = kept * _OWNER_P1_INPUT_TOKENS
    p1_output = kept * _OWNER_P1_OUTPUT_TOKENS
    p1_usd = (
        p1_input * _SONNET_INPUT_PER_MTOK + p1_output * _SONNET_OUTPUT_PER_MTOK
    ) / 1_000_000

    # Owner Phase 3: leads that phase1 and phase2 both miss
    phase3_reach = 1.0 - phase1_hit_rate - (1.0 - phase1_hit_rate) * phase2_hit_rate
    p3_leads = math.ceil(kept * phase3_reach)
    p3_usd = p3_leads * _OWNER_P3_COST_PER_LEAD

    total = filter_usd + p1_usd + p3_usd
    return CostEstimate(
        target_named_leads=target_named,
        estimated_raw_to_source=raw,
        estimated_kept=kept,
        keep_rate=keep_rate,
        total_owner_hit_rate=total_hit_rate,
        lead_filter_usd=round(filter_usd, 4),
        owner_phase1_usd=round(p1_usd, 4),
        owner_phase3_usd=round(p3_usd, 4),
        total_usd=round(total, 4),
    )
