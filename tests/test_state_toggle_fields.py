# tests/test_state_toggle_fields.py
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from state import CampaignState

def test_toggle_defaults():
    state = CampaignState(campaign_id="test-001", city="Tampa", state_abbr="FL", niche="Kitchen")
    assert state.use_registry is True
    assert state.use_websearch is True

def test_toggle_false():
    state = CampaignState(
        campaign_id="test-002", city="Tampa", state_abbr="FL", niche="Kitchen",
        use_registry=False, use_websearch=False,
    )
    assert state.use_registry is False
    assert state.use_websearch is False

if __name__ == "__main__":
    test_toggle_defaults()
    test_toggle_false()
    print("OK")
