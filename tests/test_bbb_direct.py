"""Unit tests for agents.sources.owners.bbb_direct.

External calls (BBB search HTTP, ScraperAPI profile fetch) are mocked.
Real BBB fixture HTML lives in tests/fixtures/bbb/ and is loaded once.
"""
from __future__ import annotations

import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import requests

from agents.sources.owners import bbb_direct
from state import Lead


_FIXTURES = Path(__file__).parent / "fixtures" / "bbb"
_SEARCH_HTML_JACKSON = (_FIXTURES / "search_jackson_construction.html").read_text()
_SEARCH_HTML_NORESULTS = (_FIXTURES / "search_no_results.html").read_text()
_PROFILE_HTML_JACKSON = (_FIXTURES / "profile_jackson_construction.html").read_text()


def _mock_response(text: str, status: int = 200) -> MagicMock:
    """Build a stand-in for requests.Response with .text and .status_code."""
    resp = MagicMock()
    resp.text = text
    resp.status_code = status
    return resp


class BBBDirectTests(unittest.TestCase):
    # ---- normalization (3) ----

    def test_normalize_strips_llc_suffix(self) -> None:
        self.assertEqual(
            bbb_direct._normalize_candidate_name("Jackson Construction, LLC"),
            "Jackson Construction",
        )

    def test_normalize_strips_dba_suffix(self) -> None:
        # The DBA-pattern matches ", DBA <text>" to end-of-string. CamelCase
        # split runs first ("FooCorp" -> "Foo Corp"), then suffix-strip
        # removes the ", DBA Bar Services" tail.
        comma_form = bbb_direct._normalize_candidate_name("Foo Inc, DBA Bar Services")
        self.assertEqual(comma_form, "Foo Inc")
        # Without a preceding comma the regex does not fire — documents behavior.
        no_comma = bbb_direct._normalize_candidate_name("Foo Inc DBA Bar Services")
        self.assertEqual(no_comma, "Foo Inc DBA Bar Services")

    def test_normalize_camelcase_split(self) -> None:
        self.assertEqual(
            bbb_direct._normalize_candidate_name("JacksonConstruction"),
            "Jackson Construction",
        )

    # ---- fuzzy match (3) ----

    def test_fuzzy_match_picks_highest_above_80(self) -> None:
        candidates = [
            ("Jackson Construction LLC", "/url1"),
            ("Lee Jackson Construction", "/url2"),
        ]
        self.assertEqual(
            bbb_direct._fuzzy_match_best(candidates, "Jackson Construction"),
            "/url1",
        )

    def test_fuzzy_match_returns_none_when_all_below_80(self) -> None:
        candidates = [("Completely Different Co", "/url")]
        self.assertIsNone(
            bbb_direct._fuzzy_match_best(candidates, "Jackson Construction")
        )

    def test_fuzzy_match_tiebreak_first_wins(self) -> None:
        # Identical candidate names produce identical scores → first wins
        # because the loop uses strict > on score.
        candidates = [
            ("Jackson Construction", "/first"),
            ("Jackson Construction", "/second"),
        ]
        self.assertEqual(
            bbb_direct._fuzzy_match_best(candidates, "Jackson Construction"),
            "/first",
        )

    # ---- search parser (3) ----

    @patch("agents.sources.owners.bbb_direct.requests.get")
    def test_search_parses_jackson_fixture(self, mock_get: MagicMock) -> None:
        mock_get.return_value = _mock_response(_SEARCH_HTML_JACKSON)
        candidates = bbb_direct._search_bbb("Jackson Construction", "Charleston", "SC")
        self.assertGreater(len(candidates), 0)
        names = [name for name, _ in candidates]
        self.assertTrue(
            any("Jackson Construction" in n for n in names),
            f"expected a Jackson Construction candidate in {names!r}",
        )

    @patch("agents.sources.owners.bbb_direct.requests.get")
    def test_search_no_results_returns_empty(self, mock_get: MagicMock) -> None:
        mock_get.return_value = _mock_response(_SEARCH_HTML_NORESULTS)
        candidates = bbb_direct._search_bbb("Nothing Matches", "Nowhere", "ZZ")
        self.assertEqual(candidates, [])

    @patch("agents.sources.owners.bbb_direct.requests.get")
    def test_search_network_error_returns_empty(self, mock_get: MagicMock) -> None:
        mock_get.side_effect = requests.Timeout("connect timed out")
        self.assertEqual(
            bbb_direct._search_bbb("Whatever", "City", "ST"),
            [],
        )

    # ---- JSON-LD parser (2) ----

    def test_jsonld_extracts_owner_from_jackson_fixture(self) -> None:
        # Fixture has Lion Jackson (Owner) and Cleveland Ryan Jackson
        # (License Holder). Owner wins per _ROLE_PRIORITY.
        self.assertEqual(
            bbb_direct._parse_owner_from_jsonld(_PROFILE_HTML_JACKSON),
            "Lion Jackson",
        )

    def test_jsonld_returns_none_when_no_person(self) -> None:
        html = (
            '<html><head>'
            '<script type="application/ld+json">'
            '{"@type":"Organization","name":"X"}'
            '</script></head><body></body></html>'
        )
        self.assertIsNone(bbb_direct._parse_owner_from_jsonld(html))

    # ---- DOM fallback parser (2) ----

    def test_dom_fallback_extracts_owner_from_jackson_fixture(self) -> None:
        # Fixture DOM block has "Mr. Cleveland Ryan Jackson, License Holder"
        # and "Mr. Lion Jackson, Owner". Owner role wins.
        self.assertEqual(
            bbb_direct._parse_owner_from_html(_PROFILE_HTML_JACKSON),
            "Lion Jackson",
        )

    def test_dom_fallback_strips_honorifics(self) -> None:
        html = (
            "<html><body><dl>"
            "<dt>Principal Contacts</dt>"
            "<dd>Dr. Sarah Smith, Owner</dd>"
            "</dl></body></html>"
        )
        self.assertEqual(bbb_direct._parse_owner_from_html(html), "Sarah Smith")

    # ---- lookup() integration (1) ----

    @patch("agents.sources.owners.bbb_direct.requests.get")
    @patch("agents.sources.owners.bbb_direct.build_scraperapi_client")
    def test_lookup_no_scraperapi_key_returns_none(
        self,
        mock_build: MagicMock,
        mock_get: MagicMock,
    ) -> None:
        mock_get.return_value = _mock_response(_SEARCH_HTML_JACKSON)
        mock_build.return_value = None  # simulates missing SCRAPERAPI_KEY
        lead = Lead(business_name="Jackson Construction")
        result = bbb_direct.lookup(lead, "Charleston", "SC", anthropic_key="")
        self.assertEqual(result["owner_full_name"], "")
        self.assertEqual(result["confidence"], "none")
        self.assertEqual(result["phase"], "bbb_direct")


if __name__ == "__main__":
    unittest.main()
