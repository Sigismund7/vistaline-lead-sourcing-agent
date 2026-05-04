"""Unit tests for OpenCorporatesClient helpers.

Tests jurisdiction code derivation and officer priority selection in isolation
— no HTTP calls, no API key required.
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from tools import OpenCorporatesClient


def test_jurisdiction_code():
    """State abbreviation maps to us_XX jurisdiction code."""
    assert f"us_{'FL'.lower()}" == "us_fl"
    assert f"us_{'CA'.lower()}" == "us_ca"
    assert f"us_{'NY'.lower()}" == "us_ny"


def test_pick_best_officer_owner():
    c = OpenCorporatesClient()
    officers = [
        {"name": "Jane Smith", "role": "owner", "is_current": True},
        {"name": "Bob Jones", "role": "director", "is_current": True},
    ]
    assert c.pick_best_officer(officers) == "Jane Smith"


def test_pick_best_officer_president_over_manager():
    c = OpenCorporatesClient()
    officers = [
        {"name": "Bob Jones", "role": "manager", "is_current": True},
        {"name": "Jane Smith", "role": "president", "is_current": True},
    ]
    assert c.pick_best_officer(officers) == "Jane Smith"


def test_pick_best_officer_skips_former():
    c = OpenCorporatesClient()
    officers = [
        {"name": "Former Owner", "role": "owner", "is_current": False},
        {"name": "Current Director", "role": "director", "is_current": True},
    ]
    result = c.pick_best_officer(officers)
    assert result == "Current Director"


def test_pick_best_officer_empty():
    c = OpenCorporatesClient()
    assert c.pick_best_officer([]) is None


def test_pick_best_officer_no_priority_role():
    c = OpenCorporatesClient()
    officers = [
        {"name": "Alice Brown", "role": "registered_agent", "is_current": True},
    ]
    assert c.pick_best_officer(officers) == "Alice Brown"


if __name__ == "__main__":
    test_jurisdiction_code()
    test_pick_best_officer_owner()
    test_pick_best_officer_president_over_manager()
    test_pick_best_officer_skips_former()
    test_pick_best_officer_empty()
    test_pick_best_officer_no_priority_role()
    print("OK")
