"""Gallery finder — locates a contractor's project gallery page and captures
a full-page screenshot for the personalizer agent.

The pure functions in this module (gallery_candidates) are unit-testable
without network access. The Playwright-driven find_and_screenshot is
integration-tested via a smoke run, per CLAUDE.md "test against real APIs".
"""
from __future__ import annotations
from urllib.parse import urlparse
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout, Error


# Heuristic: a gallery page must have at least this many <img> tags
# whose rendered area is > 50_000 px². This rules out one-pager landing
# sites where the only images are the logo + a hero photo.
_MIN_GALLERY_IMAGES = 4


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


def find_and_screenshot(
    website: str, *, timeout_s: int = 25
) -> tuple[bytes | None, str]:
    """Try gallery candidates in order; return (image_bytes, source_url) of the
    first one that looks like a real project gallery, else (None, "").

    'Looks like a gallery' = the page resolves with HTTP 200 AND has >= 4
    rendered images larger than 50_000 px². Falls through to the homepage.

    External errors (timeouts, navigation failures, DNS) are caught and
    logged; we move on to the next candidate. Unexpected exceptions
    propagate (CLAUDE.md: our bugs should crash).
    """
    candidates = gallery_candidates(website)
    if not candidates:
        return None, ""

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        try:
            context = browser.new_context(
                viewport={"width": 1280, "height": 900},
                user_agent=(
                    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_0) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/124.0 Safari/537.36"
                ),
            )
            page = context.new_page()
            page.set_default_timeout(timeout_s * 1000)

            for url in candidates:
                try:
                    resp = page.goto(url, wait_until="domcontentloaded")
                    if not resp or not resp.ok:
                        continue
                    # Lazy-load galleries need a scroll pass before screenshot.
                    page.evaluate(
                        "() => new Promise(r => { "
                        "  let y = 0; "
                        "  const id = setInterval(() => { "
                        "    window.scrollBy(0, 600); "
                        "    y += 600; "
                        "    if (y >= document.body.scrollHeight) { "
                        "      clearInterval(id); r(); "
                        "    } "
                        "  }, 200); "
                        "})"
                    )
                    page.wait_for_timeout(800)  # let images settle
                    big_imgs = page.evaluate(
                        "() => Array.from(document.images)"
                        ".filter(i => i.naturalWidth * i.naturalHeight > 50000)"
                        ".length"
                    )
                    if big_imgs < _MIN_GALLERY_IMAGES:
                        continue
                    png = page.screenshot(full_page=True, type="png")
                    return png, url
                except PlaywrightTimeout as e:
                    print(f"[gallery_finder] WARN: timeout on {url}: {e}")
                    continue
                except Error as e:
                    # Navigation failures, page crashes, network aborts — keep walking.
                    print(f"[gallery_finder] WARN: {url}: {type(e).__name__} {e}")
                    continue
        finally:
            browser.close()

    return None, ""
