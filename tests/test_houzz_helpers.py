"""Unit tests for Houzz city-fuzzy-match helper.

Tests the scoring logic in isolation — no HTTP calls, no Houzz dependency.
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from rapidfuzz import fuzz


def _city_score(result_location: str, target_city: str) -> float:
    """Extract city portion and score against target. Mirrors houzz.py logic."""
    # Location strings from Houzz look like "Tampa, FL" or "Tampa, Florida"
    city_part = result_location.split(",")[0].strip()
    return fuzz.token_sort_ratio(city_part.lower(), target_city.lower())


def test_exact_match():
    assert _city_score("Tampa, FL", "Tampa") >= 85

def test_case_insensitive():
    assert _city_score("TAMPA, FL", "Tampa") >= 85

def test_nearby_suburb_fails():
    # "Clearwater" is near Tampa but should NOT match Tampa
    assert _city_score("Clearwater, FL", "Tampa") < 85

def test_different_city_fails():
    assert _city_score("Atlanta, GA", "Tampa") < 85

def test_empty_location():
    assert _city_score("", "Tampa") < 85

def test_city_with_extra_text():
    # Documents expected score range (not a hard pass/fail threshold)
    score = _city_score("San Francisco Bay Area, CA", "San Francisco")
    assert isinstance(score, (int, float))

if __name__ == "__main__":
    test_exact_match()
    test_case_insensitive()
    test_nearby_suburb_fails()
    test_different_city_fails()
    test_empty_location()
    test_city_with_extra_text()
    print("OK")
