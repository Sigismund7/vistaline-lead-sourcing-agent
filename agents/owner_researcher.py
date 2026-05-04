"""Owner Researcher — finds the owner's full name for every kept lead.

Two-phase strategy per lead, in parallel across leads:

  Phase 1: Crawl the company's own website.
    Fetch homepage + likely sub-pages (About, Team, Meet, Owner...),
    extract text, send to Claude to pull the owner name.
    No web_search tokens used. Fast and cheap.

  Phase 2 (only if Phase 1 fails): BBB + Google search.
    Falls back to Claude with the web_search tool. Slower, more
    expensive, but catches leads whose websites don't mention the owner.

Hit rate expectation:
  - Phase 1 alone: ~50–65% (small contractors often have About pages)
  - Phase 1 + Phase 2 combined: ~70–80%

Never guesses. If neither phase finds a confident answer, returns blank.
"""
from __future__ import annotations
import concurrent.futures as futures
import json
import re
from anthropic import Anthropic

from state import CampaignState, Lead
from agents.website_crawler import crawl_owner_pages


MAX_PARALLEL = 10  # I/O bound now, can run more at once


# ---------- Phase 1: website extraction ----------

PHASE1_SYSTEM = """You are reading text excerpted from a small remodeling-contractor's own website.

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
    b) Its local part matches the owner's first name or initials
       (e.g., owner = "Mike Smith", email = "mike@acmebath.com" or "msmith@...").
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


def _phase1_website(lead: Lead, anthropic_key: str) -> dict:
    """Crawl the company website and ask Claude to find the owner + email."""
    if not lead.website:
        return {"owner_full_name": "", "confidence": "none"}

    crawl = crawl_owner_pages(lead.website)
    if not crawl.pages:
        return {"owner_full_name": "", "confidence": "none"}

    # Build a compact payload for Claude. Cap total chars so we don't blow
    # the context on a chatty website.
    chunks = []
    total_chars = 0
    char_budget = 24000
    for url, text in crawl.pages:
        if total_chars >= char_budget:
            break
        snippet = text[: max(0, char_budget - total_chars)]
        chunks.append(f"=== Page: {url} ===\n{snippet}")
        total_chars += len(snippet)

    # Show Claude the email candidates we extracted from the HTML — this
    # constrains the owner_email field to actually-present emails and saves
    # tokens vs. asking Claude to find them in the prose.
    if crawl.emails:
        email_block = "Candidate emails extracted from the site (pick one or none):\n" + "\n".join(
            f"  - {e}" for e in crawl.emails[:20]
        )
    else:
        email_block = "No emails were found on the site. Set owner_email to \"\"."

    user_msg = (
        f"Business: {lead.business_name}\n"
        f"Website: {lead.website}\n\n"
        f"{email_block}\n\n"
        "Pages from their website:\n\n"
        + "\n\n".join(chunks)
    )

    client = Anthropic(api_key=anthropic_key)
    try:
        response = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=1000,
            system=PHASE1_SYSTEM,
            messages=[{"role": "user", "content": user_msg}],
        )
    except Exception as e:
        return {"owner_full_name": "", "confidence": "none", "error": str(e)}

    text = response.content[0].text.strip()
    return _parse_owner_json(text)


# ---------- Phase 2: BBB + Google search fallback ----------

PHASE2_SYSTEM = """You are a research assistant finding the owner of a small remodeling-contractor business.

Use the web_search tool. Strategy in this order, stop when you find a real name:
1. Search:  "{business_name}" {city} BBB
   If a BBB.org result appears, look for "Principal" / "Owner" / "President".
2. Search:  {business_name} owner {city}
3. Search:  {business_name} {city} {state} owner OR founder

NEVER GUESS. If no name is found, return empty.

Output JSON only:
{{
  "owner_full_name": "First Last",
  "source_url": "the URL where you found the name",
  "confidence": "high" | "medium" | "low" | "none"
}}
"""


def _phase2_bbb(lead: Lead, city: str, state_abbr: str, anthropic_key: str) -> dict:
    """Fall back to BBB + Google search via Claude's web_search tool."""
    client = Anthropic(api_key=anthropic_key)
    user_msg = (
        f"Business: {lead.business_name}\n"
        f"City: {city}, {state_abbr}\n"
        f"Website: {lead.website or '(none)'}\n\n"
        "Find the owner's full name via BBB or Google search. Return JSON only."
    )

    try:
        response = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=2000,
            system=PHASE2_SYSTEM.format(
                business_name=lead.business_name, city=city, state=state_abbr,
            ),
            tools=[{"type": "web_search_20250305", "name": "web_search", "max_uses": 4}],
            messages=[{"role": "user", "content": user_msg}],
        )
    except Exception as e:
        return {"owner_full_name": "", "confidence": "none", "error": str(e)}

    text = "".join(b.text for b in response.content if getattr(b, "type", "") == "text").strip()
    return _parse_owner_json(text)


# ---------- shared helpers ----------

def _parse_owner_json(text: str) -> dict:
    """Pull the JSON object out of a Claude response, robust to code fences and prose."""
    # Strip code fences
    if text.startswith("```"):
        text = text.split("```")[1]
        if text.startswith("json"):
            text = text[4:]
        text = text.strip()
    # Find the first {...} object — search for one containing owner_full_name.
    # Use a non-greedy match that allows nested content (the outer pair only
    # has flat keys, but evidence strings may contain braces).
    match = re.search(r"\{[^{}]*?\"owner_full_name\".*?\}", text, re.DOTALL)
    raw = match.group(0) if match else text
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return {"owner_full_name": "", "confidence": "none"}


def _split_name(full: str) -> tuple[str, str]:
    parts = (full or "").strip().split()
    if not parts:
        return "", ""
    if len(parts) == 1:
        return parts[0], ""
    return parts[0], " ".join(parts[1:])


def _research_one(lead: Lead, city: str, state_abbr: str, anthropic_key: str) -> dict:
    """Run Phase 1, then Phase 2 only if Phase 1 didn't get high/medium confidence."""
    if not lead.kept or not lead.business_name:
        return {"owner_full_name": "", "confidence": "none", "phase": "skipped"}

    # Phase 1: website crawl
    p1 = _phase1_website(lead, anthropic_key)
    if p1.get("owner_full_name") and p1.get("confidence") in ("high", "medium"):
        p1["phase"] = "website"
        return p1

    # Phase 2: BBB + Google
    p2 = _phase2_bbb(lead, city, state_abbr, anthropic_key)
    if p2.get("owner_full_name") and p2.get("confidence") in ("high", "medium"):
        p2["phase"] = "bbb_search"
        return p2

    return {"owner_full_name": "", "confidence": "none", "phase": "not_found"}


# ---------- agent entry point ----------

def run(state: CampaignState, anthropic_key: str) -> None:
    if state.is_done("owner_researcher"):
        found = sum(1 for l in state.leads if l.owner_full_name)
        state.info("owner_researcher", f"already complete, skipping ({found} found)")
        return

    targets = [l for l in state.leads if l.kept and not l.owner_full_name]
    already_done = sum(1 for l in state.leads if l.kept) - len(targets)
    if already_done:
        state.info(
            "owner_researcher",
            "skipping already-researched leads on resume",
            skipped=already_done,
        )
    state.info(
        "owner_researcher",
        f"researching {len(targets)} owners (parallel × {MAX_PARALLEL})",
    )

    via_website = via_bbb = not_found = 0
    pre_enriched = 0

    with futures.ThreadPoolExecutor(max_workers=MAX_PARALLEL) as pool:
        future_map = {
            pool.submit(_research_one, lead, state.city, state.state_abbr, anthropic_key): lead
            for lead in targets
        }
        for fut in futures.as_completed(future_map):
            lead = future_map[fut]
            try:
                result = fut.result()
            except Exception as e:
                state.info("owner_researcher", f"error on {lead.business_name}", error=str(e))
                not_found += 1
                continue

            full = (result.get("owner_full_name") or "").strip()
            if full and result.get("confidence") in ("high", "medium"):
                lead.owner_full_name = full
                lead.owner_first, lead.owner_last = _split_name(full)
                lead.owner_source = result.get("phase", "")
                email = (result.get("owner_email") or "").strip().lower()
                if email and result.get("phase") == "website":
                    lead.email = email
                    pre_enriched += 1
                if result.get("phase") == "website":
                    via_website += 1
                else:
                    via_bbb += 1
            else:
                not_found += 1

            # Checkpoint: persist all leads after each completion so --resume
            # skips already-researched leads if the process crashes mid-batch.
            state.save_leads()

    state.info(
        "owner_researcher",
        f"done: {via_website} via website ({pre_enriched} with email), "
        f"{via_bbb} via BBB, {not_found} not found",
    )
    state.mark_done("owner_researcher")
