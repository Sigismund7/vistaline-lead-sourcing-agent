"""Tests for agents.sources.yelp_fusion.source_leads.

Adapter is a pure function: client + params in, normalized list of dicts out.
No CampaignState, no live HTTP. The Yelp client itself is mocked here — its
own behaviour is exercised in test_yelp_fusion_client.py.
"""
from __future__ import annotations

import unittest
from unittest.mock import MagicMock

from agents.sources import yelp_fusion as adapter


def _biz(
    biz_id: str,
    name: str = "Foo Remodeling",
    phone: str = "+14075550100",
    address_lines: tuple[str, ...] = ("123 Main St", "Orlando, FL 32801"),
    lat: float = 28.5,
    lon: float = -81.3,
) -> dict:
    """Shape mirrors what Yelp's Business Search returns at top level."""
    return {
        "id": biz_id,
        "name": name,
        "phone": phone,
        "display_phone": phone,
        "url": f"https://www.yelp.com/biz/{biz_id}",
        "coordinates": {"latitude": lat, "longitude": lon},
        "location": {
            "address1": address_lines[0],
            "city": "Orlando",
            "state": "FL",
            "zip_code": "32801",
            "display_address": list(address_lines),
        },
        "categories": [{"alias": "contractors", "title": "Contractors"}],
        "rating": 4.5,
        "review_count": 12,
        "is_closed": False,
    }


class SourceLeadsTest(unittest.TestCase):
    def setUp(self):
        self.client = MagicMock()
        # Default: every call returns nothing, override per test.
        self.client.search_businesses.return_value = []

    def test_source_leads_returns_normalized_dicts_with_empty_website(self):
        # First call returns 3 businesses; subsequent (term × offset) calls
        # return empty so we exit cleanly after collecting them.
        self.client.search_businesses.side_effect = [
            [_biz("y1", name="A"), _biz("y2", name="B"), _biz("y3", name="C")],
        ] + [[]] * 50

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
            self.assertEqual(r["source"], "yelp_fusion")
            # Yelp's Business Search response doesn't include the business's
            # own URL — only the Yelp page URL — so website is always empty.
            self.assertEqual(r["website"], "")

    def test_source_leads_deduplicates_by_business_id(self):
        self.client.search_businesses.side_effect = [
            [_biz("dup", name="X1"), _biz("uniq1", name="Y")],
            [_biz("dup", name="X2"), _biz("uniq2", name="Z")],
            [_biz("dup", name="X3")],
        ] + [[]] * 50

        results = adapter.source_leads(
            self.client, state="FL", city="Orlando",
            niche="kitchen remodelers", count=10,
        )
        ids = sorted(r["source_id"] for r in results)
        self.assertEqual(ids, ["dup", "uniq1", "uniq2"])

    def test_source_leads_stops_at_count(self):
        big_batch = [_biz(f"y{i}") for i in range(50)]
        self.client.search_businesses.return_value = big_batch
        results = adapter.source_leads(
            self.client, state="FL", city="Orlando",
            niche="kitchen remodelers", count=7,
        )
        self.assertEqual(len(results), 7)

    def test_source_leads_passes_categories_for_niche(self):
        self.client.search_businesses.return_value = [_biz("y1")]
        adapter.source_leads(
            self.client, state="FL", city="Orlando",
            niche="kitchen remodelers", count=1,
        )
        # Inspect the categories kwarg from the first call.
        first_call = self.client.search_businesses.call_args_list[0]
        self.assertEqual(
            first_call.kwargs["categories"],
            "contractors,kitchen_and_bath,homeservices",
        )

    def test_source_leads_paginates_with_offset(self):
        # 50 results on page 1, 50 on page 2 (same term), then everything
        # else empty. We need count > 50 to force a second page on the same
        # term.
        page1 = [_biz(f"a{i}") for i in range(50)]
        page2 = [_biz(f"b{i}") for i in range(50)]
        self.client.search_businesses.side_effect = [page1, page2] + [[]] * 50

        adapter.source_leads(
            self.client, state="FL", city="Orlando",
            niche="kitchen remodelers", count=80,
        )
        offsets_used = [
            call.kwargs.get("offset")
            for call in self.client.search_businesses.call_args_list
        ]
        # First two calls must be offset 0 then offset 50 — that's how we
        # paginate within a single term before rotating terms.
        self.assertEqual(offsets_used[0], 0)
        self.assertEqual(offsets_used[1], 50)

    def test_source_leads_rotates_terms(self):
        # One result per call so we burn through several terms before count.
        self.client.search_businesses.side_effect = [
            [_biz("y1")], [_biz("y2")], [_biz("y3")], [_biz("y4")],
        ] + [[]] * 50

        adapter.source_leads(
            self.client, state="FL", city="Orlando",
            niche="kitchen remodelers", count=10,
        )
        terms_used = [
            call.kwargs.get("term")
            for call in self.client.search_businesses.call_args_list
        ]
        # Mitigation 11: pattern diversity — at least 2 distinct terms,
        # counting None as its own value (the category-only sweep).
        self.assertGreaterEqual(len({repr(t) for t in terms_used}), 2)


if __name__ == "__main__":
    unittest.main()
