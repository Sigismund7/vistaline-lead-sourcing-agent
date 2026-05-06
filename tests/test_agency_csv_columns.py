"""Smoke-check that the agency CSV column list matches csv_agency.AGENCY_COLUMNS."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from agents.csv_agency import AGENCY_COLUMNS

EXPECTED = [
    "Total", "Lead Sourcer", "Business", "Owner Full Name",
    "First", "Last", "Owner Email", "LinkedIn", "Website",
    "Phone", "Date", "X Project", "Y Detail",
]

assert AGENCY_COLUMNS == EXPECTED, f"Column mismatch: {AGENCY_COLUMNS}"
print("OK — agency CSV columns match")
