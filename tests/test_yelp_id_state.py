"""Test that yelp_id survives the Lead dataclass round-trip."""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from state import Lead


def test_yelp_id_defaults_to_empty():
    lead = Lead(business_name="ABC Bath")
    assert lead.yelp_id == ""


def test_yelp_id_stores_value():
    lead = Lead(business_name="ABC Bath", yelp_id="abc-bath-orlando")
    assert lead.yelp_id == "abc-bath-orlando"


def test_lead_fields_not_accidentally_removed():
    # Regression: make sure existing fields still exist after adding yelp_id
    lead = Lead(
        business_name="ABC Bath",
        phone="4075550101",
        website="https://abcbath.com",
        owner_full_name="Jane Smith",
        email="jane@abcbath.com",
        yelp_id="abc-bath-orlando",
    )
    assert lead.business_name == "ABC Bath"
    assert lead.email == "jane@abcbath.com"
    assert lead.yelp_id == "abc-bath-orlando"


if __name__ == "__main__":
    test_yelp_id_defaults_to_empty()
    test_yelp_id_stores_value()
    test_lead_fields_not_accidentally_removed()
    print("OK")
