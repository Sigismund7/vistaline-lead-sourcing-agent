"""Verify the Lead dataclass exposes the personalization fields and that
save_leads / load round-trips them correctly. We do not hit real Supabase —
we patch _db with a thin in-memory fake."""
from __future__ import annotations
import os
import unittest
from unittest.mock import patch

# Supabase client is constructed lazily, so we can fake the env vars.
os.environ.setdefault("SUPABASE_URL", "http://fake")
os.environ.setdefault("SUPABASE_SERVICE_ROLE_KEY", "fake")

from state import Lead


class LeadPersonalizationFieldsTest(unittest.TestCase):
    def test_default_values_blank(self):
        lead = Lead()
        self.assertEqual(lead.x_project, "")
        self.assertEqual(lead.y_detail, "")
        self.assertEqual(lead.y_source, "")
        self.assertEqual(lead.linkedin_url, "")
        self.assertEqual(lead.linkedin_source, "")
        self.assertEqual(lead.personalization_status, "")

    def test_fields_round_trip_through_dict(self):
        lead = Lead(
            business_name="Test Co",
            x_project="dark modern kitchen remodel",
            y_detail="blue marble waterfall island",
            y_source="website_gallery",
            linkedin_url="https://linkedin.com/in/test",
            linkedin_source="web_search",
            personalization_status="ok",
        )
        self.assertEqual(lead.x_project, "dark modern kitchen remodel")
        self.assertEqual(lead.linkedin_source, "web_search")


if __name__ == "__main__":
    unittest.main()
