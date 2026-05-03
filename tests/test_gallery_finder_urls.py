"""Pure-function tests for the gallery candidate URL generator. No network."""
from __future__ import annotations
import unittest

from agents.gallery_finder import gallery_candidates


class GalleryCandidatesTest(unittest.TestCase):
    def test_generates_six_canonical_paths_in_order(self):
        urls = gallery_candidates("https://example.com")
        self.assertEqual(urls, [
            "https://example.com/gallery",
            "https://example.com/portfolio",
            "https://example.com/projects",
            "https://example.com/our-work",
            "https://example.com/work",
            "https://example.com",
        ])

    def test_strips_trailing_slash(self):
        urls = gallery_candidates("https://example.com/")
        self.assertEqual(urls[0], "https://example.com/gallery")

    def test_handles_subpath_root(self):
        urls = gallery_candidates("https://acme.com/home")
        self.assertEqual(urls[0], "https://acme.com/home/gallery")

    def test_skips_non_http_url(self):
        self.assertEqual(gallery_candidates(""), [])
        self.assertEqual(gallery_candidates("not a url"), [])
        self.assertEqual(gallery_candidates("mailto:test@x.com"), [])


if __name__ == "__main__":
    unittest.main()
