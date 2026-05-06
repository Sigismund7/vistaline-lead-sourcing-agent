"""Unit tests for _normalise_domain — the key to matching enriched CSV rows to leads."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))


def _normalise_domain(raw: str) -> str:
    """Strip protocol, www., and trailing slashes. Lowercase. Copy of api/main.py helper."""
    d = (raw or "").strip().lower()
    for prefix in ("https://", "http://"):
        if d.startswith(prefix):
            d = d[len(prefix):]
    if d.startswith("www."):
        d = d[4:]
    return d.rstrip("/")


cases = [
    ("andrewroby.com",           "andrewroby.com"),
    ("www.andrewroby.com",       "andrewroby.com"),
    ("https://andrewroby.com",   "andrewroby.com"),
    ("https://www.andrewroby.com/", "andrewroby.com"),
    ("ANDREWROBY.COM",           "andrewroby.com"),
    ("",                         ""),
]

for raw, expected in cases:
    result = _normalise_domain(raw)
    assert result == expected, f"_normalise_domain({raw!r}) = {result!r}, want {expected!r}"

print("OK — all domain normalisation cases pass")
