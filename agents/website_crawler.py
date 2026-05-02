"""Website crawler — fetches a contractor's website pages likely to mention the owner.

Pure HTTP + BeautifulSoup. No LLM calls here. The owner_researcher
sends the extracted text to Claude separately.

Strategy:
  1. Fetch the homepage.
  2. Find <a> tags whose link text or URL path matches keywords like
     "about", "team", "meet", "owner", "founder", "staff", "leadership",
     "contact" (contact pages often have direct emails).
  3. Restrict to the same domain (no off-site links).
  4. Fetch up to MAX_PAGES candidates.
  5. Extract clean visible text + all email addresses found in the HTML.
  6. Return (url, text) pairs for Claude + a deduped list of candidate emails.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from urllib.parse import urljoin, urlparse
import re

import requests
from bs4 import BeautifulSoup


# Keywords that signal a page might contain owner info or a direct email.
# Matched against both visible link text AND the URL path component.
OWNER_PAGE_KEYWORDS = [
    "about", "team", "meet", "owner", "founder", "staff", "leadership",
    "who-we-are", "who_we_are", "whoweare", "our-story", "ourstory",
    "our-team", "ourteam", "history", "company",
    "contact",  # often has direct mailto: + sometimes owner's name
]

# Header to look like a normal browser. Many small-business sites block
# Python's default urllib User-Agent.
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.5",
}

REQUEST_TIMEOUT = 8        # seconds per HTTP request
MAX_PAGES_PER_SITE = 5     # cap total pages we fetch per company
MAX_TEXT_PER_PAGE = 8000   # truncate each page's extracted text

# Email pattern. Permissive on the local part (allows + . - _) and the domain
# is one-or-more dot-separated label groups — that prevents capturing a
# trailing sentence period like "hello@example.com." → "hello@example.com.".
EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")


def _fetch(url: str) -> str | None:
    """Fetch a URL with a real-browser User-Agent. Return HTML or None on any error."""
    try:
        resp = requests.get(url, headers=HEADERS, timeout=REQUEST_TIMEOUT, allow_redirects=True)
        if resp.status_code != 200:
            return None
        ctype = resp.headers.get("content-type", "")
        if "html" not in ctype.lower():
            return None
        return resp.text
    except Exception:
        return None


def _extract_text(html: str) -> str:
    """Strip scripts/styles/nav junk and return readable visible text."""
    soup = BeautifulSoup(html, "html.parser")
    # Remove obvious non-content
    for tag in soup(["script", "style", "noscript", "svg", "iframe"]):
        tag.decompose()
    text = soup.get_text(separator="\n", strip=True)
    # Collapse whitespace
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text[:MAX_TEXT_PER_PAGE]


def _candidate_urls(homepage_url: str, html: str) -> list[str]:
    """Find on-domain links whose text or URL path matches owner-page keywords."""
    soup = BeautifulSoup(html, "html.parser")
    base_domain = urlparse(homepage_url).netloc.lower()
    seen: set[str] = set()
    candidates: list[str] = []

    for link in soup.find_all("a", href=True):
        href = link["href"].strip()
        if not href or href.startswith(("#", "mailto:", "tel:", "javascript:")):
            continue
        full = urljoin(homepage_url, href)
        parsed = urlparse(full)
        # Same domain only — no off-site About-Us hijacks
        if parsed.netloc.lower() != base_domain:
            continue
        # Drop fragments, normalize
        clean = parsed._replace(fragment="").geturl()
        if clean in seen:
            continue

        link_text = link.get_text(strip=True).lower()
        path = parsed.path.lower()
        haystack = f"{link_text} {path}"
        if any(kw in haystack for kw in OWNER_PAGE_KEYWORDS):
            seen.add(clean)
            candidates.append(clean)

    return candidates


def _extract_emails(html: str, domain_hint: str = "") -> list[str]:
    """Pull all email addresses from HTML — mailto: links AND plain text matches.

    If `domain_hint` is provided, prioritize emails on that domain (the
    business's own email is the only one we care about; webmaster emails on
    third-party domains are noise).
    """
    soup = BeautifulSoup(html, "html.parser")
    found: set[str] = set()

    # mailto: links — most reliable signal
    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        if href.lower().startswith("mailto:"):
            email = href[7:].split("?")[0].strip().lower()
            if EMAIL_RE.fullmatch(email):
                found.add(email)

    # Plain-text emails in visible content
    text = soup.get_text(separator=" ")
    for match in EMAIL_RE.findall(text):
        found.add(match.lower())

    # Filter out obvious junk: image filenames, encoded entities, etc.
    cleaned = [e for e in found if not any(b in e for b in (".png", ".jpg", ".gif", "wixpress", "sentry", "@2x"))]

    # Sort: same-domain emails first
    if domain_hint:
        same = [e for e in cleaned if e.endswith("@" + domain_hint)]
        other = [e for e in cleaned if not e.endswith("@" + domain_hint)]
        return same + other
    return cleaned


@dataclass
class CrawlResult:
    pages: list[tuple[str, str]] = field(default_factory=list)
    emails: list[str] = field(default_factory=list)


def _normalize_homepage(website: str) -> str | None:
    """Add scheme if missing, drop trailing junk."""
    if not website:
        return None
    w = website.strip()
    if not w.startswith(("http://", "https://")):
        w = "https://" + w
    return w


def crawl_owner_pages(website: str) -> CrawlResult:
    """Main entry point. Given a company website URL, crawl pages likely to
    mention the owner. Returns a CrawlResult with:
      - pages: up to MAX_PAGES_PER_SITE (url, text) pairs
      - emails: deduped email addresses found anywhere across those pages,
                with same-domain emails listed first

    The homepage is always included if reachable — many small-business
    sites mention the owner in the footer or hero section of the home page.
    """
    homepage_url = _normalize_homepage(website)
    if not homepage_url:
        return CrawlResult()

    home_html = _fetch(homepage_url)
    if not home_html:
        return CrawlResult()

    domain_hint = urlparse(homepage_url).netloc.lower()
    if domain_hint.startswith("www."):
        domain_hint = domain_hint[4:]

    pages: list[tuple[str, str]] = [(homepage_url, _extract_text(home_html))]
    all_emails: set[str] = set(_extract_emails(home_html, domain_hint))

    # Find candidate sub-pages from links on the homepage
    candidate_urls = _candidate_urls(homepage_url, home_html)
    for url in candidate_urls[: MAX_PAGES_PER_SITE - 1]:
        html = _fetch(url)
        if not html:
            continue
        text = _extract_text(html)
        if text:
            pages.append((url, text))
            all_emails.update(_extract_emails(html, domain_hint))
        if len(pages) >= MAX_PAGES_PER_SITE:
            break

    # Re-sort emails so same-domain ones come first (set order isn't preserved)
    same = sorted(e for e in all_emails if e.endswith("@" + domain_hint))
    other = sorted(e for e in all_emails if not e.endswith("@" + domain_hint))

    return CrawlResult(pages=pages, emails=same + other)
