"""Compare-mode integration tests for owner_researcher._research_one.

When ``CONFIG.bbb_compare_mode`` is True and both ``bbb_direct`` and
``bbb_websearch`` are in the phase list, BOTH phases run on every kept
lead — no short-circuit — and their per-phase outputs are recorded on
``lead.bbb_direct_*`` and ``lead.bbb_websearch_*``. Direct wins on
conflict; websearch is the fallback only when direct returns nothing.
"""
import sys
import os
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agents import owner_researcher
from agents.owner_researcher import _research_one
from agents.sources.owners import bbb_direct, bbb_websearch, website, websearch
from config import CONFIG
from state import Lead


def _make_lead() -> Lead:
    return Lead(business_name="Acme Remodeling", kept=True)


_NONE_RESULT = {"owner_full_name": "", "confidence": "none", "phase": "bbb_websearch"}


class OwnerResearcherCompareModeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.phases = [bbb_direct.lookup, bbb_websearch.lookup, website.lookup]

    @patch.object(CONFIG, "bbb_compare_mode", True)
    @patch("agents.owner_researcher.website")
    @patch("agents.owner_researcher.bbb_websearch")
    @patch("agents.owner_researcher.bbb_direct")
    def test_compare_mode_both_phases_run_direct_hits(
        self, mock_direct, mock_websearch, mock_website
    ) -> None:
        mock_direct.lookup.return_value = {
            "owner_full_name": "Alice Direct",
            "confidence": "high",
            "phase": "bbb_direct",
            "source_url": "https://bbb.org/x",
        }
        mock_direct.lookup.__module__ = "agents.sources.owners.bbb_direct"
        mock_websearch.lookup.return_value = {
            "owner_full_name": "",
            "confidence": "none",
            "phase": "bbb_websearch",
        }
        mock_websearch.lookup.__module__ = "agents.sources.owners.bbb_websearch"
        phases = [mock_direct.lookup, mock_websearch.lookup, mock_website.lookup]

        lead = _make_lead()
        result = _research_one(lead, "Orlando", "FL", "key", phases)

        self.assertEqual(lead.bbb_direct_name, "Alice Direct")
        self.assertEqual(lead.bbb_direct_url, "https://bbb.org/x")
        self.assertEqual(lead.bbb_websearch_name, "")
        self.assertEqual(result["owner_full_name"], "Alice Direct")
        mock_direct.lookup.assert_called_once()
        mock_websearch.lookup.assert_called_once()

    @patch.object(CONFIG, "bbb_compare_mode", True)
    @patch("agents.owner_researcher.website")
    @patch("agents.owner_researcher.bbb_websearch")
    @patch("agents.owner_researcher.bbb_direct")
    def test_compare_mode_direct_misses_websearch_hits(
        self, mock_direct, mock_websearch, mock_website
    ) -> None:
        mock_direct.lookup.return_value = {
            "owner_full_name": "",
            "confidence": "none",
            "phase": "bbb_direct",
        }
        mock_direct.lookup.__module__ = "agents.sources.owners.bbb_direct"
        mock_websearch.lookup.return_value = {
            "owner_full_name": "Bob Websearch",
            "confidence": "high",
            "phase": "bbb_websearch",
            "source_url": "https://bbb.org/y",
        }
        mock_websearch.lookup.__module__ = "agents.sources.owners.bbb_websearch"
        phases = [mock_direct.lookup, mock_websearch.lookup, mock_website.lookup]

        lead = _make_lead()
        result = _research_one(lead, "Orlando", "FL", "key", phases)

        self.assertEqual(lead.bbb_direct_name, "")
        self.assertEqual(lead.bbb_websearch_name, "Bob Websearch")
        self.assertEqual(result["owner_full_name"], "Bob Websearch")
        mock_direct.lookup.assert_called_once()
        mock_websearch.lookup.assert_called_once()

    @patch.object(CONFIG, "bbb_compare_mode", True)
    @patch("agents.owner_researcher.website")
    @patch("agents.owner_researcher.bbb_websearch")
    @patch("agents.owner_researcher.bbb_direct")
    def test_compare_mode_different_names_sets_conflict_direct_wins(
        self, mock_direct, mock_websearch, mock_website
    ) -> None:
        mock_direct.lookup.return_value = {
            "owner_full_name": "Alice Direct",
            "confidence": "high",
            "phase": "bbb_direct",
            "source_url": "https://bbb.org/x",
        }
        mock_direct.lookup.__module__ = "agents.sources.owners.bbb_direct"
        mock_websearch.lookup.return_value = {
            "owner_full_name": "Bob Websearch",
            "confidence": "high",
            "phase": "bbb_websearch",
            "source_url": "https://bbb.org/y",
        }
        mock_websearch.lookup.__module__ = "agents.sources.owners.bbb_websearch"
        phases = [mock_direct.lookup, mock_websearch.lookup, mock_website.lookup]

        lead = _make_lead()
        result = _research_one(lead, "Orlando", "FL", "key", phases)

        self.assertTrue(lead.bbb_conflict)
        self.assertEqual(lead.bbb_direct_name, "Alice Direct")
        self.assertEqual(lead.bbb_websearch_name, "Bob Websearch")
        self.assertEqual(result["owner_full_name"], "Alice Direct")

    @patch.object(CONFIG, "bbb_compare_mode", True)
    @patch("agents.owner_researcher.website")
    @patch("agents.owner_researcher.bbb_websearch")
    @patch("agents.owner_researcher.bbb_direct")
    def test_compare_mode_both_miss_falls_through_to_website(
        self, mock_direct, mock_websearch, mock_website
    ) -> None:
        mock_direct.lookup.return_value = {"owner_full_name": "", "confidence": "none"}
        mock_direct.lookup.__module__ = "agents.sources.owners.bbb_direct"
        mock_websearch.lookup.return_value = {"owner_full_name": "", "confidence": "none"}
        mock_websearch.lookup.__module__ = "agents.sources.owners.bbb_websearch"
        mock_website.lookup.return_value = {
            "owner_full_name": "Carol Web",
            "confidence": "high",
            "phase": "website",
        }
        mock_website.lookup.__module__ = "agents.sources.owners.website"
        phases = [mock_direct.lookup, mock_websearch.lookup, mock_website.lookup]

        lead = _make_lead()
        result = _research_one(lead, "Orlando", "FL", "key", phases)

        self.assertEqual(result["owner_full_name"], "Carol Web")
        mock_website.lookup.assert_called_once()

    @patch.object(CONFIG, "bbb_compare_mode", False)
    @patch("agents.owner_researcher.website")
    @patch("agents.owner_researcher.bbb_websearch")
    @patch("agents.owner_researcher.bbb_direct")
    def test_compare_mode_off_only_direct_runs(
        self, mock_direct, mock_websearch, mock_website
    ) -> None:
        mock_direct.lookup.return_value = {
            "owner_full_name": "Alice Direct",
            "confidence": "high",
            "phase": "bbb_direct",
            "source_url": "https://bbb.org/x",
        }
        mock_direct.lookup.__module__ = "agents.sources.owners.bbb_direct"
        mock_websearch.lookup.__module__ = "agents.sources.owners.bbb_websearch"
        phases = [mock_direct.lookup, mock_websearch.lookup, mock_website.lookup]

        lead = _make_lead()
        result = _research_one(lead, "Orlando", "FL", "key", phases)

        self.assertEqual(result["owner_full_name"], "Alice Direct")
        mock_direct.lookup.assert_called_once()
        mock_websearch.lookup.assert_not_called()


if __name__ == "__main__":
    unittest.main()
