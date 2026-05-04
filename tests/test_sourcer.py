"""Tests for agents.sourcer (Cycle 4 router).

The router calls Azure Maps + Yelp Fusion in parallel via ThreadPoolExecutor,
dedupes cross-source via rapidfuzz, then sequentially fills missing websites
via website_finder. All external surfaces (source adapters, website_finder,
client constructors) are mocked.
"""
from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from agents import sourcer
from state import CampaignState


def _normalized(
    *,
    source: str,
    source_id: str,
    business_name: str,
    address: str = "123 Main St, Orlando, FL",
    phone: str = "407-555-0100",
    website: str = "",
    lat: float = 28.5,
    lon: float = -81.3,
) -> dict:
    """Build a normalized 9-key source-adapter dict."""
    return {
        "source": source,
        "source_id": source_id,
        "business_name": business_name,
        "address": address,
        "phone": phone,
        "website": website,
        "lat": lat,
        "lon": lon,
        "raw": {"id": source_id},
    }


def _make_state(target: int = 50, niche: str = "kitchen remodeling") -> CampaignState:
    state = CampaignState.new()
    state.city = "Orlando"
    state.state_abbr = "FL"
    state.niche = niche
    state.target_count = target
    return state


class SourcerRunTest(unittest.TestCase):
    """End-to-end run() behavior with all external surfaces mocked."""

    def setUp(self) -> None:
        self.state = _make_state()
        # Patch client constructors so no real .env keys / HTTP fire.
        self._patches = [
            patch("agents.sourcer.AzureMapsClient", MagicMock()),
            patch("agents.sourcer.YelpFusionClient", MagicMock()),
            patch("agents.sourcer.BraveSearchClient", MagicMock()),
        ]
        for p in self._patches:
            p.start()

    def tearDown(self) -> None:
        for p in self._patches:
            p.stop()

    def test_run_returns_early_when_already_done(self):
        """is_done('sourcer') short-circuits — adapters never get called."""
        self.state.mark_done("sourcer")
        with patch("agents.sourcer.azure_source.source_leads") as mock_az, \
             patch("agents.sourcer.yelp_source.source_leads") as mock_yp, \
             patch("agents.sourcer.find_website") as mock_fw:
            sourcer.run(self.state)
            mock_az.assert_not_called()
            mock_yp.assert_not_called()
            mock_fw.assert_not_called()

    def test_run_calls_both_source_adapters_in_parallel(self):
        """Fanout calls both Azure and Yelp adapters."""
        with patch("agents.sourcer.azure_source.source_leads") as mock_az, \
             patch("agents.sourcer.yelp_source.source_leads") as mock_yp, \
             patch("agents.sourcer.find_website", return_value=None):
            mock_az.return_value = [
                _normalized(source="azure_maps", source_id="a1",
                            business_name="Acme Kitchens",
                            website="https://acme.com"),
            ]
            mock_yp.return_value = [
                _normalized(source="yelp_fusion", source_id="y1",
                            business_name="Beta Bath",
                            address="999 Other Rd, Orlando, FL"),
            ]
            sourcer.run(self.state)
            mock_az.assert_called_once()
            mock_yp.assert_called_once()
            self.assertEqual(len(self.state.leads), 2)

    def test_run_dedupes_cross_source_via_rapidfuzz(self):
        """Same business name+address from two sources collapses to 1 lead."""
        with patch("agents.sourcer.azure_source.source_leads") as mock_az, \
             patch("agents.sourcer.yelp_source.source_leads") as mock_yp, \
             patch("agents.sourcer.find_website", return_value=None):
            mock_az.return_value = [
                _normalized(source="azure_maps", source_id="a1",
                            business_name="ABC Renovations",
                            address="100 Oak St, Orlando, FL",
                            website="https://abcreno.com"),
            ]
            mock_yp.return_value = [
                _normalized(source="yelp_fusion", source_id="y1",
                            business_name="ABC Renovations LLC",
                            address="100 Oak St, Orlando, FL"),
            ]
            sourcer.run(self.state)
            self.assertEqual(len(self.state.leads), 1)
            survivor = self.state.leads[0]
            # Azure-wins: business name and website come from Azure.
            self.assertEqual(survivor.business_name, "ABC Renovations")
            self.assertEqual(survivor.website, "https://abcreno.com")

    def test_run_keeps_unique_leads_from_both_sources(self):
        """Two non-matching leads survive both sources."""
        with patch("agents.sourcer.azure_source.source_leads") as mock_az, \
             patch("agents.sourcer.yelp_source.source_leads") as mock_yp, \
             patch("agents.sourcer.find_website", return_value=None):
            mock_az.return_value = [
                _normalized(source="azure_maps", source_id="a1",
                            business_name="Foo Inc",
                            address="1 First St, Orlando, FL",
                            website="https://foo.com"),
            ]
            mock_yp.return_value = [
                _normalized(source="yelp_fusion", source_id="y1",
                            business_name="Bar LLC",
                            address="999 Ninth Ave, Orlando, FL"),
            ]
            sourcer.run(self.state)
            self.assertEqual(len(self.state.leads), 2)
            names = sorted(l.business_name for l in self.state.leads)
            self.assertEqual(names, ["Bar LLC", "Foo Inc"])

    def test_run_invokes_website_finder_for_leads_with_empty_website(self):
        """Leads with empty website get find_website called and result populated."""
        with patch("agents.sourcer.azure_source.source_leads") as mock_az, \
             patch("agents.sourcer.yelp_source.source_leads") as mock_yp, \
             patch("agents.sourcer.find_website",
                   return_value="https://discovered.com") as mock_fw:
            mock_az.return_value = []
            mock_yp.return_value = [
                _normalized(source="yelp_fusion", source_id="y1",
                            business_name="No Website Co"),
            ]
            sourcer.run(self.state)
            self.assertEqual(len(self.state.leads), 1)
            self.assertEqual(self.state.leads[0].website, "https://discovered.com")
            self.assertEqual(self.state.leads[0].domain, "discovered.com")
            mock_fw.assert_called_once()

    def test_run_skips_website_finder_when_website_already_set(self):
        """Pre-populated website skips the find_website call entirely."""
        with patch("agents.sourcer.azure_source.source_leads") as mock_az, \
             patch("agents.sourcer.yelp_source.source_leads") as mock_yp, \
             patch("agents.sourcer.find_website") as mock_fw:
            mock_az.return_value = [
                _normalized(source="azure_maps", source_id="a1",
                            business_name="Has Site",
                            website="https://hassite.com"),
            ]
            mock_yp.return_value = []
            sourcer.run(self.state)
            mock_fw.assert_not_called()
            self.assertEqual(self.state.leads[0].website, "https://hassite.com")

    def test_run_marks_done_after_completion(self):
        """state.is_done('sourcer') is True after a successful run."""
        with patch("agents.sourcer.azure_source.source_leads", return_value=[]), \
             patch("agents.sourcer.yelp_source.source_leads", return_value=[]), \
             patch("agents.sourcer.find_website", return_value=None):
            sourcer.run(self.state)
            self.assertTrue(self.state.is_done("sourcer"))

    def test_run_stops_at_target_count(self):
        """When adapters return more than target_count, only target_count survives."""
        self.state.target_count = 5
        # Distinct enough names+addresses that rapidfuzz won't fold them.
        unique_words = [
            "Alpha", "Bravo", "Charlie", "Delta", "Echo",
            "Foxtrot", "Golf", "Hotel", "India", "Juliet",
        ]
        many_az = [
            _normalized(source="azure_maps", source_id=f"a{i}",
                        business_name=f"{w} Kitchens",
                        address=f"{100 + i} {w} Boulevard, Orlando, FL",
                        website=f"https://{w.lower()}.com")
            for i, w in enumerate(unique_words)
        ]
        # Yelp set uses an entirely different vocabulary so no cross-source merge.
        yelp_words = [
            "Quartz", "Marble", "Granite", "Slate", "Onyx",
            "Walnut", "Cedar", "Maple", "Oak", "Pine",
        ]
        many_yp = [
            _normalized(source="yelp_fusion", source_id=f"y{i}",
                        business_name=f"{w} Renovations",
                        address=f"{500 + i} {w} Parkway, Tampa, FL")
            for i, w in enumerate(yelp_words)
        ]
        with patch("agents.sourcer.azure_source.source_leads", return_value=many_az), \
             patch("agents.sourcer.yelp_source.source_leads", return_value=many_yp), \
             patch("agents.sourcer.find_website", return_value=None):
            sourcer.run(self.state)
            self.assertEqual(len(self.state.leads), 5)

    def test_run_dedup_does_not_transitively_merge(self):
        """Single-pass dedup: if A matches B and B matches C, but A doesn't
        match C directly, A and C are NOT merged into each other.

        Documented behavior; lock it down. Verified scores at the
        CONFIG.dedup_match_threshold=85 ceiling:
          A vs B = 95 (Azure 'Foo Renovation Inc 100 Main' ~ Yelp 'Foo
            Renovation 100 Main') -> merged.
          A vs C = 71 (Azure ~ Yelp 'Foo Renovation 999 Maple') -> below
            threshold, C survives separately.
        A regression that started comparing each candidate against all
        already-merged-into survivors transitively would still pass this
        test, but a regression that started chaining matches across
        candidates would not.
        """
        with patch("agents.sourcer.azure_source.source_leads") as mock_az, \
             patch("agents.sourcer.yelp_source.source_leads") as mock_yp, \
             patch("agents.sourcer.find_website", return_value=None):
            mock_az.return_value = [
                _normalized(source="azure_maps", source_id="a1",
                            business_name="Foo Renovation Inc",
                            address="100 Main St, Orlando, FL",
                            website="https://foo.com"),
            ]
            mock_yp.return_value = [
                _normalized(source="yelp_fusion", source_id="y1",
                            business_name="Foo Renovation",
                            address="100 Main St, Orlando, FL"),
                _normalized(source="yelp_fusion", source_id="y2",
                            business_name="Foo Renovation",
                            address="999 Maple Ave, Orlando, FL"),
            ]
            sourcer.run(self.state)
            # Two survivors: the Azure+Yelp[0] merge, and Yelp[1] standalone.
            self.assertEqual(len(self.state.leads), 2)
            addresses = sorted(l.address for l in self.state.leads)
            self.assertEqual(
                addresses,
                ["100 Main St, Orlando, FL", "999 Maple Ave, Orlando, FL"],
            )

    def test_run_handles_partial_lead_dict_from_adapter(self):
        """Defensive _to_lead: if a source adapter returns a dict missing
        optional fields, the lead is constructed with empty defaults
        rather than raising KeyError.
        """
        partial = {"source": "azure_maps",
                   "business_name": "Partial Co",
                   "source_id": "p1"}
        with patch("agents.sourcer.azure_source.source_leads",
                   return_value=[partial]), \
             patch("agents.sourcer.yelp_source.source_leads", return_value=[]), \
             patch("agents.sourcer.find_website", return_value=None) as mock_fw:
            sourcer.run(self.state)
            self.assertEqual(len(self.state.leads), 1)
            lead = self.state.leads[0]
            self.assertEqual(lead.business_name, "Partial Co")
            self.assertEqual(lead.place_id, "p1")
            self.assertEqual(lead.phone, "")
            self.assertEqual(lead.website, "")
            self.assertEqual(lead.address, "")
            self.assertEqual(lead.area_code, "")
            self.assertEqual(lead.domain, "")
            # Empty website triggers the website finder.
            mock_fw.assert_called_once()

    def test_run_survives_one_source_failure(self):
        """Azure raising shouldn't crash sourcer; Yelp results still land."""
        with patch("agents.sourcer.azure_source.source_leads",
                   side_effect=RuntimeError("azure boom")), \
             patch("agents.sourcer.yelp_source.source_leads") as mock_yp, \
             patch("agents.sourcer.find_website", return_value=None):
            mock_yp.return_value = [
                _normalized(source="yelp_fusion", source_id="y1",
                            business_name="Survivor Co"),
            ]
            sourcer.run(self.state)
            self.assertEqual(len(self.state.leads), 1)
            self.assertEqual(self.state.leads[0].business_name, "Survivor Co")
            self.assertTrue(self.state.is_done("sourcer"))


class HelperTest(unittest.TestCase):
    """Pure-Python helpers stay testable without mocks."""

    def test_normalize_domain_strips_protocol_and_www(self):
        self.assertEqual(sourcer._normalize_domain("https://www.foo.com/x"), "foo.com")
        self.assertEqual(sourcer._normalize_domain("http://bar.com"), "bar.com")
        self.assertEqual(sourcer._normalize_domain(""), "")

    def test_area_code_extracts_first_three_digits(self):
        self.assertEqual(sourcer._area_code("407-555-0100"), "407")
        self.assertEqual(sourcer._area_code("+1 407 555 0100"), "407")
        self.assertEqual(sourcer._area_code("555-0100"), "")


if __name__ == "__main__":
    unittest.main()
