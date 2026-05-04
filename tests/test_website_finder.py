"""Tests for agents.website_finder.find_website.

All HTTP traffic is mocked — both the HEAD checks for the pattern-guess
stage and the BraveSearchClient for the fallback stage. No live calls.
"""
from __future__ import annotations

import unittest
from unittest.mock import MagicMock

import requests

from agents import website_finder
import tools


def _head_resp(
    *, status_code: int = 200, url: str | None = None, content_length: str | None = "4096"
) -> MagicMock:
    """Build a fake HEAD response."""
    r = MagicMock(spec=requests.Response)
    r.status_code = status_code
    r.url = url or "https://example.com/"
    r.headers = {}
    if content_length is not None:
        r.headers["Content-Length"] = content_length
    return r


class FindWebsitePatternGuessTest(unittest.TestCase):
    def test_find_website_pattern_guess_hit(self):
        session = MagicMock(spec=requests.Session)
        # First candidate (slug.com) succeeds.
        session.head.return_value = _head_resp(
            status_code=200, url="https://acmerenovations.com/"
        )
        brave = MagicMock(spec=tools.BraveSearchClient)
        url = website_finder.find_website(
            "ACME Renovations", "Orlando", "FL",
            brave_client=brave, http_session=session,
        )
        self.assertEqual(url, "https://acmerenovations.com")
        brave.search_web.assert_not_called()

    def test_find_website_slugify_strips_business_suffixes(self):
        session = MagicMock(spec=requests.Session)
        captured_urls: list[str] = []

        def fake_head(url, **kwargs):
            captured_urls.append(url)
            return _head_resp(status_code=200, url=url + "/")

        session.head.side_effect = fake_head
        website_finder.find_website(
            "ABC Renovations LLC", "Orlando", "FL",
            brave_client=None, http_session=session,
        )
        # The first attempted candidate must be the suffix-stripped slug.
        self.assertTrue(captured_urls, "no HEAD call was made")
        self.assertIn("abcrenovations.com", captured_urls[0])
        self.assertNotIn("llc", captured_urls[0].lower())

    def test_slugify_strips_non_ascii(self):
        """_slugify strips non-ASCII characters, treating them as separators.

        Documented behavior — most contractor sites use ASCII domains anyway.
        Pinning current output so a future change to support unicode doesn't
        accidentally regress this. Change deliberately if you want to keep
        the unicode characters.
        """
        from agents.website_finder import _slugify
        # "Café" -> "caf" (é stripped, becomes separator). "Renovações" ->
        # "renovaes" (ç and õ stripped). Concatenated tokens: "cafrenovaes".
        self.assertEqual(_slugify("Café Renovações"), "cafrenovaes")
        # "Naïve" -> "nave" (ï stripped as separator).
        self.assertEqual(_slugify("Naïve Builders"), "navebuilders")

    def test_find_website_pattern_guess_skips_parked_domains(self):
        session = MagicMock(spec=requests.Session)
        # All candidates "succeed" with 200 but tiny content (parked-page heuristic).
        session.head.return_value = _head_resp(
            status_code=200, url="https://abc.com/", content_length="200"
        )
        url = website_finder.find_website(
            "ABC Foo", "Orlando", "FL",
            brave_client=None, http_session=session,
        )
        self.assertIsNone(url)


class FindWebsiteBraveFallbackTest(unittest.TestCase):
    def setUp(self):
        self.session = MagicMock(spec=requests.Session)
        # Pattern guesses always fail at this layer.
        self.session.head.side_effect = requests.ConnectionError("nope")
        self.brave = MagicMock(spec=tools.BraveSearchClient)

    def test_find_website_pattern_guess_miss_falls_through_to_brave(self):
        self.brave.search_web.return_value = [
            {"title": "ACME", "url": "https://realacmesite.com/about"}
        ]
        # Brave-result HEAD must validate; reset side_effect for that one URL.
        def head_router(url, **kwargs):
            if "realacmesite.com" in url:
                return _head_resp(status_code=200, url="https://realacmesite.com/")
            raise requests.ConnectionError("nope")
        self.session.head.side_effect = head_router

        url = website_finder.find_website(
            "ACME Inc", "Orlando", "FL",
            brave_client=self.brave, http_session=self.session,
        )
        self.brave.search_web.assert_called_once()
        self.assertIsNotNone(url)
        self.assertIn("realacmesite.com", url)

    def test_find_website_returns_none_when_brave_returns_no_results(self):
        self.brave.search_web.return_value = []
        url = website_finder.find_website(
            "ACME", "Orlando", "FL",
            brave_client=self.brave, http_session=self.session,
        )
        self.assertIsNone(url)

    def test_find_website_skips_directory_urls_from_brave(self):
        # First two are directories; third is real.
        self.brave.search_web.return_value = [
            {"title": "Yelp", "url": "https://www.yelp.com/biz/acme"},
            {"title": "BBB", "url": "https://www.bbb.org/profile/acme"},
            {"title": "Real", "url": "https://acmecontractors.com/"},
        ]
        def head_router(url, **kwargs):
            if "acmecontractors.com" in url:
                return _head_resp(status_code=200, url="https://acmecontractors.com/")
            raise requests.ConnectionError("nope")
        self.session.head.side_effect = head_router

        url = website_finder.find_website(
            "ACME", "Orlando", "FL",
            brave_client=self.brave, http_session=self.session,
        )
        self.assertEqual(url, "https://acmecontractors.com/")

    def test_find_website_returns_none_when_no_brave_client_and_pattern_miss(self):
        url = website_finder.find_website(
            "Nonexistent Co", "Orlando", "FL",
            brave_client=None, http_session=self.session,
        )
        self.assertIsNone(url)

    def test_find_website_handles_brave_budget_exceeded_gracefully(self):
        self.brave.search_web.side_effect = tools.BraveBudgetExceededError(
            "monthly cap reached"
        )
        # Should not crash; should return None.
        url = website_finder.find_website(
            "ACME", "Orlando", "FL",
            brave_client=self.brave, http_session=self.session,
        )
        self.assertIsNone(url)


class DirectoryBlocklistTest(unittest.TestCase):
    def test_prnewswire_rejected_as_directory(self):
        """prnewswire.com is a press-release host, not a business site."""
        session = MagicMock(spec=requests.Session)
        brave = MagicMock(spec=tools.BraveSearchClient)
        # Use a business name that won't match typical pattern guesses.
        brave.search_web.return_value = [
            {"title": "Best Renovations Wins Award",
             "url": "https://www.prnewswire.com/news-releases/best-renovations-wins-123"},
            {"title": "Real Site", "url": "https://bestrenovationsinc.com/"},
        ]

        def head_router(url, **kwargs):
            # Pattern-guess candidates all fail. Both Brave results have valid
            # HEAD responses; directory blocklist should filter out prnewswire,
            # allowing the real site to win.
            if "bestrenovationsinc.com" in url:
                return _head_resp(status_code=200, url="https://bestrenovationsinc.com/")
            if "prnewswire.com" in url:
                return _head_resp(status_code=200, url="https://www.prnewswire.com/news-releases/best-renovations-wins-123")
            raise requests.ConnectionError("nope")

        session.head.side_effect = head_router
        url = website_finder.find_website(
            "Best Renovations Inc", "Tampa", "FL",
            brave_client=brave, http_session=session,
        )
        # prnewswire must be skipped; real site must win.
        self.assertEqual(url, "https://bestrenovationsinc.com/")


if __name__ == "__main__":
    unittest.main()
