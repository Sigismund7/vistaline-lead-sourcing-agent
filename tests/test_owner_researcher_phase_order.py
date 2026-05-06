"""Test that yelp_profile is Phase 0 (runs before website) in the phase list."""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dataclasses import dataclass, field
from agents.owner_researcher import _build_phase_list
from agents.sources.owners import yelp_profile, website, opencorporates, websearch


@dataclass
class _FakeState:
    city: str = "Orlando"
    state_abbr: str = "FL"
    use_registry: bool = True
    use_websearch: bool = True
    leads: list = field(default_factory=list)
    log: list = field(default_factory=list)
    completed_steps: list = field(default_factory=list)


def test_yelp_profile_is_first_phase():
    state = _FakeState()
    phases = _build_phase_list(state)
    assert phases[0] is yelp_profile.lookup, (
        f"Expected yelp_profile.lookup first, got {phases[0]}"
    )


def test_website_is_second_phase():
    state = _FakeState()
    phases = _build_phase_list(state)
    assert phases[1] is website.lookup


def test_opencorporates_included_when_use_registry_true():
    state = _FakeState(use_registry=True)
    phases = _build_phase_list(state)
    assert opencorporates.lookup in phases


def test_opencorporates_excluded_when_use_registry_false():
    state = _FakeState(use_registry=False)
    phases = _build_phase_list(state)
    assert opencorporates.lookup not in phases


def test_websearch_excluded_when_use_websearch_false():
    state = _FakeState(use_websearch=False)
    phases = _build_phase_list(state)
    assert websearch.lookup not in phases


def test_phase_list_minimum_length_is_two():
    # Even with all toggles off, yelp_profile + website always run
    state = _FakeState(use_registry=False, use_websearch=False)
    phases = _build_phase_list(state)
    assert len(phases) >= 2


if __name__ == "__main__":
    test_yelp_profile_is_first_phase()
    test_website_is_second_phase()
    test_opencorporates_included_when_use_registry_true()
    test_opencorporates_excluded_when_use_registry_false()
    test_websearch_excluded_when_use_websearch_false()
    test_phase_list_minimum_length_is_two()
    print("OK")
