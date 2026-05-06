# tests/test_cost_estimator.py
"""Unit tests for agents/cost_estimator.py — pure math, no API calls."""
from agents.cost_estimator import estimate, CostEstimate


def test_estimate_returns_dataclass():
    result = estimate(target_named=30)
    assert isinstance(result, CostEstimate)


def test_estimate_raw_leads_formula():
    # raw = ceil(30 / (0.45 * 0.65)) = ceil(102.56) = 103
    result = estimate(target_named=30, keep_rate=0.45, total_hit_rate=0.65)
    assert result.estimated_raw_to_source == 103


def test_estimate_kept_formula():
    result = estimate(target_named=30, keep_rate=0.45, total_hit_rate=0.65)
    # kept = ceil(103 * 0.45) = ceil(46.35) = 47
    assert result.estimated_kept == 47


def test_total_is_sum_of_parts():
    result = estimate(target_named=30)
    parts = result.lead_filter_usd + result.owner_phase1_usd + result.owner_phase3_usd
    assert abs(result.total_usd - parts) < 0.001


def test_zero_target_returns_zero_cost():
    result = estimate(target_named=0)
    assert result.total_usd == 0.0
    assert result.estimated_raw_to_source == 0


def test_larger_target_costs_more():
    small = estimate(target_named=20)
    large = estimate(target_named=60)
    assert large.total_usd > small.total_usd


def test_higher_keep_rate_lowers_cost():
    low_keep = estimate(target_named=30, keep_rate=0.30)
    high_keep = estimate(target_named=30, keep_rate=0.70)
    assert high_keep.total_usd < low_keep.total_usd


def test_summary_contains_dollar_sign():
    result = estimate(target_named=30)
    assert "$" in result.summary()
