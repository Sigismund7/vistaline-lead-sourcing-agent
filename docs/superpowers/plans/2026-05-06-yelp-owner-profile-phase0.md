# Yelp Owner Profile Scraping — Phase 0 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a free Phase 0 to `owner_researcher.py` that scrapes the "Business Owner" labeled field from Yelp profile pages for all leads (not just Yelp-sourced), improving owner hit rate before the website crawl runs.

**Architecture:** A new `yelp_id` field on `Lead` stores the Yelp business alias. During sourcing, `yelp_id` is populated automatically for any lead where Yelp data is available. At owner-research time, `yelp_profile.lookup()` uses the cached `yelp_id` if present; for Azure-only leads it searches Yelp by name+city first (one API call), then fetches the profile page via HTTP and parses the "Business Owner" labeled field with BeautifulSoup — no LLM required. All failures are silent fallthrough so a Yelp block or miss never breaks a campaign.

**Tech Stack:** Python, BeautifulSoup4 (already in requirements), rapidfuzz (already in requirements), requests (already in requirements), YelpFusionClient (already in `tools.py`)

---

## File Structure

| File | Change |
|---|---|
| `state.py` | Add `yelp_id: str = ""` to `Lead`; update `save_leads()` and `load()` to persist it |
| `agents/sourcer.py` | Set `yelp_id` in `_to_lead()` from Yelp alias where available |
| `agents/sources/owners/yelp_profile.py` | **New.** Phase 0 lookup: search Yelp if no alias, fetch profile page, parse "Business Owner" field |
| `agents/owner_researcher.py` | Insert `yelp_profile.lookup` as Phase 0 before website crawl |
| `tests/test_yelp_profile_parser.py` | **New.** Unit tests for the HTML-parsing helpers with fixture HTML snippets |

### Schema migration (run once in Supabase SQL editor)

```sql
ALTER TABLE leads ADD COLUMN IF NOT EXISTS yelp_id TEXT NOT NULL DEFAULT '';
```

---

## Task 1: Add `yelp_id` to Lead and persist it

**Files:**
- Modify: `state.py`
- Test: `tests/test_yelp_id_state.py`

### Context for implementer

`Lead` is a `@dataclass` in `state.py`. New fields go after the existing `email` field. `save_leads()` builds a `rows` list of dicts — add `"yelp_id": l.yelp_id` to each row dict. `load()` builds `Lead(...)` from DB rows — add `yelp_id=r.get("yelp_id", "") or ""`. The Supabase schema migration (`ALTER TABLE leads ADD COLUMN IF NOT EXISTS yelp_id TEXT NOT NULL DEFAULT ''`) must be run manually by the operator before deploying; the code change itself is safe before or after.

- [ ] **Step 1: Write the failing test**

Create `tests/test_yelp_id_state.py`:

```python
"""Test that yelp_id survives the Lead dataclass round-trip."""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from state import Lead


def test_yelp_id_defaults_to_empty():
    lead = Lead(business_name="ABC Bath")
    assert lead.yelp_id == ""


def test_yelp_id_stores_value():
    lead = Lead(business_name="ABC Bath", yelp_id="abc-bath-orlando")
    assert lead.yelp_id == "abc-bath-orlando"


def test_lead_fields_not_accidentally_removed():
    # Regression: make sure existing fields still exist after adding yelp_id
    lead = Lead(
        business_name="ABC Bath",
        phone="4075550101",
        website="https://abcbath.com",
        owner_full_name="Jane Smith",
        email="jane@abcbath.com",
        yelp_id="abc-bath-orlando",
    )
    assert lead.business_name == "ABC Bath"
    assert lead.email == "jane@abcbath.com"
    assert lead.yelp_id == "abc-bath-orlando"


if __name__ == "__main__":
    test_yelp_id_defaults_to_empty()
    test_yelp_id_stores_value()
    test_lead_fields_not_accidentally_removed()
    print("OK")
```

- [ ] **Step 2: Run test to verify it fails**

```bash
python tests/test_yelp_id_state.py
```

Expected: `AttributeError: 'Lead' object has no attribute 'yelp_id'` or `TypeError`

- [ ] **Step 3: Add `yelp_id` to Lead dataclass**

In `state.py`, find the `email: str = ""` line (currently the last owner-researcher field, around line 44). Add `yelp_id` immediately after it:

```python
    email: str = ""
    yelp_id: str = ""
    # Personalization (post-FindyMail). Empty string means "not run yet".
```

- [ ] **Step 4: Add `yelp_id` to `save_leads()` row dict**

In `state.py`, find the `rows = [...]` list comprehension in `save_leads()`. The last field in the per-lead dict is currently `"personalization_status": l.personalization_status`. Add `yelp_id` after `email`:

```python
                "email": l.email,
                "yelp_id": l.yelp_id,
                "x_project": l.x_project,
```

- [ ] **Step 5: Add `yelp_id` to `load()` Lead construction**

In `state.py`, find the `Lead(...)` constructor call inside `load()`. After `email=r["email"],` add:

```python
                email=r["email"],
                yelp_id=r.get("yelp_id", "") or "",
                x_project=r.get("x_project", "") or "",
```

- [ ] **Step 6: Run test to verify it passes**

```bash
python tests/test_yelp_id_state.py
```

Expected: `OK`

- [ ] **Step 7: Smoke import test**

```bash
python -c "from agents import sourcer, lead_filter, owner_researcher, csv_assembler; print('OK')"
```

Expected: `OK`

- [ ] **Step 8: Commit**

```bash
git add state.py tests/test_yelp_id_state.py
git commit -m "feat: add yelp_id field to Lead for Yelp owner profile phase"
```

---

## Task 2: Populate `yelp_id` during sourcing

**Files:**
- Modify: `agents/sourcer.py:218-242` (the `_to_lead()` function)
- Test: `tests/test_yelp_id_in_sourcer.py`

### Context for implementer

`_to_lead(normalized)` converts a 9-key raw dict from either Azure or Yelp into a `Lead`. The `normalized` dict always has a `"source"` key set by the adapter:
- `"yelp_fusion"` → `source_id` is the Yelp business alias (e.g., `"andrews-bath-orlando"`)
- `"azure_maps"` → `source_id` is the Azure POI ID (a UUID-like string, not a Yelp alias)
- `"azure_maps+yelp_fusion"` → `source_id` is the Azure POI ID, but `raw_yelp` holds the full raw Yelp dict whose `"id"` key is the Yelp alias

The goal: populate `yelp_id` when the Yelp alias is available in the raw dict, without any API calls. This is purely dict-key extraction.

- [ ] **Step 1: Write the failing test**

Create `tests/test_yelp_id_in_sourcer.py`:

```python
"""Test that _to_lead populates yelp_id correctly by source."""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agents.sourcer import _to_lead


def _yelp_lead(alias: str) -> dict:
    return {
        "source": "yelp_fusion",
        "source_id": alias,
        "business_name": "ABC Bath",
        "address": "123 Main St, Orlando, FL",
        "phone": "+14075550101",
        "website": "",
        "lat": 28.5,
        "lon": -81.4,
        "raw": {"id": alias, "name": "ABC Bath"},
    }


def _azure_lead() -> dict:
    return {
        "source": "azure_maps",
        "source_id": "deadbeef-1234",
        "business_name": "XYZ Remodeling",
        "address": "456 Elm St, Orlando, FL",
        "phone": "+14075550202",
        "website": "https://xyz.com",
        "lat": 28.5,
        "lon": -81.4,
        "raw": {},
    }


def _merged_lead(azure_id: str, yelp_alias: str) -> dict:
    return {
        "source": "azure_maps+yelp_fusion",
        "source_id": azure_id,
        "business_name": "MNO Kitchen",
        "address": "789 Oak Ave, Orlando, FL",
        "phone": "+14075550303",
        "website": "https://mno.com",
        "lat": 28.5,
        "lon": -81.4,
        "raw": {},
        "raw_yelp": {"id": yelp_alias, "name": "MNO Kitchen"},
    }


def test_yelp_sourced_lead_gets_yelp_id():
    lead = _to_lead(_yelp_lead("abc-bath-orlando"))
    assert lead.yelp_id == "abc-bath-orlando"


def test_azure_only_lead_has_empty_yelp_id():
    lead = _to_lead(_azure_lead())
    assert lead.yelp_id == ""


def test_merged_lead_gets_yelp_id_from_raw_yelp():
    lead = _to_lead(_merged_lead("deadbeef-5678", "mno-kitchen-orlando"))
    assert lead.yelp_id == "mno-kitchen-orlando"


def test_merged_lead_without_raw_yelp_has_empty_yelp_id():
    raw = _merged_lead("deadbeef-5678", "mno-kitchen-orlando")
    del raw["raw_yelp"]
    lead = _to_lead(raw)
    assert lead.yelp_id == ""


if __name__ == "__main__":
    test_yelp_sourced_lead_gets_yelp_id()
    test_azure_only_lead_has_empty_yelp_id()
    test_merged_lead_gets_yelp_id_from_raw_yelp()
    test_merged_lead_without_raw_yelp_has_empty_yelp_id()
    print("OK")
```

- [ ] **Step 2: Run test to verify it fails**

```bash
python tests/test_yelp_id_in_sourcer.py
```

Expected: `AssertionError` — `lead.yelp_id` will be `""` even for Yelp-sourced leads until we add the logic.

- [ ] **Step 3: Update `_to_lead()` to populate `yelp_id`**

In `agents/sourcer.py`, find the `_to_lead()` function. Replace the `return Lead(...)` call (it currently ends with `place_id=normalized.get("source_id", "") or "",`). Add `yelp_id` extraction before the return and pass it in:

```python
def _to_lead(normalized: dict) -> Lead:
    """Convert a 9-key normalized source dict into a `Lead` dataclass.

    `place_id` is mapped from `source_id` (legacy field name; `Lead` was
    designed when Google Places was the only source). `domain` and
    `area_code` are derived helpers consistent with the pre-Cycle-4 sourcer.
    `yelp_id` is the Yelp business alias, available when the source includes
    Yelp data — used by the yelp_profile owner-research phase.

    Defensive contract: optional fields (phone, website, address, lat, lon,
    raw) default to empty strings when missing — a buggy adapter returning
    a partial dict shouldn't crash the router. `business_name` and
    `source_id` are also resolved via `.get(..., "")` so a fully-malformed
    dict produces an empty-string Lead rather than a `KeyError`; callers
    should still treat them as required and surface upstream if absent.
    """
    website = normalized.get("website", "") or ""
    phone = normalized.get("phone", "") or ""
    source = normalized.get("source", "")

    # Determine Yelp alias. Yelp-only leads carry it as source_id.
    # Merged leads carry the Azure ID as source_id but the Yelp raw dict
    # is attached as raw_yelp by the merge step in _merge_sources().
    if source == "yelp_fusion":
        yelp_id = normalized.get("source_id", "") or ""
    elif source == "azure_maps+yelp_fusion":
        yelp_id = (normalized.get("raw_yelp") or {}).get("id", "") or ""
    else:
        yelp_id = ""

    return Lead(
        business_name=normalized.get("business_name", "") or "",
        phone=phone,
        website=website,
        address=normalized.get("address", "") or "",
        area_code=_area_code(phone),
        domain=_normalize_domain(website),
        place_id=normalized.get("source_id", "") or "",
        yelp_id=yelp_id,
    )
```

- [ ] **Step 4: Run test to verify it passes**

```bash
python tests/test_yelp_id_in_sourcer.py
```

Expected: `OK`

- [ ] **Step 5: Smoke import test**

```bash
python -c "from agents import sourcer, lead_filter, owner_researcher, csv_assembler; print('OK')"
```

Expected: `OK`

- [ ] **Step 6: Commit**

```bash
git add agents/sourcer.py tests/test_yelp_id_in_sourcer.py
git commit -m "feat: populate yelp_id in sourcer for Yelp-sourced and merged leads"
```

---

## Task 3: Implement `yelp_profile.py` — the Phase 0 lookup

**Files:**
- Create: `agents/sources/owners/yelp_profile.py`
- Test: `tests/test_yelp_profile_parser.py`

### Context for implementer

This module has one job: given a lead, return `{owner_full_name, confidence, phase, source_url}` by checking the Yelp profile page. It NEVER crashes the pipeline — all failures return `confidence="none"`.

**Two-step execution:**

**Step A — Resolve Yelp alias (if not already known):**
- If `lead.yelp_id` is already set (from sourcing), skip the API search entirely.
- Otherwise call `YelpFusionClient.search_businesses(term=lead.business_name, location=f"{city}, {state_abbr}", limit=5, categories="contractors,kitchen_and_bath,homeservices")` and pick the best fuzzy match using `rapidfuzz.fuzz.token_sort_ratio`. Accept the top result if score ≥ 85. Set `lead.yelp_id` in-memory so that `--resume` checkpointing (which calls `state.save_leads()` after every lead) persists it.
- If no match found, return `confidence="none"`.

**Step B — Scrape the profile page:**
- Fetch `https://www.yelp.com/biz/{yelp_id}` with a Chrome User-Agent: `"Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"`. Timeout 15s.
- If status 403 or any error, return `confidence="none"` silently.
- Parse with BeautifulSoup. Look for the text `"Business Owner"` anywhere on the page. The owner name appears in the adjacent element.
- Two parsing strategies (try both, first match wins):
  1. **JSON-LD structured data:** many Yelp pages embed `<script type="application/ld+json">` with schema.org markup. Parse all such scripts; look for `{"@type": "Person", "jobTitle": "Business Owner", "name": "..."}` or similar.
  2. **HTML text pattern:** find all text nodes or `<p>`, `<span>`, `<div>` elements whose `.get_text()` contains `"Business Owner"`. From the parent container extract the sibling text that is NOT `"Business Owner"` — that is the name.
- A successful match returns `confidence="high"` (the field is explicitly labeled on Yelp, not inferred).
- If neither strategy finds the name, return `confidence="none"`.

**Function signature** (must match the `PhaseFn` type in `owner_researcher.py`):
```python
def lookup(lead: Lead, city: str, state_abbr: str, anthropic_key: str) -> dict:
```
`anthropic_key` is accepted but not used — Phase 0 is free, no LLM calls.

- [ ] **Step 1: Write failing tests for the HTML parser**

Create `tests/test_yelp_profile_parser.py`:

```python
"""Unit tests for Yelp profile page parsing helpers.

Tests use fixture HTML snippets — no network calls.
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# We test the internal helpers before wiring them into the module.
# Once the module exists, import from it directly.


def _parse_from_jsonld(html: str) -> str | None:
    """Extract owner name from JSON-LD structured data."""
    import json
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(tag.string or "")
        except (json.JSONDecodeError, TypeError):
            continue
        # Handle both a single dict and a list of dicts
        items = data if isinstance(data, list) else [data]
        for item in items:
            if isinstance(item, dict):
                # Check for Person with Business Owner job title
                if (item.get("@type") == "Person"
                        and "owner" in (item.get("jobTitle") or "").lower()
                        and item.get("name")):
                    return item["name"].strip()
    return None


def _parse_from_html(html: str) -> str | None:
    """Extract owner name from HTML 'Business Owner' label pattern."""
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(html, "html.parser")
    # Walk all tags; find those whose direct text contains "Business Owner"
    for tag in soup.find_all(True):
        text = tag.get_text(separator=" ", strip=True)
        if "Business Owner" in text:
            # Try to get name from a sibling or child that isn't the label
            for part in text.split("\n"):
                part = part.strip()
                if part and part != "Business Owner" and len(part.split()) >= 2:
                    return part
    return None


# --- JSON-LD tests ---

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


def test_jsonld_extracts_owner_name():
    name = _parse_from_jsonld(JSONLD_HTML)
    assert name == "Manuel Hernández A.", f"got {name!r}"


def test_jsonld_returns_none_when_no_person():
    name = _parse_from_jsonld(JSONLD_HTML_NO_OWNER)
    assert name is None


def test_jsonld_returns_none_on_empty_html():
    name = _parse_from_jsonld("<html></html>")
    assert name is None


# --- HTML text-pattern tests ---

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


def test_html_pattern_extracts_owner():
    name = _parse_from_html(HTML_PATTERN)
    assert name is not None
    assert "John Smith" in name or "Smith" in name, f"got {name!r}"


def test_html_pattern_returns_none_when_no_label():
    name = _parse_from_html(HTML_NO_OWNER)
    assert name is None


if __name__ == "__main__":
    test_jsonld_extracts_owner_name()
    test_jsonld_returns_none_when_no_person()
    test_jsonld_returns_none_on_empty_html()
    test_html_pattern_extracts_owner()
    test_html_pattern_returns_none_when_no_label()
    print("OK")
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
python tests/test_yelp_profile_parser.py
```

Expected: All tests fail because the functions don't exist yet in a module. (The test file defines them locally for now — they should pass. Run it and confirm `OK` before proceeding; if any assertion fails, fix the test fixture HTML.)

- [ ] **Step 3: Create `agents/sources/owners/yelp_profile.py`**

```python
"""Phase 0 — Yelp profile page owner lookup.

Checks the 'Business Owner' labeled field in Yelp's 'About the Business'
section. Free: no LLM calls. The Yelp Fusion API is used only to resolve
the Yelp business alias for leads that weren't sourced from Yelp.

Failure modes: all silent fallthrough. A 403 block, no search results, or
a missing 'Business Owner' field all return confidence='none' so the
pipeline continues to Phase 1 (website crawl).
"""
from __future__ import annotations

import json
import time
import random

import requests
from bs4 import BeautifulSoup
from rapidfuzz import fuzz

from state import Lead
from tools import YelpFusionClient

# Realistic browser User-Agent. Yelp uses Cloudflare; a bare Python UA
# gets blocked immediately.
_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)
_HEADERS = {
    "User-Agent": _USER_AGENT,
    "Accept-Language": "en-US,en;q=0.9",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}

_SEARCH_CATEGORIES = "contractors,kitchen_and_bath,homeservices"
_FUZZY_THRESHOLD = 85
_PAGE_FETCH_TIMEOUT_S = 15


def _resolve_yelp_id(lead: Lead, city: str, state_abbr: str, yelp_key: str) -> str | None:
    """Return Yelp business alias for this lead.

    Uses lead.yelp_id directly if already set (no API call). Otherwise
    searches Yelp by business name + city and fuzzy-matches the top results.
    Writes the found alias back to lead.yelp_id in-memory so --resume
    (which checkpoints via state.save_leads()) skips the search next time.
    """
    if lead.yelp_id:
        return lead.yelp_id

    if not yelp_key:
        return None

    try:
        client = YelpFusionClient(api_key=yelp_key, rate_limit_qps=1.0, jitter_ms=200)
        results = client.search_businesses(
            term=lead.business_name,
            location=f"{city}, {state_abbr}",
            categories=_SEARCH_CATEGORIES,
            limit=5,
        )
    except Exception:
        return None

    best_alias: str | None = None
    best_score = 0
    for biz in results:
        result_name = biz.get("name") or ""
        score = fuzz.token_sort_ratio(lead.business_name.lower(), result_name.lower())
        if score > best_score:
            best_score = score
            best_alias = biz.get("id") or None

    if best_score >= _FUZZY_THRESHOLD and best_alias:
        lead.yelp_id = best_alias  # cache for --resume checkpointing
        return best_alias

    return None


def _fetch_yelp_page(yelp_id: str) -> str | None:
    """Fetch the Yelp business profile page HTML.

    Returns None on any HTTP error or timeout so callers can silently
    fall through to the next owner-research phase.
    """
    url = f"https://www.yelp.com/biz/{yelp_id}"
    # Brief random delay to avoid hammering Yelp when multiple leads
    # are researched in parallel. Each parallel worker calls this
    # independently so the aggregate rate is MAX_PARALLEL * this delay.
    time.sleep(random.uniform(0.5, 1.5))
    try:
        resp = requests.get(url, headers=_HEADERS, timeout=_PAGE_FETCH_TIMEOUT_S)
    except requests.RequestException:
        return None

    if resp.status_code in (403, 429, 503):
        return None
    if not resp.ok:
        return None

    return resp.text


def _parse_owner_from_jsonld(html: str) -> str | None:
    """Extract owner name from JSON-LD structured data embedded in page.

    Yelp embeds schema.org Person entities for business owners in some
    markets. Returns None when no Person with an owner-role jobTitle is found.
    """
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(tag.string or "")
        except (json.JSONDecodeError, TypeError):
            continue
        items = data if isinstance(data, list) else [data]
        for item in items:
            if not isinstance(item, dict):
                continue
            if (item.get("@type") == "Person"
                    and "owner" in (item.get("jobTitle") or "").lower()
                    and item.get("name")):
                return item["name"].strip()
    return None


def _parse_owner_from_html(html: str) -> str | None:
    """Extract owner name from the 'Business Owner' label in the page HTML.

    Yelp renders 'Business Owner' as a visible text label adjacent to the
    owner's name in the 'About the Business' section. We walk every element
    containing that label text and extract the adjacent non-label text.
    """
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup.find_all(True):
        direct_text = " ".join(tag.find_all(string=True, recursive=False)).strip()
        if "Business Owner" not in direct_text and "Business Owner" not in tag.get_text():
            continue

        # Collect text fragments from the containing block
        block_text = tag.get_text(separator="\n", strip=True)
        for line in block_text.split("\n"):
            line = line.strip()
            if not line:
                continue
            if line == "Business Owner":
                continue
            # Accept lines that look like a person's name: ≥2 words,
            # no digits, not a generic heading
            words = line.split()
            if len(words) >= 2 and not any(ch.isdigit() for ch in line):
                return line

    return None


def lookup(lead: Lead, city: str, state_abbr: str, anthropic_key: str) -> dict:
    """Phase 0: scrape Yelp profile page for the 'Business Owner' field.

    `anthropic_key` is accepted to satisfy the PhaseFn signature but is
    not used — this phase makes no LLM calls.

    Returns a dict with at minimum: owner_full_name (str), confidence (str).
    confidence is 'high' on a labeled Yelp match, 'none' otherwise.
    """
    import os
    yelp_key = os.environ.get("YELP_FUSION_KEY", "")

    yelp_id = _resolve_yelp_id(lead, city, state_abbr, yelp_key)
    if not yelp_id:
        return {"owner_full_name": "", "confidence": "none", "phase": "yelp_profile"}

    html = _fetch_yelp_page(yelp_id)
    if not html:
        return {"owner_full_name": "", "confidence": "none", "phase": "yelp_profile"}

    profile_url = f"https://www.yelp.com/biz/{yelp_id}"

    name = _parse_owner_from_jsonld(html)
    if not name:
        name = _parse_owner_from_html(html)

    if name:
        return {
            "owner_full_name": name,
            "confidence": "high",
            "phase": "yelp_profile",
            "source_url": profile_url,
            "evidence": "Yelp Business Owner labeled field",
        }

    return {"owner_full_name": "", "confidence": "none", "phase": "yelp_profile"}
```

- [ ] **Step 4: Update the parser test to import from the module**

Now that the module exists, update `tests/test_yelp_profile_parser.py` to import the helpers directly:

```python
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
```

- [ ] **Step 5: Run tests**

```bash
python tests/test_yelp_profile_parser.py
```

Expected: `OK`

- [ ] **Step 6: Smoke import test**

```bash
python -c "from agents.sources.owners import yelp_profile; print('OK')"
```

Expected: `OK`

- [ ] **Step 7: Commit**

```bash
git add agents/sources/owners/yelp_profile.py tests/test_yelp_profile_parser.py
git commit -m "feat: yelp_profile Phase 0 owner lookup via profile page scraping"
```

---

## Task 4: Wire `yelp_profile` as Phase 0 in `owner_researcher.py`

**Files:**
- Modify: `agents/owner_researcher.py`
- Test: `tests/test_owner_researcher_phase_order.py`

### Context for implementer

`owner_researcher.py` builds a `phases` list in `_build_phase_list()`. Currently the list always starts with `website.lookup`. We need `yelp_profile.lookup` as Phase 0 — inserted BEFORE `website.lookup`.

The `PhaseFn` type alias is `Callable[[Lead, str, str, str], dict]`. `yelp_profile.lookup` already matches this signature.

`_research_one()` runs the eponymous heuristic first (free, no network), then iterates `phases` and short-circuits on the first `confidence in ("high", "medium")`. `yelp_profile` returns `"high"` on a match, so it will correctly short-circuit before website or opencorporates run.

The `owner_source` logged in the summary and stored as `lead.owner_source` comes from `result.get("phase", "")`. `yelp_profile.lookup` sets `"phase": "yelp_profile"` in its return dict so the audit trail is clean.

There is NO new toggle for this phase — it always runs. Yelp profile scraping is free (no Anthropic spend) and silently skips when Yelp is blocked or unavailable, so there's no reason to make it optional.

- [ ] **Step 1: Write the failing test**

Create `tests/test_owner_researcher_phase_order.py`:

```python
"""Test that yelp_profile is Phase 0 (runs before website) in the phase list."""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dataclasses import dataclass, field
from agents.owner_researcher import _build_phase_list
from agents.sources.owners import yelp_profile, website, opencorporates, websearch


@dataclass
class _FakeState:
    city: str = "Orlando"
    state_abbr: str = "FL"
    use_registry: bool = True
    use_websearch: bool = True
    leads: list = field(default_factory=list)
    log: list = field(default_factory=list)
    completed_steps: list = field(default_factory=list)


def test_yelp_profile_is_first_phase():
    state = _FakeState()
    phases = _build_phase_list(state)
    assert phases[0] is yelp_profile.lookup, (
        f"Expected yelp_profile.lookup first, got {phases[0]}"
    )


def test_website_is_second_phase():
    state = _FakeState()
    phases = _build_phase_list(state)
    assert phases[1] is website.lookup


def test_opencorporates_included_when_use_registry_true():
    state = _FakeState(use_registry=True)
    phases = _build_phase_list(state)
    assert opencorporates.lookup in phases


def test_opencorporates_excluded_when_use_registry_false():
    state = _FakeState(use_registry=False)
    phases = _build_phase_list(state)
    assert opencorporates.lookup not in phases


def test_websearch_excluded_when_use_websearch_false():
    state = _FakeState(use_websearch=False)
    phases = _build_phase_list(state)
    assert websearch.lookup not in phases


def test_phase_list_minimum_length_is_two():
    # Even with all toggles off, yelp_profile + website always run
    state = _FakeState(use_registry=False, use_websearch=False)
    phases = _build_phase_list(state)
    assert len(phases) >= 2


if __name__ == "__main__":
    test_yelp_profile_is_first_phase()
    test_website_is_second_phase()
    test_opencorporates_included_when_use_registry_true()
    test_opencorporates_excluded_when_use_registry_false()
    test_websearch_excluded_when_use_websearch_false()
    test_phase_list_minimum_length_is_two()
    print("OK")
```

- [ ] **Step 2: Run test to verify it fails**

```bash
python tests/test_owner_researcher_phase_order.py
```

Expected: `AssertionError` — `phases[0]` is currently `website.lookup`, not `yelp_profile.lookup`.

- [ ] **Step 3: Update imports in `owner_researcher.py`**

In `agents/owner_researcher.py`, find the imports line:

```python
from agents.sources.owners import website, opencorporates, websearch
```

Replace with:

```python
from agents.sources.owners import yelp_profile, website, opencorporates, websearch
```

- [ ] **Step 4: Update `_build_phase_list()` to prepend `yelp_profile`**

In `agents/owner_researcher.py`, find `_build_phase_list()`. The current body is:

```python
def _build_phase_list(state: CampaignState) -> list[PhaseFn]:
    """Build the ordered list of phases to run based on campaign toggles."""
    phases: list[PhaseFn] = [website.lookup]
    if state.use_registry:
        phases.append(opencorporates.lookup)
    if state.use_websearch:
        phases.append(websearch.lookup)
    return phases
```

Replace with:

```python
def _build_phase_list(state: CampaignState) -> list[PhaseFn]:
    """Build the ordered list of phases to run based on campaign toggles.

    yelp_profile always runs first — it's free (no LLM) and silently
    falls through when Yelp is unavailable or the owner field is absent.
    """
    phases: list[PhaseFn] = [yelp_profile.lookup, website.lookup]
    if state.use_registry:
        phases.append(opencorporates.lookup)
    if state.use_websearch:
        phases.append(websearch.lookup)
    return phases
```

- [ ] **Step 5: Update the phase_names log line to include `yelp_profile`**

The `run()` function logs phase names like this:

```python
phase_names = [fn.__module__.split(".")[-1] for fn in phases]
```

This derives names from the module path automatically, so `yelp_profile.lookup` will log as `"yelp_profile"` without any manual change. Verify that line is still using `fn.__module__.split(".")[-1]` — if so, no change needed.

- [ ] **Step 6: Run tests**

```bash
python tests/test_owner_researcher_phase_order.py
```

Expected: `OK`

- [ ] **Step 7: Full smoke import test**

```bash
python -c "from agents import sourcer, lead_filter, owner_researcher, csv_assembler; print('OK')"
```

Expected: `OK`

- [ ] **Step 8: Commit**

```bash
git add agents/owner_researcher.py tests/test_owner_researcher_phase_order.py
git commit -m "feat: wire yelp_profile as Phase 0 in owner_researcher before website crawl"
```

---

## Task 5: Schema migration + integration verification

**Files:**
- No code changes — this task is operational verification.

### Context for implementer

The Supabase `leads` table needs a `yelp_id` column before the pipeline can persist the new field. Run the migration in the Supabase SQL editor. Then run a small real campaign to verify the end-to-end behavior.

- [ ] **Step 1: Run the Supabase schema migration**

In the Supabase dashboard → SQL Editor, run:

```sql
ALTER TABLE leads ADD COLUMN IF NOT EXISTS yelp_id TEXT NOT NULL DEFAULT '';
```

Confirm: no error, column appears in the `leads` table schema.

- [ ] **Step 2: Run a 5-lead smoke campaign**

From the project root (with `.venv` activated and `.env` populated):

```bash
python run.py --city "Tampa" --state FL --count 5
```

Expected behavior:
- `[owner_researcher]` log line shows `phases=['yelp_profile', 'website', 'opencorporates', 'websearch']` (or whichever are toggled on)
- Some leads log `owner_source = yelp_profile` in the master CSV if the Yelp page had the Business Owner field
- No crashes. Leads where Yelp is unavailable fall through to website crawl normally.

- [ ] **Step 3: Inspect the master CSV**

Open `output/<city>_<state>_<niche>_<date>__master.csv` and verify:
- `owner_source` column contains `yelp_profile` for at least some leads (or `website`/`web_search` for others — mix is expected)
- `yelp_id` column is NOT in the FindyMail CSV (it's internal), but should be present in Supabase

- [ ] **Step 4: Final smoke import**

```bash
python -c "from agents import sourcer, lead_filter, owner_researcher, csv_assembler; print('OK')"
```

Expected: `OK`

---

## Self-Review

### Spec coverage check

| Requirement | Task |
|---|---|
| `yelp_id` field on Lead | Task 1 |
| Yelp alias populated from sourcer for Yelp/merged leads | Task 2 |
| Profile page scraping with BeautifulSoup (JSON-LD + HTML pattern) | Task 3 |
| Yelp search by name+city for Azure-only leads | Task 3 |
| Alias cached to `lead.yelp_id` for `--resume` | Task 3 (`_resolve_yelp_id`) |
| Phase 0 wired before website in `owner_researcher` | Task 4 |
| Silent fallthrough on 403 / block / no match | Task 3 (`_fetch_yelp_page`, `_resolve_yelp_id`) |
| No LLM calls in this phase | Task 3 (no Anthropic import) |
| Supabase migration | Task 5 |
| Integration verification | Task 5 |

### Placeholder scan

No TBDs, no "add error handling" without showing it, no "similar to Task N" shortcuts.

### Type consistency

- `lookup(lead: Lead, city: str, state_abbr: str, anthropic_key: str) -> dict` — matches `PhaseFn` in `owner_researcher.py`
- `_resolve_yelp_id` returns `str | None` — used with `if not yelp_id` guard ✓
- `_parse_owner_from_jsonld` and `_parse_owner_from_html` both return `str | None` ✓
- Test imports `_parse_owner_from_jsonld`, `_parse_owner_from_html` — both defined in module ✓
