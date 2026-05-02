"""Tests for agents.sources.azure_maps.source_leads.

Adapter is a pure function: client + params in, normalized list of dicts out.
No CampaignState, no live HTTP. The Azure Maps client itself is mocked here —
its own behaviour is exercised in test_azure_maps_client.py.
"""
from __future__ import annotations

import unittest
from unittest.mock import MagicMock

from agents.sources import azure_maps as adapter


def _poi(
    poi_id: str,
    name: str = "Foo Remodeling",
    phone: str = "407-555-0100",
    website: str = "https://foo.com",
    address: str = "123 Main St, Orlando, FL",
) -> dict:
    """Shape mirrors what Azure Maps Search POI actually returns at top level."""
    return {
        "id": poi_id,
        "poi": {
            "name": name,
            "phone": phone,
            "url": website,
            "categorySet": [{"id": 7320}],
        },
        "address": {"freeformAddress": address},
        "position": {"lat": 28.5, "lon": -81.3},
    }


class SourceLeadsTest(unittest.TestCase):
    def setUp(self):
        self.client = MagicMock()
        self.client.geocode.return_value = (28.5383, -81.3792)
        # Default: every search call returns the same single POI so tests
        # that don't override see a known-good signal.
        self.client.search_poi.return_value = [_poi("p-default")]

    def test_source_leads_returns_normalized_dicts(self):
        self.client.search_poi.side_effect = [
            [_poi("p1", name="A"), _poi("p2", name="B"), _poi("p3", name="C")],
        ]
        results = adapter.source_leads(
            self.client, state="FL", city="Orlando",
            niche="kitchen remodelers", count=10,
        )
        self.assertEqual(len(results), 3)
        expected_keys = {
            "source", "source_id", "business_name", "address",
            "phone", "website", "lat", "lon", "raw",
        }
        for r in results:
            self.assertEqual(set(r.keys()), expected_keys)
            self.assertEqual(r["source"], "azure_maps")

    def test_source_leads_deduplicates_by_poi_id(self):
        # Same id repeated across keyword rotations should collapse to one.
        self.client.search_poi.side_effect = [
            [_poi("dup", name="X1"), _poi("uniq1", name="Y")],
            [_poi("dup", name="X2"), _poi("uniq2", name="Z")],
            [_poi("dup", name="X3")],
        ]
        results = adapter.source_leads(
            self.client, state="FL", city="Orlando",
            niche="kitchen remodelers", count=10,
        )
        ids = [r["source_id"] for r in results]
        self.assertEqual(sorted(ids), ["dup", "uniq1", "uniq2"])

    def test_source_leads_stops_at_count(self):
        big_batch = [_poi(f"p{i}") for i in range(100)]
        self.client.search_poi.return_value = big_batch
        results = adapter.source_leads(
            self.client, state="FL", city="Orlando",
            niche="kitchen remodelers", count=7,
        )
        self.assertEqual(len(results), 7)

    def test_source_leads_geocodes_city_state(self):
        adapter.source_leads(
            self.client, state="FL", city="Orlando",
            niche="kitchen remodelers", count=1,
        )
        self.client.geocode.assert_called_once()
        call_arg = self.client.geocode.call_args[0][0]
        # Must include both city and state — exact format ("Orlando, FL")
        # is the convention used by Azure free-form geocoder.
        self.assertIn("Orlando", call_arg)
        self.assertIn("FL", call_arg)

    def test_source_leads_returns_empty_list_when_geocode_fails(self):
        self.client.geocode.return_value = None
        results = adapter.source_leads(
            self.client, state="FL", city="Nowhereville",
            niche="kitchen remodelers", count=10,
        )
        self.assertEqual(results, [])
        self.client.search_poi.assert_not_called()

    def test_source_leads_rotates_keywords(self):
        # Need >1 call to demonstrate rotation. Each keyword returns one POI
        # so we burn through several keywords before reaching count.
        self.client.search_poi.side_effect = [
            [_poi("p1")], [_poi("p2")], [_poi("p3")],
        ]
        adapter.source_leads(
            self.client, state="FL", city="Orlando",
            niche="kitchen remodelers", count=10,
        )
        queries_used = [
            call.kwargs.get("query") or (call.args[0] if call.args else None)
            for call in self.client.search_poi.call_args_list
        ]
        # Mitigation 11: pattern diversity — at least 2 distinct queries.
        self.assertGreaterEqual(len(set(queries_used)), 2)


if __name__ == "__main__":
    unittest.main()
