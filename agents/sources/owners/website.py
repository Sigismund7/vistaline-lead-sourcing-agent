"""Phase 1 — website crawl owner lookup.

Fetches the lead's own website pages and asks Claude to extract the owner
name and (if present) owner email. Free, no external API calls beyond the
website itself and Claude Sonnet for parsing.
"""
from __future__ import annotations

from anthropic import Anthropic

from state import Lead
from agents.website_crawler import crawl_owner_pages
from agents.sources.owners._utils import parse_owner_json

SYSTEM_PROMPT = """You are reading text excerpted from a small remodeling-contractor's own website.

You have two goals:
  1. Find the owner / founder / president of the business.
  2. If visible, also find the owner's direct email address.

OWNER NAME RULES:
- Look for explicit ownership language: "founded by", "owner", "founder",
  "president", "started by", "owned and operated by", "principal".
- A name in a bio paragraph paired with one of those titles counts.
- A name on a team page with a title like "Project Manager" or "Designer"
  does NOT count — those are employees, not owners.
- For family businesses, return the founding generation if multiple names
  appear (e.g., if "founded by Mike Smith in 1995" and his sons are listed,
  return Mike Smith).
- Never guess. If no ownership language appears, return empty.

OWNER EMAIL RULES:
- The user will give you a list of email addresses extracted from the site.
  ONLY pick from that list — never invent or guess an email.
- Generic emails are NOT the owner's email. Reject:
  info@, sales@, contact@, hello@, office@, admin@, support@, hi@,
  team@, service@, customerservice@, marketing@, billing@.
- Pick an email when:
    a) It's bound to the owner in text (e.g., "Mike Smith — mike@acmebath.com").
    b) Its local part matches the owner's first name or initials.
    c) A bio paragraph contains the email next to the owner's name.
- If none of the candidate emails clearly belongs to the owner, return "".

Output JSON only:
{
  "owner_full_name": "First Last",
  "owner_email": "mike@acmebath.com",
  "source_url": "the URL where you found the name",
  "evidence": "the short phrase from the page that confirmed it",
  "confidence": "high" | "medium" | "low" | "none"
}

If no owner found, set owner_full_name to "" and confidence to "none".
If owner found but no matching email, set owner_email to "".
"""


def lookup(lead: Lead, city: str, state_abbr: str, anthropic_key: str) -> dict:
    """Phase 1: crawl the lead's website and ask Claude to extract the owner.

    Returns a dict with at minimum: owner_full_name (str), confidence (str).
    Also returns owner_email when found on the site.
    """
    if not lead.website:
        return {"owner_full_name": "", "confidence": "none"}

    crawl = crawl_owner_pages(lead.website)
    if not crawl.pages:
        return {"owner_full_name": "", "confidence": "none"}

    chunks: list[str] = []
    total_chars = 0
    char_budget = 24000
    for url, text in crawl.pages:
        if total_chars >= char_budget:
            break
        snippet = text[: max(0, char_budget - total_chars)]
        chunks.append(f"=== Page: {url} ===\n{snippet}")
        total_chars += len(snippet)

    email_block = (
        "Candidate emails extracted from the site (pick one or none):\n"
        + "\n".join(f"  - {e}" for e in crawl.emails[:20])
        if crawl.emails
        else 'No emails were found on the site. Set owner_email to "".'
    )

    user_msg = (
        f"Business: {lead.business_name}\n"
        f"Website: {lead.website}\n\n"
        f"{email_block}\n\n"
        "Pages from their website:\n\n"
        + "\n\n".join(chunks)
    )

    client = Anthropic(api_key=anthropic_key, timeout=60.0, max_retries=10)
    try:
        response = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=1000,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_msg}],
        )
    except Exception as e:
        return {"owner_full_name": "", "confidence": "none", "error": str(e)}

    result = parse_owner_json(response.content[0].text.strip())
    result.setdefault("phase", "website")
    return result
