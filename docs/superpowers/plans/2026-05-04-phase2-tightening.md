# Phase 2 Tightening — Sourcer Quality Improvements

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Reduce sourcer food-business noise, prevent cross-run re-sourcing of the same leads, make owner research resumable mid-batch, and block press-release URLs from the website finder.

**Architecture:** Four targeted patches — no new agents, no new paid surfaces, no Supabase schema changes. All changes land on the `tightening` branch. Build order: 2.NEWS → 2.KW → 2.CD → 2.OR.

**Tech Stack:** Python 3.11, sqlite3 (stdlib — no new dependency), rapidfuzz (already installed), pytest (already in `.venv`).

---

## File Structure

**Create:**
- `agents/leads_cache.py` — SQLite-backed cross-run dedup module (two public functions)
- `tests/test_leads_cache.py` — 11 unit tests for the cache module

**Modify:**
- `agents/website_finder.py:32-38` — add 7 news/PR domains to `_DIRECTORY_DOMAINS`
- `agents/sources/azure_maps.py:22-43` — replace 3 keywords for `"kitchen remodelers"` + `"kitchen remodeling"`
- `agents/sources/yelp_fusion.py:44-69` — replace 4 terms, drop `None` for kitchen niches
- `agents/sourcer.py:310-320` — insert cache filter + mark calls around the append loop
- `agents/owner_researcher.py:233-282` — write result back per-lead + call `save_leads()` as checkpoint
- `config.py:72` — add `leads_cache_ttl_days: int = 30`
- `tests/test_website_finder.py` — add 1 test for prnewswire rejection
- `tests/test_source_azure_maps.py` — add 1 regression test (no bare `"kitchen"` in keywords)
- `tests/test_source_yelp_fusion.py` — add 1 regression test (no `None` in kitchen terms)
- `tests/test_sourcer.py` — add 2 tests for cache integration
- `.gitignore` — add `state/leads_cache.db`

---

## Task 0: Create the tightening branch

**Files:** none (git only)

- [ ] **Step 1: Create and switch to the tightening branch**

```bash
git checkout -b tightening
```

Expected output:
```
Switched to a new branch 'tightening'
```

- [ ] **Step 2: Verify**

```bash
git branch --show-current
```

Expected: `tightening`

---

## Task 1: 2.NEWS — Add news/PR domains to website_finder blocklist

**Files:**
- Modify: `agents/website_finder.py:32-38`
- Modify: `tests/test_website_finder.py`

Problem: `website_finder.py` Stage 2 Brave search returns press-release URLs (e.g., `prnewswire.com/ABC-Contracting-Wins-Award`) as the lead's website. The crawler then scrapes a press release instead of a business homepage. One frozenset addition fixes it.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_website_finder.py` before `if __name__ == "__main__":`:

```python
class DirectoryBlocklistTest(unittest.TestCase):
    def test_prnewswire_rejected_as_directory(self):
        """prnewswire.com is a press-release host, not a business site."""
        session = MagicMock(spec=requests.Session)
        brave = MagicMock(spec=tools.BraveSearchClient)
        brave.search_web.return_value = [
            {"title": "ABC Contracting Wins Award",
             "url": "https://www.prnewswire.com/news-releases/abc-contracting-wins-123"},
            {"title": "Real Site", "url": "https://abccontracting.com/"},
        ]

        def head_router(url, **kwargs):
            if "abccontracting.com" in url:
                return _head_resp(status_code=200, url="https://abccontracting.com/")
            raise requests.ConnectionError("nope")

        session.head.side_effect = head_router
        url = website_finder.find_website(
            "ABC Contracting", "Tampa", "FL",
            brave_client=brave, http_session=session,
        )
        # prnewswire must be skipped; real site must win.
        self.assertEqual(url, "https://abccontracting.com/")
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd "/Users/daschelgorgenyi/Desktop/Vistaline-Lead Sourcing Agent" && \
.venv/bin/python -m pytest tests/test_website_finder.py::DirectoryBlocklistTest::test_prnewswire_rejected_as_directory -v
```

Expected: FAIL — `prnewswire.com` not yet in `_DIRECTORY_DOMAINS`.

- [ ] **Step 3: Add the 7 news domains to `_DIRECTORY_DOMAINS` in `agents/website_finder.py`**

Replace lines 32-38 (the current `_DIRECTORY_DOMAINS` frozenset) with:

```python
_DIRECTORY_DOMAINS = frozenset({
    "yelp.com", "bbb.org", "angi.com", "homeadvisor.com", "houzz.com",
    "facebook.com", "instagram.com", "linkedin.com", "mapquest.com",
    "yellowpages.com", "manta.com", "thumbtack.com", "porch.com",
    "nextdoor.com", "google.com", "maps.google.com", "twitter.com",
    "x.com", "youtube.com", "pinterest.com",
    # News and press-release hosts — Brave returns these for contractors
    # mentioned in awards/permits coverage. Not business homepages.
    "businessinsider.com", "prnewswire.com", "prweb.com",
    "globenewswire.com", "accesswire.com", "einpresswire.com",
    "newswire.com",
})
```

- [ ] **Step 4: Run all website_finder tests**

```bash
.venv/bin/python -m pytest tests/test_website_finder.py -v
```

Expected: all tests PASS including the new one.

- [ ] **Step 5: Import smoke test**

```bash
.venv/bin/python -c "from agents import website_finder; print('OK')"
```

Expected: `OK`

- [ ] **Step 6: Commit**

```bash
git add agents/website_finder.py tests/test_website_finder.py
git commit -m "fix(website_finder): add news/PR domains to directory blocklist (2.NEWS)"
```

---

## Task 2: 2.KW — Keyword noise tightening

**Files:**
- Modify: `agents/sources/azure_maps.py:22-43`
- Modify: `agents/sources/yelp_fusion.py:44-69`
- Modify: `tests/test_source_azure_maps.py`
- Modify: `tests/test_source_yelp_fusion.py`

Problem: bare `"kitchen"` terms in both adapters pull restaurants from search results. The `None` term in Yelp does a category-only sweep that has the same effect. Keyword counts stay the same (Azure: 3, Yelp: 4) so no `side_effect` sizing changes are needed in existing tests.

### Capture before snapshot

- [ ] **Step 1: Print current keyword lists (save this output — it's the before)**

```bash
.venv/bin/python -c "
from agents.sources import azure_maps, yelp_fusion
print('=== BEFORE: Azure _KEYWORDS_BY_NICHE ===')
for niche, kws in azure_maps._KEYWORDS_BY_NICHE.items():
    print(f'  {niche}: {kws}')
print()
print('=== BEFORE: Yelp _TERMS_BY_NICHE ===')
for niche, terms in yelp_fusion._TERMS_BY_NICHE.items():
    print(f'  {niche}: {terms}')
"
```

Expected output (baseline — note the food-noise terms):
```
=== BEFORE: Azure _KEYWORDS_BY_NICHE ===
  kitchen remodelers: ['kitchen remodeling', 'kitchen renovation', 'kitchen contractor']
  kitchen remodeling: ['kitchen remodeling', 'kitchen renovation', 'kitchen contractor']
  bathroom remodelers: ['bathroom remodeling', 'bathroom renovation', 'bathroom contractor']
  bathroom remodeling: ['bathroom remodeling', 'bathroom renovation', 'bathroom contractor']

=== BEFORE: Yelp _TERMS_BY_NICHE ===
  kitchen remodelers: ['kitchen remodeling', 'kitchen renovation', 'kitchen contractor', None]
  kitchen remodeling: ['kitchen remodeling', 'kitchen renovation', 'kitchen contractor', None]
  bathroom remodelers: ['bathroom remodeling', 'bathroom renovation', 'bathroom contractor', None]
  bathroom remodeling: ['bathroom remodeling', 'bathroom renovation', 'bathroom contractor', None]
```

### Write regression tests first

- [ ] **Step 2: Write failing regression test in `tests/test_source_azure_maps.py`**

Add to the `SourceLeadsTest` class:

```python
def test_kitchen_remodelers_keywords_do_not_contain_bare_kitchen(self):
    """No bare 'kitchen' keyword — root cause of restaurant noise in Tampa smoke run."""
    from agents.sources.azure_maps import _KEYWORDS_BY_NICHE
    for niche in ("kitchen remodelers", "kitchen remodeling"):
        for kw in _KEYWORDS_BY_NICHE[niche]:
            self.assertNotEqual(
                kw, "kitchen",
                f"niche '{niche}' contains bare 'kitchen' keyword — causes food noise",
            )
```

- [ ] **Step 3: Write failing regression test in `tests/test_source_yelp_fusion.py`**

Add to the `SourceLeadsTest` class:

```python
def test_kitchen_remodelers_terms_do_not_contain_none_sweep(self):
    """None term (category-only sweep) pulls restaurants via homeservices category."""
    from agents.sources.yelp_fusion import _TERMS_BY_NICHE
    for niche in ("kitchen remodelers", "kitchen remodeling"):
        self.assertNotIn(
            None, _TERMS_BY_NICHE[niche],
            f"niche '{niche}' contains None term — causes restaurant noise via homeservices",
        )
```

- [ ] **Step 4: Run both regression tests to confirm they fail**

```bash
.venv/bin/python -m pytest \
  tests/test_source_azure_maps.py::SourceLeadsTest::test_kitchen_remodelers_keywords_do_not_contain_bare_kitchen \
  tests/test_source_yelp_fusion.py::SourceLeadsTest::test_kitchen_remodelers_terms_do_not_contain_none_sweep \
  -v
```

Expected: both FAIL.

### Apply keyword changes

- [ ] **Step 5: Replace `_KEYWORDS_BY_NICHE` in `agents/sources/azure_maps.py` (lines 22-43)**

```python
_KEYWORDS_BY_NICHE: dict[str, list[str]] = {
    "kitchen remodelers": [
        "kitchen and bath remodeling",
        "kitchen cabinet installation",
        "bathroom remodeling",
    ],
    "kitchen remodeling": [
        "kitchen and bath remodeling",
        "kitchen cabinet installation",
        "bathroom remodeling",
    ],
    "bathroom remodelers": [
        "bathroom remodeling",
        "bathroom renovation",
        "bathroom contractor",
    ],
    "bathroom remodeling": [
        "bathroom remodeling",
        "bathroom renovation",
        "bathroom contractor",
    ],
}
```

- [ ] **Step 6: Replace `_TERMS_BY_NICHE` in `agents/sources/yelp_fusion.py` (lines 44-69)**

Drop `None` from kitchen niches only. Bathroom niches keep their `None` sweep (no food noise problem there).

```python
_TERMS_BY_NICHE: dict[str, list[str | None]] = {
    "kitchen remodelers": [
        "kitchen and bath remodeling",
        "kitchen cabinet installation",
        "bathroom remodeling",
        "home remodeling contractor",
    ],
    "kitchen remodeling": [
        "kitchen and bath remodeling",
        "kitchen cabinet installation",
        "bathroom remodeling",
        "home remodeling contractor",
    ],
    "bathroom remodelers": [
        "bathroom remodeling",
        "bathroom renovation",
        "bathroom contractor",
        None,
    ],
    "bathroom remodeling": [
        "bathroom remodeling",
        "bathroom renovation",
        "bathroom contractor",
        None,
    ],
}
```

Also update the module docstring comment on line 14 that says "The rotation includes a `None` entry" — change it to:

```python
#   A rotation of `term` values broadens the surface within those
#   categories. For bathroom niches a `None` entry exercises a category-only
#   sweep; kitchen niches drop this to avoid food-business noise via the
#   homeservices category.
```

- [ ] **Step 7: Run all source adapter tests**

```bash
.venv/bin/python -m pytest tests/test_source_azure_maps.py tests/test_source_yelp_fusion.py -v
```

Expected: all tests PASS including both new regression tests.

### After snapshot + live validation

- [ ] **Step 8: Print the after keyword lists and compare to the before output from Step 1**

```bash
.venv/bin/python -c "
from agents.sources import azure_maps, yelp_fusion
print('=== AFTER: Azure _KEYWORDS_BY_NICHE ===')
for niche, kws in azure_maps._KEYWORDS_BY_NICHE.items():
    print(f'  {niche}: {kws}')
print()
print('=== AFTER: Yelp _TERMS_BY_NICHE ===')
for niche, terms in yelp_fusion._TERMS_BY_NICHE.items():
    print(f'  {niche}: {terms}')
"
```

Expected:
```
=== AFTER: Azure _KEYWORDS_BY_NICHE ===
  kitchen remodelers: ['kitchen and bath remodeling', 'kitchen cabinet installation', 'bathroom remodeling']
  kitchen remodeling: ['kitchen and bath remodeling', 'kitchen cabinet installation', 'bathroom remodeling']
  bathroom remodelers: ['bathroom remodeling', 'bathroom renovation', 'bathroom contractor']
  bathroom remodeling: ['bathroom remodeling', 'bathroom renovation', 'bathroom contractor']

=== AFTER: Yelp _TERMS_BY_NICHE ===
  kitchen remodelers: ['kitchen and bath remodeling', 'kitchen cabinet installation', 'bathroom remodeling', 'home remodeling contractor']
  kitchen remodeling: ['kitchen and bath remodeling', 'kitchen cabinet installation', 'bathroom remodeling', 'home remodeling contractor']
  bathroom remodelers: ['bathroom remodeling', 'bathroom renovation', 'bathroom contractor', None]
  bathroom remodeling: ['bathroom remodeling', 'bathroom renovation', 'bathroom contractor', None]
```

- [ ] **Step 9: Live count=5 validation (requires API keys in .env)**

```bash
python run.py --city "Tampa" --state FL --count 5 --niche "kitchen remodelers"
```

When complete, it prints the master CSV path (e.g., `output/Tampa_FL_kitchen_remodelers_YYYY-MM-DD__master.csv`). Open it and check:
- No rows where `reject_reason` contains `"restaurant"` or `"kitchen"` as a food reference
- All kept rows are remodeling contractors

Compare against the before baseline at `.playwright-mcp/master-20260504-024425-e36ea2.csv`, which had 7 food-business rejections (Zoe's Kitchen, The Exchange Kitchen and Bar, The Asian Kitchen, True Food Kitchen, Santos Kitchen + Lounge, Pizza Kitchen, California Pizza Kitchen). The after run should have zero food rejections.

- [ ] **Step 10: Commit**

```bash
git add agents/sources/azure_maps.py agents/sources/yelp_fusion.py \
        tests/test_source_azure_maps.py tests/test_source_yelp_fusion.py
git commit -m "fix(sourcer): tighten kitchen keywords to eliminate food business noise (2.KW)"
```

---

## Task 3: 2.CD — Cross-run dedup cache

**Files:**
- Create: `agents/leads_cache.py`
- Create: `tests/test_leads_cache.py`
- Modify: `agents/sourcer.py`
- Modify: `config.py`
- Modify: `tests/test_sourcer.py`
- Modify: `.gitignore`

### Config

- [ ] **Step 1: Add `leads_cache_ttl_days` to `config.py`**

After the `dedup_match_threshold` field (after line 72, before the personalizer block), add:

```python
    # ---- Cross-run dedup cache ----
    # Leads seen for this city+state within ttl_days are skipped on re-sourcing.
    leads_cache_ttl_days: int = 30
```

### Write all 11 tests before implementing

- [ ] **Step 2: Create `tests/test_leads_cache.py`**

```python
"""Tests for agents.leads_cache.

Test isolation: setUp patches leads_cache._DB_PATH to a temp path and calls
_init_db() to create a fresh schema. tearDown restores the original path and
removes the temp directory. Tests never touch the real state/leads_cache.db
and never bleed state between methods.
"""
from __future__ import annotations

import shutil
import sqlite3
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path

import agents.leads_cache as leads_cache


def _lead(source: str, source_id: str, business_name: str = "Foo Remodeling") -> dict:
    return {"source": source, "source_id": source_id, "business_name": business_name}


class LeadsCacheTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.mkdtemp()
        self._orig_path = leads_cache._DB_PATH
        leads_cache._DB_PATH = Path(self._tmp) / "test_cache.db"
        leads_cache._init_db()

    def tearDown(self):
        leads_cache._DB_PATH = self._orig_path
        shutil.rmtree(self._tmp, ignore_errors=True)

    # Test 1
    def test_filter_unseen_returns_all_when_cache_empty(self):
        leads = [_lead("azure_maps", "a1"), _lead("azure_maps", "a2")]
        result = leads_cache.filter_unseen(leads, "Tampa", "FL", ttl_days=30)
        self.assertEqual(len(result), 2)

    # Test 2
    def test_filter_unseen_drops_leads_seen_within_ttl(self):
        lead = _lead("azure_maps", "a1")
        leads_cache.mark_seen([lead], "Tampa", "FL", campaign_id="camp-1")
        result = leads_cache.filter_unseen([lead], "Tampa", "FL", ttl_days=30)
        self.assertEqual(result, [])

    # Test 3
    def test_filter_unseen_keeps_expired_leads(self):
        old_date = (date.today() - timedelta(days=31)).isoformat()
        conn = sqlite3.connect(str(leads_cache._DB_PATH))
        conn.execute(
            "INSERT OR REPLACE INTO seen_leads "
            "(source, source_id, business_name, city, state_abbr, first_seen, campaign_id) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            ("azure_maps", "a1", "Foo Remodeling", "tampa", "FL", old_date, "old-camp"),
        )
        conn.commit()
        conn.close()
        lead = _lead("azure_maps", "a1")
        result = leads_cache.filter_unseen([lead], "Tampa", "FL", ttl_days=30)
        self.assertEqual(len(result), 1)

    # Test 4
    def test_mark_seen_is_idempotent(self):
        lead = _lead("azure_maps", "a1")
        leads_cache.mark_seen([lead], "Tampa", "FL", campaign_id="camp-1")
        leads_cache.mark_seen([lead], "Tampa", "FL", campaign_id="camp-2")
        result = leads_cache.filter_unseen([lead], "Tampa", "FL", ttl_days=30)
        self.assertEqual(result, [])
        conn = sqlite3.connect(str(leads_cache._DB_PATH))
        count = conn.execute("SELECT COUNT(*) FROM seen_leads").fetchone()[0]
        conn.close()
        self.assertEqual(count, 1)

    # Test 5
    def test_empty_source_id_skipped_by_filter_and_mark(self):
        lead_no_id = _lead("azure_maps", "")
        leads_cache.mark_seen([lead_no_id], "Tampa", "FL", campaign_id="camp-1")
        conn = sqlite3.connect(str(leads_cache._DB_PATH))
        count = conn.execute("SELECT COUNT(*) FROM seen_leads").fetchone()[0]
        conn.close()
        self.assertEqual(count, 0)
        result = leads_cache.filter_unseen([lead_no_id], "Tampa", "FL", ttl_days=30)
        self.assertEqual(len(result), 1)

    # Test 6
    def test_city_scoping_dallas_does_not_block_orlando(self):
        lead = _lead("azure_maps", "a1")
        leads_cache.mark_seen([lead], "Dallas", "TX", campaign_id="camp-1")
        result = leads_cache.filter_unseen([lead], "Orlando", "FL", ttl_days=30)
        self.assertEqual(len(result), 1)

    # Test 7
    def test_merged_source_normalized_to_primary_before_write(self):
        merged_lead = _lead("azure_maps+yelp_fusion", "a1")
        leads_cache.mark_seen([merged_lead], "Tampa", "FL", campaign_id="camp-1")
        # A future filter_unseen with primary source string must match it.
        single_source_lead = _lead("azure_maps", "a1")
        result = leads_cache.filter_unseen([single_source_lead], "Tampa", "FL", ttl_days=30)
        self.assertEqual(result, [])

    # Test 8
    def test_filter_unseen_non_fatal_on_db_error(self):
        leads_cache._DB_PATH = Path(self._tmp) / "no_parent_dir" / "cache.db"
        lead = _lead("azure_maps", "a1")
        result = leads_cache.filter_unseen([lead], "Tampa", "FL", ttl_days=30)
        self.assertEqual(len(result), 1)  # returns full list on error

    # Test 9
    def test_mark_seen_non_fatal_on_db_error(self):
        leads_cache._DB_PATH = Path(self._tmp) / "no_parent_dir" / "cache.db"
        lead = _lead("azure_maps", "a1")
        leads_cache.mark_seen([lead], "Tampa", "FL", campaign_id="camp-1")  # must not raise

    # Test 10
    def test_city_normalization_case_insensitive(self):
        lead = _lead("azure_maps", "a1")
        leads_cache.mark_seen([lead], "Tampa", "FL", campaign_id="camp-1")
        result = leads_cache.filter_unseen([lead], "tampa", "FL", ttl_days=30)
        self.assertEqual(result, [])

    # Test 11
    def test_filter_unseen_logs_info_when_filtering(self):
        lead = _lead("azure_maps", "a1")
        leads_cache.mark_seen([lead], "Tampa", "FL", campaign_id="camp-1")
        with self.assertLogs("leads_cache", level="INFO") as log:
            leads_cache.filter_unseen([lead], "Tampa", "FL", ttl_days=30)
        self.assertTrue(any("filtered" in msg for msg in log.output))


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 3: Run tests to confirm they fail (module not yet created)**

```bash
.venv/bin/python -m pytest tests/test_leads_cache.py -v 2>&1 | head -10
```

Expected: `ModuleNotFoundError: No module named 'agents.leads_cache'`

### Implement the module

- [ ] **Step 4: Create `agents/leads_cache.py`**

```python
"""Cross-run dedup cache — SQLite-backed seen-leads store.

Public API:
    filter_unseen(leads, city, state_abbr, ttl_days) -> list[dict]
        Returns only leads not seen for this city+state within ttl_days.
    mark_seen(leads, city, state_abbr, campaign_id)
        Upserts leads into the cache.

Both functions are non-fatal: DB errors are logged as warnings and the
caller receives the full leads list so the sourcer continues uninterrupted.

Test isolation: tests patch `_DB_PATH` before calling `_init_db()`.
"""
from __future__ import annotations

import logging
import sqlite3
from pathlib import Path

logger = logging.getLogger("leads_cache")

# Exposed at module level so tests can patch it before calling _init_db().
_DB_PATH: Path = Path(__file__).parent.parent / "state" / "leads_cache.db"


def _init_db() -> None:
    """Create the DB file and table if they don't exist. Safe to call repeatedly."""
    Path(_DB_PATH).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(_DB_PATH))
    conn.execute("""
        CREATE TABLE IF NOT EXISTS seen_leads (
            source        TEXT NOT NULL,
            source_id     TEXT NOT NULL,
            business_name TEXT NOT NULL,
            city          TEXT NOT NULL,
            state_abbr    TEXT NOT NULL,
            first_seen    TEXT NOT NULL,
            campaign_id   TEXT NOT NULL,
            PRIMARY KEY (source, source_id)
        )
    """)
    conn.commit()
    conn.close()


_init_db()


def filter_unseen(
    leads: list[dict],
    city: str,
    state_abbr: str,
    ttl_days: int,
) -> list[dict]:
    """Return leads not already seen for this city+state within ttl_days.

    Leads with empty source_id pass through unconditionally — they can't be
    matched in the cache and skipping them would cause false negatives.
    On any DB error, returns the full leads list so the sourcer continues.
    """
    city = city.strip().lower()
    state_abbr = state_abbr.strip().upper()

    no_id = [l for l in leads if not l.get("source_id")]
    has_id = [l for l in leads if l.get("source_id")]

    if not has_id:
        return leads

    try:
        conn = sqlite3.connect(str(_DB_PATH))
        unseen: list[dict] = []
        for lead in has_id:
            row = conn.execute(
                """
                SELECT 1 FROM seen_leads
                WHERE source = ? AND source_id = ? AND city = ? AND state_abbr = ?
                  AND julianday('now') - julianday(first_seen) < ?
                """,
                (
                    lead["source"].split("+")[0],
                    lead["source_id"],
                    city,
                    state_abbr,
                    ttl_days,
                ),
            ).fetchone()
            if row is None:
                unseen.append(lead)
        conn.close()

        filtered_count = len(has_id) - len(unseen)
        if filtered_count > 0:
            logger.info(
                "leads_cache: filtered %d/%d already-seen leads",
                filtered_count,
                len(has_id),
            )
        return no_id + unseen

    except Exception as exc:
        logger.warning("leads_cache: filter_unseen failed, returning all leads: %s", exc)
        return leads


def mark_seen(
    leads: list[dict],
    city: str,
    state_abbr: str,
    campaign_id: str,
) -> None:
    """Upsert leads into the seen-leads cache.

    Normalizes merged source strings (e.g. 'azure_maps+yelp_fusion') to the
    primary source before writing so future filter_unseen calls match them.
    Leads with empty source_id are silently skipped.
    On any DB error, logs a warning and returns without crashing.
    """
    from datetime import date as _date

    city = city.strip().lower()
    state_abbr = state_abbr.strip().upper()
    today = _date.today().isoformat()

    rows = [
        (
            lead["source"].split("+")[0],
            lead["source_id"],
            lead.get("business_name", ""),
            city,
            state_abbr,
            today,
            campaign_id,
        )
        for lead in leads
        if lead.get("source_id")
    ]
    if not rows:
        return

    try:
        conn = sqlite3.connect(str(_DB_PATH))
        conn.executemany(
            "INSERT OR REPLACE INTO seen_leads "
            "(source, source_id, business_name, city, state_abbr, first_seen, campaign_id) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            rows,
        )
        conn.commit()
        conn.close()
    except Exception as exc:
        logger.warning("leads_cache: mark_seen failed, dedup not persisted: %s", exc)
```

- [ ] **Step 5: Run all 11 tests**

```bash
.venv/bin/python -m pytest tests/test_leads_cache.py -v
```

Expected: 11/11 PASS.

### Wire into sourcer.py

- [ ] **Step 6: Write 2 failing sourcer tests**

Add to `SourcerRunTest` in `tests/test_sourcer.py`:

```python
def test_run_logs_cache_filtered_short_when_all_filtered(self):
    """When leads_cache returns [], sourcer logs 'cache filtered short'."""
    import agents.leads_cache as lc
    from unittest.mock import patch as _patch
    with patch("agents.sourcer.azure_source.source_leads") as mock_az, \
         patch("agents.sourcer.yelp_source.source_leads") as mock_yp, \
         patch("agents.sourcer.find_website", return_value=None), \
         _patch.object(lc, "filter_unseen", return_value=[]), \
         _patch.object(lc, "mark_seen"):
        mock_az.return_value = [
            _normalized(source="azure_maps", source_id="a1",
                        business_name="Foo Inc", website="https://foo.com"),
        ]
        mock_yp.return_value = []
        sourcer.run(self.state)
        short_entries = [
            e for e in self.state.log if "cache filtered short" in e.get("msg", "")
        ]
        self.assertTrue(short_entries, "expected 'cache filtered short' in state.log")

def test_run_does_not_crash_when_leads_cache_raises(self):
    """An unexpected raise from filter_unseen does not crash the sourcer."""
    import agents.leads_cache as lc
    import sqlite3 as _sqlite3
    from unittest.mock import patch as _patch
    with patch("agents.sourcer.azure_source.source_leads") as mock_az, \
         patch("agents.sourcer.yelp_source.source_leads") as mock_yp, \
         patch("agents.sourcer.find_website", return_value=None), \
         _patch.object(lc, "filter_unseen",
                       side_effect=_sqlite3.OperationalError("disk full")):
        mock_az.return_value = [
            _normalized(source="azure_maps", source_id="a1",
                        business_name="Foo Inc", website="https://foo.com"),
        ]
        mock_yp.return_value = []
        sourcer.run(self.state)  # must not raise
        self.assertTrue(self.state.is_done("sourcer"))
```

- [ ] **Step 7: Run new sourcer tests to confirm they fail**

```bash
.venv/bin/python -m pytest \
  "tests/test_sourcer.py::SourcerRunTest::test_run_logs_cache_filtered_short_when_all_filtered" \
  "tests/test_sourcer.py::SourcerRunTest::test_run_does_not_crash_when_leads_cache_raises" \
  -v
```

Expected: both FAIL — `leads_cache` not yet imported in sourcer.

- [ ] **Step 8: Modify `agents/sourcer.py` — add import and wire cache calls**

Add to the imports block (after line 37, after the existing `from agents.website_finder import find_website` line):

```python
from agents import leads_cache
```

Replace the `# ---- 4. Website backfill` and `# ---- 5. Convert + persist` sections (lines 310-320 in the current file) with:

```python
    # ---- 4. Website backfill --------------------------------------------- #
    deduped = _enrich_websites(deduped, state)

    # ---- 4.5 Cross-run dedup cache --------------------------------------- #
    try:
        deduped = leads_cache.filter_unseen(
            deduped, state.city, state.state_abbr, CONFIG.leads_cache_ttl_days
        )
    except Exception as exc:
        state.info("sourcer", "leads_cache.filter_unseen error (non-fatal)", error=str(exc))

    # ---- 5. Convert + persist -------------------------------------------- #
    new_leads: list[dict] = []
    for normalized in deduped:
        if len(state.leads) >= state.target_count:
            break
        state.leads.append(_to_lead(normalized))
        new_leads.append(normalized)

    leads_cache.mark_seen(new_leads, state.city, state.state_abbr, state.campaign_id)

    if len(new_leads) < state.target_count:
        state.info(
            "sourcer", "cache filtered short",
            found=len(new_leads), target=state.target_count,
        )

    state.info("sourcer", "done", final_count=len(state.leads))
    state.mark_done("sourcer")
```

- [ ] **Step 9: Add `state/leads_cache.db` to `.gitignore`**

Open `.gitignore` and append:
```
state/leads_cache.db
```

- [ ] **Step 10: Run all sourcer tests**

```bash
.venv/bin/python -m pytest tests/test_sourcer.py -v
```

Expected: all tests PASS including the 2 new ones.

- [ ] **Step 11: Run full test suite**

```bash
.venv/bin/python -m pytest tests/ -v
```

Expected: all tests PASS.

- [ ] **Step 12: Import smoke test**

```bash
.venv/bin/python -c "from agents import sourcer, leads_cache; print('OK')"
```

Expected: `OK`

- [ ] **Step 13: Commit**

```bash
git add agents/leads_cache.py tests/test_leads_cache.py \
        agents/sourcer.py config.py tests/test_sourcer.py .gitignore
git commit -m "feat(sourcer): add SQLite cross-run dedup cache (2.CD)"
```

---

## Task 4: 2.OR — Per-lead owner researcher checkpointing

**Files:**
- Modify: `agents/owner_researcher.py:233-282`

Problem: the current `run()` collects all futures into a `results` dict before applying any of them (lines 242-254). If the process crashes mid-batch, all completed owner lookups are lost and the entire batch re-runs on `--resume`. At 50 leads this wastes up to 40 Claude Sonnet calls.

Fix: apply each result immediately as its future completes, then call `state.save_leads()` so the lead data is persisted to Supabase. On resume, `targets = [l for l in state.leads if l.kept and not l.owner_full_name]` naturally skips leads already researched.

`state.save_leads()` does a DELETE + bulk INSERT of all leads. At 50 leads called up to 50 times this is 2,550 Supabase row writes — well within the free tier and acceptable for the crash-safety gain.

- [ ] **Step 1: Confirm current line numbers before editing**

```bash
grep -n "def run\|results = {}\|as_completed\|results\[id\|for lead in targets\|mark_done" \
  agents/owner_researcher.py
```

Expected (current):
```
233: def run(state: CampaignState, anthropic_key: str) -> None:
239: targets = [l for l in state.leads if l.kept and not l.owner_full_name]
242:     results = {}
243:     with futures.ThreadPoolExecutor(max_workers=MAX_PARALLEL) as pool:
248:         for fut in futures.as_completed(future_map):
258:     for lead in targets:
282:     state.mark_done("owner_researcher")
```

- [ ] **Step 2: Replace `run()` in `agents/owner_researcher.py` (lines 233-282)**

```python
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
```

- [ ] **Step 3: Import smoke test**

```bash
.venv/bin/python -c "from agents import owner_researcher; print('OK')"
```

Expected: `OK`

- [ ] **Step 4: Run full test suite**

```bash
.venv/bin/python -m pytest tests/ -v --tb=short
```

Expected: all tests PASS.

- [ ] **Step 5: Commit**

```bash
git add agents/owner_researcher.py
git commit -m "feat(owner_researcher): checkpoint per-lead so --resume skips completed work (2.OR)"
```

---

## Final verification

- [ ] **Step 1: Full test suite green**

```bash
.venv/bin/python -m pytest tests/ -v --tb=short
```

Expected: all tests PASS, no import errors, no warnings.

- [ ] **Step 2: All agent imports clean**

```bash
.venv/bin/python -c "
from agents import sourcer, leads_cache, website_finder, owner_researcher
from agents.sources import azure_maps, yelp_fusion
print('All imports OK')
"
```

Expected: `All imports OK`

- [ ] **Step 3: Confirm 4 commits on tightening branch**

```bash
git log --oneline -5
```

Expected (newest first):
```
<sha>  feat(owner_researcher): checkpoint per-lead so --resume skips completed work (2.OR)
<sha>  feat(sourcer): add SQLite cross-run dedup cache (2.CD)
<sha>  fix(sourcer): tighten kitchen keywords to eliminate food business noise (2.KW)
<sha>  fix(website_finder): add news/PR domains to directory blocklist (2.NEWS)
```
