"""Tests for Lead.filter_done — no Supabase connection required."""
from state import Lead, CampaignState


def _make_state(n_leads: int = 3) -> CampaignState:
    state = CampaignState(campaign_id="test-filter-done")
    state.city = "Orlando"
    state.state_abbr = "FL"
    state.niche = "bathroom remodeling"
    state.target_count = 10
    for i in range(n_leads):
        state.leads.append(Lead(
            business_name=f"Test Co {i}",
            phone="4075550100",
            website=f"https://testco{i}.com",
        ))
    return state


def test_lead_filter_done_defaults_false():
    lead = Lead(business_name="Test Co")
    assert lead.filter_done is False


def test_new_leads_start_as_filter_done_false():
    state = _make_state(3)
    assert all(not l.filter_done for l in state.leads)


def test_filter_done_can_be_set_true():
    lead = Lead(business_name="Test Co")
    lead.filter_done = True
    assert lead.filter_done is True


def test_filter_done_false_leads_are_selectable():
    state = _make_state(4)
    state.leads[0].filter_done = True
    state.leads[1].filter_done = True
    unfiltered = [l for l in state.leads if not l.filter_done]
    assert len(unfiltered) == 2
