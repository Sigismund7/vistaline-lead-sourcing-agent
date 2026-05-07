"""Test that _to_lead populates yelp_id correctly by source."""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agents.sourcer import _to_lead


def _yelp_lead(alias: str) -> dict:
    return {
        "source": "yelp_fusion",
        "source_id": alias,
        "business_name": "ABC Bath",
        "address": "123 Main St, Orlando, FL",
        "phone": "+14075550101",
        "website": "",
        "lat": 28.5,
        "lon": -81.4,
        "raw": {"id": alias, "name": "ABC Bath"},
    }


def _azure_lead() -> dict:
    return {
        "source": "azure_maps",
        "source_id": "deadbeef-1234",
        "business_name": "XYZ Remodeling",
        "address": "456 Elm St, Orlando, FL",
        "phone": "+14075550202",
        "website": "https://xyz.com",
        "lat": 28.5,
        "lon": -81.4,
        "raw": {},
    }


def _merged_lead(azure_id: str, yelp_alias: str) -> dict:
    return {
        "source": "azure_maps+yelp_fusion",
        "source_id": azure_id,
        "business_name": "MNO Kitchen",
        "address": "789 Oak Ave, Orlando, FL",
        "phone": "+14075550303",
        "website": "https://mno.com",
        "lat": 28.5,
        "lon": -81.4,
        "raw": {},
        "raw_yelp": {"id": yelp_alias, "name": "MNO Kitchen"},
    }


def test_yelp_sourced_lead_gets_yelp_id():
    lead = _to_lead(_yelp_lead("abc-bath-orlando"))
    assert lead.yelp_id == "abc-bath-orlando"


def test_azure_only_lead_has_empty_yelp_id():
    lead = _to_lead(_azure_lead())
    assert lead.yelp_id == ""


def test_merged_lead_gets_yelp_id_from_raw_yelp():
    lead = _to_lead(_merged_lead("deadbeef-5678", "mno-kitchen-orlando"))
    assert lead.yelp_id == "mno-kitchen-orlando"


def test_merged_lead_without_raw_yelp_has_empty_yelp_id():
    raw = _merged_lead("deadbeef-5678", "mno-kitchen-orlando")
    del raw["raw_yelp"]
    lead = _to_lead(raw)
    assert lead.yelp_id == ""


if __name__ == "__main__":
    test_yelp_sourced_lead_gets_yelp_id()
    test_azure_only_lead_has_empty_yelp_id()
    test_merged_lead_gets_yelp_id_from_raw_yelp()
    test_merged_lead_without_raw_yelp_has_empty_yelp_id()
    print("OK")
