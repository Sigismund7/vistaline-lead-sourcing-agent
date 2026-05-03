"""Gallery finder — locates a contractor's project gallery page and captures
a full-page screenshot for the personalizer agent.

The pure functions in this module (gallery_candidates) are unit-testable
without network access. The Playwright-driven find_and_screenshot is
integration-tested via a smoke run, per CLAUDE.md "test against real APIs".
"""
from __future__ import annotations
from urllib.parse import urlparse


def gallery_candidates(website: str) -> list[str]:
    """Return ordered candidate URLs to try for a contractor gallery page.

    The order reflects observed frequency on small remodeler sites:
    /gallery > /portfolio > /projects > /our-work > /work > homepage.
    The homepage is included last so contractors with a gallery section
    embedded in the home page still get screenshotted.
    """
    if not website:
        return []
    # Only prepend scheme if the string already looks URL-like; bare words like
    # "not a url" must not be silently promoted to https:// URLs.
    if "://" not in website:
        return []
    parsed = urlparse(website)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        return []
    # Reject netlocs that contain spaces or other characters invalid in a host.
    if " " in parsed.netloc or not parsed.netloc.replace(".", "").replace("-", "").replace(":", "").isalnum():
        return []
    base = f"{parsed.scheme}://{parsed.netloc}{parsed.path.rstrip('/')}"
    return [
        f"{base}/gallery",
        f"{base}/portfolio",
        f"{base}/projects",
        f"{base}/our-work",
        f"{base}/work",
        base or f"{parsed.scheme}://{parsed.netloc}",
    ]
