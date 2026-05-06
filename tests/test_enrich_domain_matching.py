"""Unit tests for _normalise_domain — the key to matching enriched CSV rows to leads."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from api.main import _normalise_domain


cases = [
    ("andrewroby.com",           "andrewroby.com"),
    ("www.andrewroby.com",       "andrewroby.com"),
    ("http://andrewroby.com",    "andrewroby.com"),
    ("https://andrewroby.com",   "andrewroby.com"),
    ("https://www.andrewroby.com/", "andrewroby.com"),
    ("ANDREWROBY.COM",           "andrewroby.com"),
    ("",                         ""),
]

for raw, expected in cases:
    result = _normalise_domain(raw)
    assert result == expected, f"_normalise_domain({raw!r}) = {result!r}, want {expected!r}"

print("OK — all domain normalisation cases pass")
