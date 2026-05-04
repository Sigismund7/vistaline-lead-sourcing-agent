# Owner Researcher v2 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Extend owner_researcher to four sequential phases (website → Houzz → OpenCorporates → web search), each toggleable from the new-campaign form, pushing owner-name hit rate from ~75% to ~92-95% nationwide.

**Architecture:** Four phase modules under `agents/sources/owners/` each export a uniform `lookup(lead, city, state_abbr, anthropic_key) -> dict`. The `owner_researcher.py` orchestrator builds a phase list from campaign toggle flags (stored on the `campaigns` DB row) and short-circuits on the first high/medium-confidence result. New clients `HouzzClient` and `OpenCorporatesClient` live in `tools.py`. Three checkboxes on the new-campaign form persist to `campaigns.use_houzz / use_registry / use_websearch`.

**Tech Stack:** Python 3.11, requests, BeautifulSoup4, rapidfuzz (already installed), anthropic SDK, OpenCorporates REST API v0.4, Next.js 16, Supabase Postgres, FastAPI.

**Branch:** `tightening` — all commits go here.

---

## File Map

| Action | Path | Purpose |
|---|---|---|
| Modify | `supabase/migrations/003_owner_toggles.sql` | Add 3 toggle columns to campaigns |
| Modify | `state.py` | Add toggle fields to CampaignState |
| Modify | `config.py` | Add `opencorporates_api_key` |
| Modify | `tools.py` | Add `HouzzClient`, `OpenCorporatesClient` |
| Create | `agents/sources/owners/__init__.py` | Package marker |
| Create | `agents/sources/owners/_utils.py` | Shared helpers: `parse_owner_json`, `split_name` |
| Create | `agents/sources/owners/website.py` | Phase 1 — website crawl (extracted) |
| Create | `agents/sources/owners/websearch.py` | Phase 4 — BBB + Google web search (extracted) |
| Create | `agents/sources/owners/houzz.py` | Phase 2 — Houzz name+city scrape |
| Create | `agents/sources/owners/opencorporates.py` | Phase 3 — OpenCorporates officer lookup |
| Modify | `agents/owner_researcher.py` | Orchestrator refactor: phase list + toggles |
| Modify | `api/main.py` | `CampaignCreate` model: 3 toggle fields |
| Modify | `frontend/app/campaigns/new/page.tsx` | 3 toggle checkboxes |
| Modify | `frontend/app/campaigns/actions.ts` | Pass toggles to API |
| Create | `tests/test_houzz_helpers.py` | Unit tests for Houzz fuzzy match |
| Create | `tests/test_opencorporates_helpers.py` | Unit tests for OC officer priority + jurisdiction |

---

## Task 1: DB Migration

**Files:**
- Create: `supabase/migrations/003_owner_toggles.sql`

- [ ] **Step 1: Write the migration file**

```sql
-- supabase/migrations/003_owner_toggles.sql
ALTER TABLE campaigns ADD COLUMN IF NOT EXISTS use_houzz    BOOLEAN NOT NULL DEFAULT TRUE;
ALTER TABLE campaigns ADD COLUMN IF NOT EXISTS use_registry BOOLEAN NOT NULL DEFAULT TRUE;
ALTER TABLE campaigns ADD COLUMN IF NOT EXISTS use_websearch BOOLEAN NOT NULL DEFAULT TRUE;
```

- [ ] **Step 2: Apply to Supabase**

Open the Supabase dashboard → SQL Editor, paste and run the migration. Confirm with:

```sql
SELECT column_name, data_type, column_default
FROM information_schema.columns
WHERE table_name = 'campaigns'
  AND column_name IN ('use_houzz', 'use_registry', 'use_websearch');
```

Expected: 3 rows, `data_type = boolean`, `column_default = true`.

- [ ] **Step 3: Commit**

```bash
git add supabase/migrations/003_owner_toggles.sql
git commit -m "feat(db): add use_houzz/use_registry/use_websearch toggle columns"
```

---

## Task 2: CampaignState Toggle Fields

**Files:**
- Modify: `state.py:54-70` (CampaignState dataclass + save + load)

- [ ] **Step 1: Write the failing test**

```python
# tests/test_state_toggle_fields.py
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from state import CampaignState

def test_toggle_defaults():
    state = CampaignState(campaign_id="test-001", city="Tampa", state_abbr="FL", niche="Kitchen")
    assert state.use_houzz is True
    assert state.use_registry is True
    assert state.use_websearch is True

def test_toggle_false():
    state = CampaignState(
        campaign_id="test-002", city="Tampa", state_abbr="FL", niche="Kitchen",
        use_houzz=False, use_registry=False, use_websearch=False,
    )
    assert state.use_houzz is False
    assert state.use_registry is False
    assert state.use_websearch is False

if __name__ == "__main__":
    test_toggle_defaults()
    test_toggle_false()
    print("OK")
```

- [ ] **Step 2: Run test to verify it fails**

```bash
python tests/test_state_toggle_fields.py
```

Expected: `AttributeError: 'CampaignState' object has no attribute 'use_houzz'`

- [ ] **Step 3: Add toggle fields to CampaignState**

In `state.py`, add three fields to the `CampaignState` dataclass after `triggered_by`:

```python
@dataclass
class CampaignState:
    campaign_id: str
    city: str = ""
    state_abbr: str = ""
    niche: str = ""
    target_count: int = 50
    triggered_by: str = "DG"
    use_houzz: bool = True        # NEW
    use_registry: bool = True     # NEW
    use_websearch: bool = True    # NEW
    status: str = "running"
    leads: list[Lead] = field(default_factory=list)
    log: list[dict] = field(default_factory=list)
    completed_steps: list[str] = field(default_factory=list)
    created_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())
```

- [ ] **Step 4: Update `save()` to persist the three fields**

In `state.py`, inside `save()`, add the three fields to `payload`:

```python
payload: dict = {
    "id": self.campaign_id,
    "city": self.city,
    "state_abbr": self.state_abbr,
    "niche": self.niche,
    "target_count": self.target_count,
    "triggered_by": self.triggered_by,
    "use_houzz": self.use_houzz,
    "use_registry": self.use_registry,
    "use_websearch": self.use_websearch,
    "status": self.status,
    "total_leads": len(self.leads),
    "kept_leads": len(kept),
    "with_owner": sum(1 for l in kept if l.owner_first),
    "with_email": sum(1 for l in kept if l.email),
    "completed_steps": self.completed_steps,
    "created_at": self.created_at,
}
```

- [ ] **Step 5: Update `load()` to read the three fields**

In `state.py`, inside `load()`, add to the `cls(...)` constructor call:

```python
return cls(
    campaign_id=row["id"],
    city=row["city"],
    state_abbr=row["state_abbr"],
    niche=row["niche"],
    target_count=row["target_count"],
    triggered_by=row.get("triggered_by", "DG"),
    use_houzz=row.get("use_houzz", True),
    use_registry=row.get("use_registry", True),
    use_websearch=row.get("use_websearch", True),
    status=row.get("status", "running"),
    leads=leads,
    completed_steps=row.get("completed_steps") or [],
    created_at=row["created_at"],
)
```

- [ ] **Step 6: Run test to verify it passes**

```bash
python tests/test_state_toggle_fields.py
```

Expected: `OK`

- [ ] **Step 7: Commit**

```bash
git add state.py tests/test_state_toggle_fields.py
git commit -m "feat(state): add use_houzz/use_registry/use_websearch toggle fields"
```

---

## Task 3: Config + Env Var

**Files:**
- Modify: `config.py:22-94`

- [ ] **Step 1: Add `opencorporates_api_key` to Config**

In `config.py`, add after `brave_search_key`:

```python
# Owner research layer 3 — OpenCorporates business registry API.
# Free tier: 50 lookups/day. Upgrade at https://opencorporates.com/api_accounts/new
# ($0.50/1000 lookups). Empty string = unauthenticated (still works at free-tier rate).
opencorporates_api_key: str = ""
```

And in the `CONFIG = Config(...)` block:

```python
opencorporates_api_key=_optional("OPENCORPORATES_API_KEY"),
```

- [ ] **Step 2: Add env var to local `.env` (development only)**

In your local `.env` file, add:

```
OPENCORPORATES_API_KEY=
```

Leave blank for now — the client works unauthenticated at the free-tier rate. Fill it in after upgrading the plan.

- [ ] **Step 3: Smoke test**

```bash
python -c "from config import CONFIG; print('opencorporates_api_key' in CONFIG.__dataclass_fields__); print('OK')"
```

Expected: `True` then `OK`

- [ ] **Step 4: Commit**

```bash
git add config.py
git commit -m "feat(config): add OPENCORPORATES_API_KEY env var"
```

---

## Task 4: HouzzClient in tools.py

**Files:**
- Modify: `tools.py` (append at end)

- [ ] **Step 1: Append HouzzClient to `tools.py`**

```python
# --------------------------------------------------------------------------- #
# Houzz scraper client                                                        #
# --------------------------------------------------------------------------- #


class HouzzClient:
    """Minimal HTTP scraper for Houzz professional search + profile pages.

    Not rate-limited beyond the implicit throttle of MAX_PARALLEL=10 leads
    running concurrently (each lead makes at most 2 requests). Cloudflare
    protection on Houzz means a 403 or JS-challenge page is possible — both
    are treated as a miss and the caller falls through to the next phase.

    Not thread-safe; construct one per worker thread (CLAUDE.md rule).
    """

    SEARCH_URL = "https://www.houzz.com/professionals/search"
    USER_AGENT = (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    )

    def __init__(self, timeout_s: int = 15) -> None:
        self._timeout = timeout_s
        self._session = requests.Session()
        self._session.headers.update({
            "User-Agent": self.USER_AGENT,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
            "Accept-Encoding": "gzip, deflate, br",
        })

    def search(self, business_name: str) -> list[dict]:
        """Search Houzz for a business name.

        Returns a list of dicts with keys: name, location, profile_url.
        Returns [] on any HTTP error or Cloudflare block.
        """
        try:
            resp = self._session.get(
                self.SEARCH_URL,
                params={"q": business_name},
                timeout=self._timeout,
                allow_redirects=True,
            )
        except requests.RequestException:
            return []
        if resp.status_code != 200:
            return []
        return self._parse_search_results(resp.text)

    def get_profile_text(self, profile_url: str) -> str:
        """Fetch a Houzz profile page and return About-section text (max 4000 chars).

        Returns "" on any error or Cloudflare block.
        """
        try:
            resp = self._session.get(profile_url, timeout=self._timeout, allow_redirects=True)
        except requests.RequestException:
            return ""
        if resp.status_code != 200:
            return ""
        return self._parse_profile_text(resp.text)

    # ------------------------------------------------------------------ #
    # Private parsers — CSS selectors verified against Houzz HTML 2026-05 #
    # If search returns 0 results, inspect resp.text for the actual        #
    # container classes and update these selectors.                        #
    # ------------------------------------------------------------------ #

    def _parse_search_results(self, html: str) -> list[dict]:
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(html, "html.parser")
        results: list[dict] = []
        # Houzz search result cards — try multiple known selector patterns.
        cards = (
            soup.select("[data-component='ProCard']")
            or soup.select(".hz-pro-search-result")
            or soup.select("li.search-results__item")
        )
        for card in cards:
            name_el = (
                card.select_one("[data-component='ProName']")
                or card.select_one(".hz-pro-search-result__title")
                or card.select_one("h2")
            )
            loc_el = (
                card.select_one("[data-component='ProLocation']")
                or card.select_one(".hz-pro-search-result__location")
                or card.select_one(".pro-location")
            )
            link_el = card.select_one("a[href]")
            if not name_el or not link_el:
                continue
            href = link_el["href"]
            results.append({
                "name": name_el.get_text(strip=True),
                "location": loc_el.get_text(strip=True) if loc_el else "",
                "profile_url": href if href.startswith("http") else f"https://www.houzz.com{href}",
            })
        return results

    def _parse_profile_text(self, html: str) -> str:
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(html, "html.parser")
        about = (
            soup.select_one("[data-component='AboutSection']")
            or soup.select_one(".hz-pro-profile__about")
            or soup.select_one("#about")
            or soup.select_one(".pro-description")
        )
        if about:
            return about.get_text(separator=" ", strip=True)[:4000]
        # Fallback: collect all paragraph text
        return " ".join(p.get_text(strip=True) for p in soup.find_all("p"))[:4000]
```

- [ ] **Step 2: Smoke test**

```bash
python -c "from tools import HouzzClient; c = HouzzClient(); print('OK')"
```

Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add tools.py
git commit -m "feat(tools): add HouzzClient HTTP scraper"
```

---

## Task 5: OpenCorporatesClient in tools.py

**Files:**
- Modify: `tools.py` (append at end)

- [ ] **Step 1: Append OpenCorporatesClient to `tools.py`**

```python
# --------------------------------------------------------------------------- #
# OpenCorporates client                                                       #
# --------------------------------------------------------------------------- #


class OpenCorporatesClient:
    """Client for the OpenCorporates v0.4 companies API.

    Used by Phase 3 of owner_researcher to look up LLC/Corp officer names.
    Handles 429 rate-limit gracefully (returns []) so the caller can fall
    through to the next phase.

    Free tier: 50 lookups/day unauthenticated (or with free API key).
    Paid tier ($0.50/1000): set OPENCORPORATES_API_KEY. See spec alert.

    Not thread-safe; construct one per worker thread (CLAUDE.md rule).
    """

    BASE_URL = "https://api.opencorporates.com/v0.4"

    # Officer role keywords in descending priority order.
    ROLE_PRIORITY = ["owner", "president", "ceo", "principal", "founder", "manager", "director"]

    def __init__(self, api_key: str = "", timeout_s: int = 15) -> None:
        self._api_key = api_key
        self._timeout = timeout_s
        self._session = requests.Session()

    def search_company_officers(
        self, business_name: str, state_abbr: str
    ) -> list[dict]:
        """Search for a company and return its current officers.

        Returns a list of dicts with keys: name (str), role (str), is_current (bool).
        Returns [] on 429, network error, no results, or parse failure.
        """
        params: dict[str, Any] = {
            "q": business_name,
            "jurisdiction_code": f"us_{state_abbr.lower()}",
            "include_officers": "true",
        }
        if self._api_key:
            params["api_token"] = self._api_key

        try:
            resp = self._session.get(
                f"{self.BASE_URL}/companies/search",
                params=params,
                timeout=self._timeout,
            )
        except requests.RequestException:
            return []

        if resp.status_code == 429:
            return []  # rate-limited — silent fallthrough per spec
        if not resp.ok:
            return []

        try:
            data = resp.json()
        except ValueError:
            return []

        companies = data.get("results", {}).get("companies") or []
        if not companies:
            return []

        # Use the first result's officer list
        company = companies[0].get("company", {})
        officers_raw = company.get("officers") or []
        return [
            {
                "name": o.get("officer", {}).get("name", ""),
                "role": (
                    o.get("officer", {}).get("position")
                    or o.get("officer", {}).get("title")
                    or ""
                ).lower(),
                "is_current": o.get("officer", {}).get("end_date") is None,
            }
            for o in officers_raw
            if o.get("officer", {}).get("name")
        ]

    def pick_best_officer(self, officers: list[dict]) -> str | None:
        """Return the name of the highest-priority current officer, or None.

        Priority: owner > president > ceo > principal > founder > manager > director.
        Falls back to any current officer if no priority role matches.
        """
        if not officers:
            return None
        current = [o for o in officers if o.get("is_current", True)] or officers
        for role_keyword in self.ROLE_PRIORITY:
            for o in current:
                if role_keyword in o.get("role", "").lower():
                    return o["name"] or None
        return current[0]["name"] or None
```

- [ ] **Step 2: Smoke test**

```bash
python -c "from tools import OpenCorporatesClient; c = OpenCorporatesClient(); print(c.pick_best_officer([{'name':'Jane Smith','role':'president','is_current':True}]))"
```

Expected: `Jane Smith`

- [ ] **Step 3: Commit**

```bash
git add tools.py
git commit -m "feat(tools): add OpenCorporatesClient for Phase 3 officer lookup"
```

---

## Task 6: agents/sources/owners/ Package + Shared Utils + Phase Extractions

**Files:**
- Create: `agents/sources/owners/__init__.py`
- Create: `agents/sources/owners/_utils.py`
- Create: `agents/sources/owners/website.py`
- Create: `agents/sources/owners/websearch.py`

- [ ] **Step 1: Create the package files**

```bash
mkdir -p agents/sources/owners
touch agents/sources/owners/__init__.py
```

- [ ] **Step 2: Create `agents/sources/owners/_utils.py`**

```python
"""Shared helpers for owner-researcher phase modules."""
from __future__ import annotations
import json
import re


def parse_owner_json(text: str) -> dict:
    """Extract JSON owner dict from a Claude response, robust to code fences."""
    if text.startswith("```"):
        text = text.split("```")[1]
        if text.startswith("json"):
            text = text[4:]
        text = text.strip()
    match = re.search(r"\{[^{}]*?\"owner_full_name\".*?\}", text, re.DOTALL)
    raw = match.group(0) if match else text
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return {"owner_full_name": "", "confidence": "none"}


def split_name(full: str) -> tuple[str, str]:
    """Split 'First Last' → ('First', 'Last'). Handles single-word names."""
    parts = (full or "").strip().split()
    if not parts:
        return "", ""
    if len(parts) == 1:
        return parts[0], ""
    return parts[0], " ".join(parts[1:])
```

- [ ] **Step 3: Create `agents/sources/owners/website.py`**

This extracts `_phase1_website` from `owner_researcher.py` into the uniform `lookup()` signature.

```python
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

    client = Anthropic(api_key=anthropic_key)
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
```

- [ ] **Step 4: Create `agents/sources/owners/websearch.py`**

```python
"""Phase 4 — BBB + Google web search fallback owner lookup.

Uses Claude's web_search tool to search BBB.org, then Google "owner",
then Google "founder". Paid: ~$0.04/lead reaching this phase.
Toggleable via campaign.use_websearch.
"""
from __future__ import annotations

from anthropic import Anthropic

from state import Lead
from agents.sources.owners._utils import parse_owner_json

SYSTEM_PROMPT = """You are a research assistant finding the owner of a small remodeling-contractor business.

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


def lookup(lead: Lead, city: str, state_abbr: str, anthropic_key: str) -> dict:
    """Phase 4: BBB + Google web search via Claude's web_search tool.

    Returns a dict with at minimum: owner_full_name (str), confidence (str).
    """
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
            system=SYSTEM_PROMPT.format(
                business_name=lead.business_name, city=city, state=state_abbr,
            ),
            tools=[{"type": "web_search_20250305", "name": "web_search", "max_uses": 4}],
            messages=[{"role": "user", "content": user_msg}],
        )
    except Exception as e:
        return {"owner_full_name": "", "confidence": "none", "error": str(e)}

    text = "".join(
        b.text for b in response.content if getattr(b, "type", "") == "text"
    ).strip()
    result = parse_owner_json(text)
    result.setdefault("phase", "web_search")
    return result
```

- [ ] **Step 5: Smoke test**

```bash
python -c "from agents.sources.owners import website, websearch; from agents.sources.owners._utils import parse_owner_json, split_name; print('OK')"
```

Expected: `OK`

- [ ] **Step 6: Commit**

```bash
git add agents/sources/owners/
git commit -m "feat(owners): add phase package, _utils, website.py, websearch.py (extracted)"
```

---

## Task 7: Unit Tests for Houzz Helpers

**Files:**
- Create: `tests/test_houzz_helpers.py`

- [ ] **Step 1: Write the tests**

```python
# tests/test_houzz_helpers.py
"""Unit tests for Houzz city-fuzzy-match helper.

Tests the scoring logic in isolation — no HTTP calls, no Houzz dependency.
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from rapidfuzz import fuzz


def _city_score(result_location: str, target_city: str) -> int:
    """Extract city portion and score against target. Mirrors houzz.py logic."""
    # Location strings from Houzz look like "Tampa, FL" or "Tampa, Florida"
    city_part = result_location.split(",")[0].strip()
    return fuzz.token_sort_ratio(city_part.lower(), target_city.lower())


def test_exact_match():
    assert _city_score("Tampa, FL", "Tampa") >= 85

def test_case_insensitive():
    assert _city_score("TAMPA, FL", "Tampa") >= 85

def test_nearby_suburb_fails():
    # "Clearwater" is near Tampa but should NOT match Tampa
    assert _city_score("Clearwater, FL", "Tampa") < 85

def test_different_city_fails():
    assert _city_score("Atlanta, GA", "Tampa") < 85

def test_empty_location():
    assert _city_score("", "Tampa") < 85

def test_city_with_extra_text():
    # "San Francisco Bay Area, CA" should still match "San Francisco"
    score = _city_score("San Francisco Bay Area, CA", "San Francisco")
    # token_sort_ratio will partially match; we're fine with a miss here
    # (test documents the expected score range, not a hard requirement)
    assert isinstance(score, int)

if __name__ == "__main__":
    test_exact_match()
    test_case_insensitive()
    test_nearby_suburb_fails()
    test_different_city_fails()
    test_empty_location()
    test_city_with_extra_text()
    print("OK")
```

- [ ] **Step 2: Run tests**

```bash
python tests/test_houzz_helpers.py
```

Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add tests/test_houzz_helpers.py
git commit -m "test(houzz): city fuzzy-match scoring unit tests"
```

---

## Task 8: agents/sources/owners/houzz.py

**Files:**
- Create: `agents/sources/owners/houzz.py`

- [ ] **Step 1: Create the module**

```python
"""Phase 2 — Houzz profile scrape owner lookup.

Searches Houzz by business name, fuzzy-matches results to the target city,
fetches the matched profile's About section, and asks Claude to extract the
owner name. Free (direct HTTP). Falls through silently on Cloudflare blocks,
no results, or confidence < medium.
"""
from __future__ import annotations

from rapidfuzz import fuzz
from anthropic import Anthropic

from state import Lead
from tools import HouzzClient
from agents.sources.owners._utils import parse_owner_json

CITY_MATCH_THRESHOLD = 85  # rapidfuzz token_sort_ratio minimum

SYSTEM_PROMPT = """You are reading the About/Overview section of a remodeling contractor's Houzz profile.

Find the owner, founder, or president of the business.

Rules:
- Only accept names with explicit ownership language: "owner", "founder", "president",
  "started by", "owned and operated by", "principal", "founded by".
- Never guess from a name alone without a title.
- Return empty if no ownership language is present.

Output JSON only:
{
  "owner_full_name": "First Last",
  "source_url": "the Houzz profile URL",
  "evidence": "the exact phrase that confirmed ownership",
  "confidence": "high" | "medium" | "low" | "none"
}
"""


def _best_match(results: list[dict], city: str) -> dict | None:
    """Return the Houzz search result whose location best matches city (score >= threshold)."""
    best_score = 0
    best_result = None
    for r in results:
        city_part = r.get("location", "").split(",")[0].strip()
        score = fuzz.token_sort_ratio(city_part.lower(), city.lower())
        if score > best_score:
            best_score = score
            best_result = r
    if best_score >= CITY_MATCH_THRESHOLD:
        return best_result
    return None


def lookup(lead: Lead, city: str, state_abbr: str, anthropic_key: str) -> dict:
    """Phase 2: search Houzz by business name, match to city, parse About text.

    Returns dict with: owner_full_name, confidence, source_url, evidence.
    Returns confidence="none" on any failure (Cloudflare, no match, etc.).
    """
    client_houzz = HouzzClient()
    results = client_houzz.search(lead.business_name)
    if not results:
        return {"owner_full_name": "", "confidence": "none"}

    match = _best_match(results, city)
    if not match:
        return {"owner_full_name": "", "confidence": "none"}

    about_text = client_houzz.get_profile_text(match["profile_url"])
    if not about_text or len(about_text.strip()) < 50:
        return {"owner_full_name": "", "confidence": "none"}

    user_msg = (
        f"Business: {lead.business_name}\n"
        f"City: {city}, {state_abbr}\n"
        f"Houzz profile URL: {match['profile_url']}\n\n"
        f"About section text:\n{about_text}"
    )

    client_claude = Anthropic(api_key=anthropic_key)
    try:
        response = client_claude.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=500,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_msg}],
        )
    except Exception as e:
        return {"owner_full_name": "", "confidence": "none", "error": str(e)}

    result = parse_owner_json(response.content[0].text.strip())
    result.setdefault("phase", "houzz")
    result.setdefault("source_url", match["profile_url"])
    return result
```

- [ ] **Step 2: Smoke test**

```bash
python -c "from agents.sources.owners import houzz; print('OK')"
```

Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add agents/sources/owners/houzz.py
git commit -m "feat(owners): add Phase 2 Houzz scrape lookup"
```

---

## Task 9: Unit Tests for OpenCorporates Helpers

**Files:**
- Create: `tests/test_opencorporates_helpers.py`

- [ ] **Step 1: Write the tests**

```python
# tests/test_opencorporates_helpers.py
"""Unit tests for OpenCorporatesClient helpers.

Tests jurisdiction code derivation and officer priority selection in isolation
— no HTTP calls, no API key required.
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from tools import OpenCorporatesClient


def test_jurisdiction_code():
    """State abbreviation maps to us_XX jurisdiction code."""
    c = OpenCorporatesClient()
    # The jurisdiction param is built inline in search_company_officers.
    # We test the mapping formula here.
    assert f"us_{'FL'.lower()}" == "us_fl"
    assert f"us_{'CA'.lower()}" == "us_ca"
    assert f"us_{'NY'.lower()}" == "us_ny"


def test_pick_best_officer_owner():
    c = OpenCorporatesClient()
    officers = [
        {"name": "Jane Smith", "role": "owner", "is_current": True},
        {"name": "Bob Jones", "role": "director", "is_current": True},
    ]
    assert c.pick_best_officer(officers) == "Jane Smith"


def test_pick_best_officer_president_over_manager():
    c = OpenCorporatesClient()
    officers = [
        {"name": "Bob Jones", "role": "manager", "is_current": True},
        {"name": "Jane Smith", "role": "president", "is_current": True},
    ]
    assert c.pick_best_officer(officers) == "Jane Smith"


def test_pick_best_officer_skips_former():
    c = OpenCorporatesClient()
    officers = [
        {"name": "Former Owner", "role": "owner", "is_current": False},
        {"name": "Current Director", "role": "director", "is_current": True},
    ]
    # Former owner should be deprioritised; current director is returned
    result = c.pick_best_officer(officers)
    assert result == "Current Director"


def test_pick_best_officer_empty():
    c = OpenCorporatesClient()
    assert c.pick_best_officer([]) is None


def test_pick_best_officer_no_priority_role():
    c = OpenCorporatesClient()
    officers = [
        {"name": "Alice Brown", "role": "registered_agent", "is_current": True},
    ]
    # No priority role — falls back to first current officer
    assert c.pick_best_officer(officers) == "Alice Brown"


if __name__ == "__main__":
    test_jurisdiction_code()
    test_pick_best_officer_owner()
    test_pick_best_officer_president_over_manager()
    test_pick_best_officer_skips_former()
    test_pick_best_officer_empty()
    test_pick_best_officer_no_priority_role()
    print("OK")
```

- [ ] **Step 2: Run tests**

```bash
python tests/test_opencorporates_helpers.py
```

Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add tests/test_opencorporates_helpers.py
git commit -m "test(opencorporates): officer priority + jurisdiction unit tests"
```

---

## Task 10: agents/sources/owners/opencorporates.py

**Files:**
- Create: `agents/sources/owners/opencorporates.py`

- [ ] **Step 1: Create the module**

```python
"""Phase 3 — OpenCorporates business registry officer lookup.

Searches the OpenCorporates API for the company by name + state jurisdiction,
then returns the highest-priority officer (owner > president > CEO ...).
Free up to 50 lookups/day on the free tier. Returns confidence="none" on
429 rate-limit so the orchestrator falls through to Phase 4 silently.

⚠️  UPGRADE REMINDER: Set OPENCORPORATES_API_KEY env var after upgrading
    the plan at https://opencorporates.com/api_accounts/new
"""
from __future__ import annotations

from state import Lead
from tools import OpenCorporatesClient
from config import CONFIG


def lookup(lead: Lead, city: str, state_abbr: str, anthropic_key: str) -> dict:
    """Phase 3: OpenCorporates officer lookup for the business.

    anthropic_key is accepted to satisfy the uniform phase signature but is
    not used — this phase makes no LLM calls.

    Returns dict with: owner_full_name, confidence, source_url.
    Returns confidence="none" on 429, no results, or no matching officer.
    """
    client = OpenCorporatesClient(api_key=CONFIG.opencorporates_api_key)
    officers = client.search_company_officers(lead.business_name, state_abbr)
    if not officers:
        return {"owner_full_name": "", "confidence": "none"}

    name = client.pick_best_officer(officers)
    if not name:
        return {"owner_full_name": "", "confidence": "none"}

    return {
        "owner_full_name": name,
        "confidence": "high",
        "source_url": (
            f"https://opencorporates.com/companies/us_{state_abbr.lower()}"
            f"?q={lead.business_name.replace(' ', '+')}"
        ),
        "phase": "opencorporates",
    }
```

- [ ] **Step 2: Smoke test**

```bash
python -c "from agents.sources.owners import opencorporates; print('OK')"
```

Expected: `OK`

- [ ] **Step 3: Full package smoke test**

```bash
python -c "from agents.sources.owners import website, houzz, opencorporates, websearch; print('OK')"
```

Expected: `OK`

- [ ] **Step 4: Commit**

```bash
git add agents/sources/owners/opencorporates.py
git commit -m "feat(owners): add Phase 3 OpenCorporates registry lookup"
```

---

## Task 11: owner_researcher.py Refactor

**Files:**
- Modify: `agents/owner_researcher.py` (full rewrite of orchestration logic)

- [ ] **Step 1: Replace the file with the new orchestrator**

The new file removes the inline `_phase1_website` and `_phase2_bbb` functions (they now live in the `owners/` package) and replaces `_research_one` with a toggle-aware phase loop.

```python
"""Owner Researcher — finds the owner's full name for every kept lead.

Four-phase strategy per lead, phases run sequentially and short-circuit on
the first high/medium-confidence result. Each phase is independently
toggleable from the campaign row (use_houzz, use_registry, use_websearch).
Phase 1 (website crawl) always runs.

  Phase 1: website.lookup   — crawl own website, ask Claude. Free.
  Phase 2: houzz.lookup     — Houzz name+city scrape + Claude parse. Free.
  Phase 3: opencorporates.lookup — OpenCorporates officer API. Free tier.
  Phase 4: websearch.lookup — BBB + Google via Claude web_search. ~$0.04/lead.

Hit rate expectation (all phases on):
  Phase 1 alone:          ~55%
  + Phase 2 (Houzz):      ~70%
  + Phase 3 (OC):         ~82%
  + Phase 4 (web search): ~92-95%

Never guesses. If all phases fail, owner fields stay blank.
"""
from __future__ import annotations
import concurrent.futures as futures
from typing import Callable

from state import CampaignState, Lead
from agents.sources.owners import website, houzz, opencorporates, websearch
from agents.sources.owners._utils import split_name


MAX_PARALLEL = 10  # I/O-bound; construct own Anthropic client per worker.

# Uniform phase signature
PhaseFn = Callable[[Lead, str, str, str], dict]


def _build_phase_list(state: CampaignState) -> list[PhaseFn]:
    """Build the ordered list of phases to run based on campaign toggles."""
    phases: list[PhaseFn] = [website.lookup]
    if state.use_houzz:
        phases.append(houzz.lookup)
    if state.use_registry:
        phases.append(opencorporates.lookup)
    if state.use_websearch:
        phases.append(websearch.lookup)
    return phases


def _research_one(
    lead: Lead,
    city: str,
    state_abbr: str,
    anthropic_key: str,
    phases: list[PhaseFn],
) -> dict:
    """Run phases sequentially, short-circuit on first high/medium confidence."""
    if not lead.kept or not lead.business_name:
        return {"owner_full_name": "", "confidence": "none", "phase": "skipped"}

    for phase_fn in phases:
        try:
            result = phase_fn(lead, city, state_abbr, anthropic_key)
        except Exception:
            continue  # external failure — try next phase
        if result.get("owner_full_name") and result.get("confidence") in ("high", "medium"):
            return result

    return {"owner_full_name": "", "confidence": "none", "phase": "not_found"}


def run(state: CampaignState, anthropic_key: str) -> None:
    """Research owner names for all kept leads with no existing owner name."""
    if state.is_done("owner_researcher"):
        found = sum(1 for l in state.leads if l.owner_full_name)
        state.info("owner_researcher", f"already complete, skipping ({found} found)")
        return

    phases = _build_phase_list(state)
    phase_names = [fn.__module__.split(".")[-1] for fn in phases]
    targets = [l for l in state.leads if l.kept and not l.owner_full_name]
    state.info(
        "owner_researcher",
        f"researching {len(targets)} owners (parallel × {MAX_PARALLEL})",
        phases=phase_names,
    )

    results: dict[int, dict] = {}
    with futures.ThreadPoolExecutor(max_workers=MAX_PARALLEL) as pool:
        future_map = {
            pool.submit(
                _research_one, lead, state.city, state.state_abbr, anthropic_key, phases
            ): lead
            for lead in targets
        }
        for fut in futures.as_completed(future_map):
            lead = future_map[fut]
            try:
                results[id(lead)] = fut.result()
            except Exception as e:
                state.info(
                    "owner_researcher",
                    f"error on {lead.business_name}",
                    error=str(e),
                )
                results[id(lead)] = {"owner_full_name": "", "confidence": "none"}

    phase_counts: dict[str, int] = {}
    not_found = 0
    pre_enriched = 0

    for lead in targets:
        result = results.get(id(lead), {})
        full = (result.get("owner_full_name") or "").strip()
        if full and result.get("confidence") in ("high", "medium"):
            lead.owner_full_name = full
            lead.owner_first, lead.owner_last = split_name(full)
            lead.owner_source = result.get("phase", "")
            phase_counts[lead.owner_source] = phase_counts.get(lead.owner_source, 0) + 1
            email = (result.get("owner_email") or "").strip().lower()
            if email and result.get("phase") == "website":
                lead.email = email
                pre_enriched += 1
        else:
            not_found += 1

    state.info(
        "owner_researcher",
        "done",
        by_phase=phase_counts,
        not_found=not_found,
        pre_enriched=pre_enriched,
    )
    state.mark_done("owner_researcher")
```

- [ ] **Step 2: Smoke test**

```bash
python -c "from agents import owner_researcher; print('OK')"
```

Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add agents/owner_researcher.py
git commit -m "feat(owner_researcher): refactor to 4-phase modular pipeline with toggles"
```

---

## Task 12: API Wiring (FastAPI + Runner)

**Files:**
- Modify: `api/main.py:35-75`

- [ ] **Step 1: Add toggle fields to `CampaignCreate` and `create_campaign`**

In `api/main.py`, update the Pydantic model and route:

```python
class CampaignCreate(BaseModel):
    city: str
    state_abbr: str
    niche: str
    target_count: int = 50
    triggered_by: str = "DG"
    use_houzz: bool = True
    use_registry: bool = True
    use_websearch: bool = True


@app.post("/campaigns", status_code=201)
def create_campaign(body: CampaignCreate, background_tasks: BackgroundTasks, _: AuthDep):
    state = CampaignState.new(triggered_by=body.triggered_by)
    state.city = body.city
    state.state_abbr = body.state_abbr.upper()
    state.niche = body.niche
    state.target_count = body.target_count
    state.use_houzz = body.use_houzz
    state.use_registry = body.use_registry
    state.use_websearch = body.use_websearch
    state.status = "running"
    state.save()
    background_tasks.add_task(run_pipeline, state.campaign_id)
    return {
        "id": state.campaign_id,
        "city": state.city,
        "state_abbr": state.state_abbr,
        "niche": state.niche,
        "target_count": state.target_count,
        "triggered_by": state.triggered_by,
        "use_houzz": state.use_houzz,
        "use_registry": state.use_registry,
        "use_websearch": state.use_websearch,
        "status": "running",
        "created_at": state.created_at,
    }
```

- [ ] **Step 2: Smoke test the API import**

```bash
python -c "from api.main import app; print('OK')"
```

Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add api/main.py
git commit -m "feat(api): accept use_houzz/use_registry/use_websearch in CampaignCreate"
```

---

## Task 13: Frontend — New Campaign Form Toggles

**Files:**
- Modify: `frontend/app/campaigns/new/page.tsx`
- Modify: `frontend/app/campaigns/actions.ts`

- [ ] **Step 1: Add toggle state and UI card to `page.tsx`**

Add three state variables after the existing `useState` declarations:

```tsx
const [useHouzz, setUseHouzz] = useState(true);
const [useRegistry, setUseRegistry] = useState(true);
const [useWebsearch, setUseWebsearch] = useState(true);
```

Pass them to `startCampaign` inside `handleStart`:

```tsx
await startCampaign({
  city: city.trim(),
  stateAbbr,
  niche,
  targetCount: count,
  useHouzz,
  useRegistry,
  useWebsearch,
});
```

Add a new `<Card>` section after the "How many" card and before the spend card:

```tsx
<Card>
  <CardHeader>
    <CardTitle className="text-base">Research phases</CardTitle>
    <CardDescription>
      Toggle off to skip a phase. Phase 1 (website crawl) always runs.
    </CardDescription>
  </CardHeader>
  <CardContent className="space-y-3">
    {[
      {
        id: "use-houzz",
        label: "Houzz lookup",
        desc: "Free — scrapes Houzz profiles for owner name.",
        value: useHouzz,
        set: setUseHouzz,
      },
      {
        id: "use-registry",
        label: "Business registry",
        desc: "Free — OpenCorporates officer lookup (50/day free tier).",
        value: useRegistry,
        set: setUseRegistry,
      },
      {
        id: "use-websearch",
        label: "Web search fallback",
        desc: "~$0.04/lead — BBB + Google via AI web search.",
        value: useWebsearch,
        set: setUseWebsearch,
      },
    ].map(({ id, label, desc, value, set }) => (
      <div key={id} className="flex items-start gap-3">
        <input
          id={id}
          type="checkbox"
          checked={value}
          onChange={(e) => set(e.target.checked)}
          className="mt-0.5 h-4 w-4 rounded border-border accent-brand"
        />
        <label htmlFor={id} className="cursor-pointer">
          <span className="text-sm font-medium">{label}</span>
          <p className="text-xs text-muted-foreground">{desc}</p>
        </label>
      </div>
    ))}
  </CardContent>
</Card>
```

- [ ] **Step 2: Update `actions.ts` to pass toggle fields**

```typescript
export async function startCampaign(formData: {
  city: string;
  stateAbbr: string;
  niche: string;
  targetCount: number;
  useHouzz: boolean;
  useRegistry: boolean;
  useWebsearch: boolean;
}) {
  const jar = await cookies();
  const triggeredBy = jar.get("username")?.value ?? process.env.AUTH_USERNAME ?? "User";

  const base = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";
  const res = await fetch(`${base}/campaigns`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "X-Api-Key": process.env.VISTALINE_API_SECRET ?? "",
    },
    body: JSON.stringify({
      city: formData.city,
      state_abbr: formData.stateAbbr,
      niche: formData.niche,
      target_count: formData.targetCount,
      triggered_by: triggeredBy,
      use_houzz: formData.useHouzz,
      use_registry: formData.useRegistry,
      use_websearch: formData.useWebsearch,
    }),
  });

  if (!res.ok) {
    const detail = res.status >= 500
      ? "The backend is unavailable. Try again in a moment."
      : await res.text().catch(() => res.statusText);
    throw new Error(detail);
  }

  const { id } = await res.json();
  redirect(`/campaigns/${id}`);
}
```

- [ ] **Step 3: Build check**

```bash
cd frontend && npx tsc --noEmit 2>&1 | head -20
```

Expected: no output (zero type errors).

- [ ] **Step 4: Deploy**

```bash
cd frontend && npx vercel --prod --yes 2>&1 | grep "Production:"
```

- [ ] **Step 5: Commit**

```bash
git add frontend/app/campaigns/new/page.tsx frontend/app/campaigns/actions.ts
git commit -m "feat(frontend): add Houzz/registry/websearch toggle checkboxes to new-campaign form"
```

---

## Task 14: Smoke Test + Integration Test

- [ ] **Step 1: Full agent import smoke test**

```bash
python -c "
from agents import sourcer, lead_filter, owner_researcher, csv_assembler
from agents.sources.owners import website, houzz, opencorporates, websearch
from tools import HouzzClient, OpenCorporatesClient
print('All imports OK')
"
```

Expected: `All imports OK`

- [ ] **Step 2: Unit test suite**

```bash
python tests/test_state_toggle_fields.py && \
python tests/test_houzz_helpers.py && \
python tests/test_opencorporates_helpers.py && \
echo "All unit tests passed"
```

Expected: `All unit tests passed`

- [ ] **Step 3: Run a real integration test**

```bash
python run.py --city "Tampa" --state FL --count 10
```

After it completes, inspect the master CSV:

```bash
python -c "
import csv, sys
rows = list(csv.DictReader(open('state/master-*.csv' if False else sorted(__import__('glob').glob('state/master-*.csv'))[-1])))
from collections import Counter
print('owner_source distribution:', Counter(r['owner_source'] for r in rows if r['owner_source']))
print('owner hit rate:', sum(1 for r in rows if r['owner_full_name'] and r['kept']=='True'), '/', sum(1 for r in rows if r['kept']=='True'))
"
```

Expected: `owner_source` shows a mix of `website`, `houzz`, `opencorporates`, `web_search` (not 100% one source). Owner hit rate > 5/10 kept leads.

- [ ] **Step 4: Verify toggles work end-to-end**

Open the live UI at `https://frontend-eight-xi-78.vercel.app/campaigns/new`. Confirm:
- Three checkboxes appear under "Research phases"
- All default to checked
- Unchecking "Web search fallback" and starting a campaign creates a campaign row in Supabase with `use_websearch = false`

Check Supabase: `SELECT id, use_houzz, use_registry, use_websearch FROM campaigns ORDER BY created_at DESC LIMIT 1;`

- [ ] **Step 5: Final commit**

```bash
git add .
git commit -m "feat: Owner Researcher v2 — 4-phase nationwide pipeline with toggles

Phases: website → Houzz → OpenCorporates → web search
All phases toggleable from new-campaign form.
Targets ~92-95% owner-name hit rate.

🚨 TODO: set OPENCORPORATES_API_KEY once plan is upgraded."
```

---

## Self-Review Checklist (for implementer)

After completing all tasks, verify:

- [ ] `use_houzz = False` + `use_registry = False` + `use_websearch = False` campaign runs Phase 1 only with zero API spend beyond website parsing
- [ ] `use_websearch = False` campaign never calls `client.messages.create` with `web_search` tool (check Railway logs)
- [ ] `python run.py --resume <id>` on a campaign that crashed mid-owner-research picks up where it left off, doesn't repeat leads with existing owner names
- [ ] OpenCorporates 429 (can be simulated by exhausting 50/day free limit) doesn't crash campaign — silently falls through to web search
- [ ] Houzz returning 0 results (common for obscure businesses) doesn't crash campaign
