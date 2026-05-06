"""Unit tests for Yelp profile page parsing helpers.

Tests use fixture HTML snippets — no network calls.
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agents.sources.owners.yelp_profile import _parse_owner_from_jsonld, _parse_owner_from_html


JSONLD_HTML = """
<html><body>
<script type="application/ld+json">
[{"@context": "https://schema.org", "@type": "LocalBusiness", "name": "ABC Bath"},
 {"@context": "https://schema.org", "@type": "Person", "name": "Manuel Hernández A.",
  "jobTitle": "Business Owner"}]
</script>
</body></html>
"""

JSONLD_HTML_NO_OWNER = """
<html><body>
<script type="application/ld+json">
{"@context": "https://schema.org", "@type": "LocalBusiness", "name": "ABC Bath"}
</script>
</body></html>
"""

HTML_PATTERN = """
<html><body>
<section>
  <h2>About the Business</h2>
  <div>
    <p>Business Owner</p>
    <p>John Smith</p>
  </div>
</section>
</body></html>
"""

HTML_NO_OWNER = """
<html><body>
<section>
  <h2>About the Business</h2>
  <p>We do great work.</p>
</section>
</body></html>
"""


def test_jsonld_extracts_owner_name():
    name = _parse_owner_from_jsonld(JSONLD_HTML)
    assert name == "Manuel Hernández A.", f"got {name!r}"


def test_jsonld_returns_none_when_no_person():
    name = _parse_owner_from_jsonld(JSONLD_HTML_NO_OWNER)
    assert name is None


def test_jsonld_returns_none_on_empty_html():
    name = _parse_owner_from_jsonld("<html></html>")
    assert name is None


def test_html_pattern_extracts_owner():
    name = _parse_owner_from_html(HTML_PATTERN)
    assert name is not None
    assert "John Smith" in name, f"got {name!r}"


def test_html_pattern_returns_none_when_no_label():
    name = _parse_owner_from_html(HTML_NO_OWNER)
    assert name is None


if __name__ == "__main__":
    test_jsonld_extracts_owner_name()
    test_jsonld_returns_none_when_no_person()
    test_jsonld_returns_none_on_empty_html()
    test_html_pattern_extracts_owner()
    test_html_pattern_returns_none_when_no_label()
    print("OK")
