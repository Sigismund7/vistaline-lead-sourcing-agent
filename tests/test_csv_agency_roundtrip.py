"""Round-trip a synthetic FindyMail-enriched CSV through the agency reader."""
from __future__ import annotations
import csv
import os
import tempfile
import unittest

os.environ.setdefault("SUPABASE_URL", "http://fake")
os.environ.setdefault("SUPABASE_SERVICE_ROLE_KEY", "fake")

from agents.csv_agency import read_enriched, AGENCY_COLUMNS


SAMPLE_ROWS = [
    {
        "First Name": "Brett",
        "Last Name": "Primack",
        "Company": "Las Vegas Remodel",
        "Domain": "lvremodel.com",
        "email": "brett@lvremodel.com",
        "phone": "+1 702-425-7272",
        "website": "http://lvremodel.com",
        "address": "123 Main, Las Vegas NV",
    },
    {
        "First Name": "Cyndi",
        "Last Name": "Huff",
        "Company": "Dream Construction",
        "Domain": "dreamconstr.com",
        "email": "",
        "phone": "+1 702-816-5800",
        "website": "https://dreamconstr.com",
        "address": "",
    },
]


class ReadEnrichedTest(unittest.TestCase):
    def test_loads_leads_with_email_field_populated(self):
        with tempfile.NamedTemporaryFile(
            "w", suffix=".csv", delete=False, newline="", encoding="utf-8"
        ) as f:
            writer = csv.DictWriter(f, fieldnames=list(SAMPLE_ROWS[0].keys()))
            writer.writeheader()
            writer.writerows(SAMPLE_ROWS)
            path = f.name

        state = read_enriched(path)
        self.assertEqual(len(state.leads), 2)

        brett = state.leads[0]
        self.assertEqual(brett.owner_first, "Brett")
        self.assertEqual(brett.owner_last, "Primack")
        self.assertEqual(brett.owner_full_name, "Brett Primack")
        self.assertEqual(brett.business_name, "Las Vegas Remodel")
        self.assertEqual(brett.domain, "lvremodel.com")
        self.assertEqual(brett.email, "brett@lvremodel.com")
        self.assertEqual(brett.phone, "+1 702-425-7272")

        cyndi = state.leads[1]
        self.assertEqual(cyndi.email, "")

    def test_agency_columns_match_henderson_crm_v3(self):
        self.assertEqual(AGENCY_COLUMNS, [
            "Total", "Lead Sourcer", "Business", "Owner Full Name",
            "First", "Last", "Owner Email", "LinkedIn", "Website",
            "Phone", "Date", "X Project", "Y Detail",
        ])


if __name__ == "__main__":
    unittest.main()
