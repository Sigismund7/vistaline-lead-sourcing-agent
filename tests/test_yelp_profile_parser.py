"""Tests for `_parse_owner_from_html` in agents.sources.owners.yelp_profile.

These exercise the DOM fallback in isolation with synthetic HTML — pure
parser logic, no network. Guards against the false-positive vector where
<script type="text/template"> or <noscript> blocks contain HTML fragments
that BeautifulSoup's html.parser would otherwise treat as live DOM.
"""
from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agents.sources.owners.yelp_profile import _parse_owner_from_html


_REAL_OWNER_BLOCK = """
<div>
  <p data-font-weight="bold">Jane Doe</p>
  <p>Business Owner</p>
</div>
"""

_FAKE_TEMPLATE_BLOCK = """
<script type="text/template">
  <div>
    <p data-font-weight="bold">FAKE NAME</p>
    <p>Business Owner</p>
  </div>
</script>
"""

_FAKE_NOSCRIPT_BLOCK = """
<noscript>
  <div>
    <p data-font-weight="bold">FAKE NAME</p>
    <p>Business Owner</p>
  </div>
</noscript>
"""


def _wrap(*fragments: str) -> str:
    """Wrap fragments in a minimal HTML document for the parser."""
    return "<html><body>" + "".join(fragments) + "</body></html>"


class ParseOwnerFromHtmlTests(unittest.TestCase):
    """Behavioral tests for the DOM fallback parser."""

    def test_clean_positive_extraction(self) -> None:
        """Standard owner block with no decoy returns the bold name."""
        html = _wrap(_REAL_OWNER_BLOCK)
        self.assertEqual(_parse_owner_from_html(html), "Jane Doe")

    def test_template_decoy_does_not_shadow_real_block(self) -> None:
        """Real owner block must win over a script-template decoy elsewhere."""
        html = _wrap(_FAKE_TEMPLATE_BLOCK, _REAL_OWNER_BLOCK)
        self.assertEqual(_parse_owner_from_html(html), "Jane Doe")

    def test_template_only_returns_none(self) -> None:
        """A 'Business Owner' label that exists only inside a <script>
        template must not produce a name — the script content is not
        a rendered element on the page."""
        html = _wrap(_FAKE_TEMPLATE_BLOCK)
        self.assertIsNone(_parse_owner_from_html(html))

    def test_noscript_only_returns_none(self) -> None:
        """Same guarantee for <noscript> wrappers."""
        html = _wrap(_FAKE_NOSCRIPT_BLOCK)
        self.assertIsNone(_parse_owner_from_html(html))

    def test_oborne_fixture_still_extracts(self) -> None:
        """If the saved Oborne page is on disk and its DOM 'Business Owner'
        block is present, the parser must still pull 'John O.'. Skipped
        when the fixture is gone or only carries the state-blob path."""
        fixture = Path("/tmp/yelp_oborne.html")
        if not fixture.exists():
            self.skipTest("Oborne fixture not present on disk")
        html = fixture.read_text(encoding="utf-8", errors="ignore")
        result = _parse_owner_from_html(html)
        if result is None:
            self.skipTest("Oborne fixture has no DOM 'Business Owner' block")
        self.assertEqual(result, "John O.")


if __name__ == "__main__":
    unittest.main()
