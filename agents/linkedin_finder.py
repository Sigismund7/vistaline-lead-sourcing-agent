"""LinkedIn finder — uses Claude's web_search tool to locate the owner's
LinkedIn profile URL given (owner_full_name, business_name, city).

Same architectural pattern as owner_researcher Phase 2: each parallel
worker constructs its own Anthropic client. Returns blank when the model
can't find a profile that clearly matches the owner — never guesses.
"""
from __future__ import annotations
import concurrent.futures as futures
import json
import re
from anthropic import Anthropic

from state import CampaignState, Lead


STEP_NAME = "linkedin_finder"

_LINKEDIN_PROFILE_RE = re.compile(
    r"^https?://([a-z]{2,3}\.)?linkedin\.com/in/[^/?#]+/?$",
    re.IGNORECASE,
)


def is_valid_linkedin_profile_url(url: str) -> bool:
    """True when the URL is a personal LinkedIn profile (/in/<slug>).

    Rejects /company/, /posts/, /pulse/, /school/ and anything off-domain.
    Used to filter out hallucinations and adjacent-but-wrong matches.
    """
    if not url or not isinstance(url, str):
        return False
    return bool(_LINKEDIN_PROFILE_RE.match(url.strip()))


_SYSTEM = """You are a researcher finding the LinkedIn profile URL for a small-business owner.

Given (owner full name, business name, city), use the web_search tool to locate
their personal LinkedIn profile. Personal profiles live at linkedin.com/in/<slug>.

Match rules:
- The profile name must clearly correspond to the given owner name.
- The profile must be a person, NOT a company page (linkedin.com/company/...).
- If multiple candidates exist, pick the one whose current role mentions the
  business name OR the city.
- If no profile clearly matches, return blank — NEVER guess.

Output strict JSON only:
{
  "linkedin_url": "https://linkedin.com/in/...",
  "confidence": "high" | "medium" | "low" | "none"
}
"""


def _find_one(owner: str, business: str, city: str, anthropic_key: str) -> str:
    """Return the LinkedIn URL or "" — never raises."""
    if not owner or not business:
        return ""
    client = Anthropic(api_key=anthropic_key)
    user = (
        f"Owner: {owner}\nBusiness: {business}\nCity: {city}\n\n"
        "Find this person's LinkedIn profile."
    )
    try:
        resp = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=400,
            system=_SYSTEM,
            tools=[{"type": "web_search_20250305", "name": "web_search", "max_uses": 4}],
            messages=[{"role": "user", "content": user}],
        )
    except Exception as e:
        print(f"[linkedin_finder] WARN: {owner!r} @ {business!r}: {type(e).__name__} {e}")
        return ""
    raw = "".join(b.text for b in resp.content if hasattr(b, "text"))
    match = re.search(r"\{.*\}", raw, flags=re.DOTALL)
    if not match:
        return ""
    try:
        data = json.loads(match.group(0))
    except json.JSONDecodeError:
        return ""
    url = str(data.get("linkedin_url", "") or "").strip()
    if data.get("confidence") in ("none", "low"):
        return ""
    if not is_valid_linkedin_profile_url(url):
        return ""
    return url


def run(
    state: CampaignState,
    anthropic_key: str,
    *,
    max_parallel: int = 4,
) -> None:
    """Fill linkedin_url / linkedin_source for every kept lead with email and
    owner. Idempotent — skips leads with linkedin_source already set.
    """
    if state.is_done(STEP_NAME):
        state.info(STEP_NAME, "already done, skipping")
        return

    targets = [
        l for l in state.leads
        if l.kept and l.email and l.owner_full_name and not l.linkedin_source
    ]
    state.info(STEP_NAME, f"searching for {len(targets)} LinkedIn profiles")

    with futures.ThreadPoolExecutor(max_workers=max_parallel) as ex:
        fut_to_lead = {
            ex.submit(
                _find_one,
                lead.owner_full_name,
                lead.business_name,
                state.city,
                anthropic_key,
            ): lead
            for lead in targets
        }
        for fut in futures.as_completed(fut_to_lead):
            lead = fut_to_lead[fut]
            url = fut.result()  # _find_one swallows external errors
            lead.linkedin_url = url
            lead.linkedin_source = "web_search" if url else ""
            state.info(STEP_NAME, f"{lead.owner_full_name}: {url or '(none)'}")

    state.mark_done(STEP_NAME)
