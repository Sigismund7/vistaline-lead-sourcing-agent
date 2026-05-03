# Plan: Sourcing Tool — Two-Layer Universal Architecture v1

**Source-of-truth design doc:** `docs/office-hours-renovation.md`
**Status:** APPROVED for execution (2026-05-02)
**Architecture:** Azure Maps POI Search + Yelp Fusion API (parallel sourcing layers, deduplicated) → Bing Web Search API (website finder) → existing free HTTP+BS4 crawler + two-phase researcher
**Scope:** Sourcing pipeline only. Tool produces FindyMail-ready CSV at production size. Operator workflow downstream (Instantly variants, PRR tracking, decision gate) is out of scope.

## Architecture

```
agents/sourcer.py (router) → merges + dedupes results from two layers:
  ├── agents/sources/azure_maps.py    (NEW: universal POI Search across 50 states)
  └── agents/sources/yelp_fusion.py   (NEW: universal business search via Yelp categories)

agents/website_finder.py    → Pattern-guess + Bing Web Search API fallback (NEW)
agents/website_crawler.py   → existing free HTTP+BS4 (unchanged)
agents/owner_researcher.py  → existing two-phase researcher (unchanged unless smoke surfaces issues)
agents/lead_filter.py       → existing Claude SOP filter (unchanged unless smoke shows category drift)
agents/csv_assembler.py     → existing FindyMail CSV writer (unchanged unless smoke shows column issues)
run.py                      → existing deterministic orchestrator (Premise 5 lock — no LLM-decision logic)
```

## Decision log (architecture journey, preserved)

1. Started: tighten existing Google Places + BBB pipeline.
2. Compliance review: Google Maps Platform ToS prohibits "creating mailing lists / telemarketing lists." Rejected.
3. Burner Google account: rejected (active evasion + fingerprint linkage risk to Vistaline's main Google account).
4. State contractor licensing registries: evaluated for universal sourcing; only ~35–40 states have programmatically-accessible registries; per-state engineering cost (1–2 days × 50 states) too high.
5. Azure Maps POI Search: selected as Layer 1 universal sourcer. Microsoft's Service Specific Terms do NOT contain Google's "no mailing lists" clause. B2B sales prospecting is contemplated as permitted commercial use. Less aggressive detection. Universal across 50 states.
6. Yelp Fusion API: added as Layer 2 universal supplement. Coverage of renovation contractors via Yelp Home Services category is meaningfully better than Azure Maps alone in metro areas. ToS permits business lookups for commercial use.
7. PhantomBuster + LLM-based scrapers: deferred. State databases are 1990s-era ASP forms — plain BS4 wins; LLM scrapers don't add value for tabular data; PhantomBuster doesn't add value over in-house code.

## Locked Constraints

1. Premises 1–5 from design doc.
2. `run.py` stays deterministic Python — no LLM-decision logic.
3. Cost discipline: paid surfaces are **Anthropic API + Azure Maps POI Search + Bing Web Search API + Yelp Fusion API**. Any additional paid surface requires new approval.
4. Both Azure and Yelp accounts are SEPARATE from Vistaline Digital's main Microsoft / Yelp / Google accounts. Confirmed by operator.
5. Companion PRR-outreach is human-only.

## Mitigation Stack — Operator-Side

These must be true before any production-volume run:

1. **Separate Azure subscription** (not main Vistaline). ✅ confirmed.
2. **Tier S1 (production) for Azure Maps**, NOT free S0. ~/mo entry.
3. **Real attached payment method** on the Azure account.
4. **Bing Search v7 key** provisioned on same Azure account.
5. **Separate Yelp Fusion API account** (developer.yelp.com), not tied to Vistaline's primary Yelp business listing if any.
6. **Real attached payment method** on Yelp Fusion if upgrading past free tier (free tier covers 5000 calls/day — likely sufficient for smoke and early production).
7. **Don't combine Azure Maps / Yelp / Bing data with Google Places or other competitor mapping data** in same operation or downstream output.
8. **Don't redistribute raw POI / business listing responses** anywhere downstream. Process inside pipeline; output is FindyMail-ready CSV only.
9. **Refresh cycle for cached lead data:** any lead older than 30 days re-sourced or expired. Operator decides cadence; recommend weekly full refresh.

## Mitigation Stack — Code-Side

Built into the pipeline; enforced by code:

10. **Rate limiting on both sourcer layers:**
    - Azure Maps: 1.5 calls/sec with random jitter `0..200ms`. Configured `AZURE_MAPS_RATE_LIMIT_QPS` and `AZURE_MAPS_JITTER_MS`.
    - Yelp Fusion: 1.0 call/sec with random jitter `0..300ms`. Configured `YELP_RATE_LIMIT_QPS` and `YELP_JITTER_MS`. Yelp's documented limits are 5000 calls/day, 5 calls/sec; we run well under.
11. **Diverse query patterns on both layers:** rotate categories and geographies rather than running 1000 identical-shape queries.
12. **Use category filters correctly:**
    - Azure Maps: call POI Search with `categorySet=<construction/renovation/kitchen-remodeling>`, not raw text-only queries.
    - Yelp: call `/businesses/search` with `categories=contractors,kitchen_and_bath,homeservices`, not raw text searches.
13. **Throttle response handler on both:** monitor 429/5xx → exponential back-off (base 1s, max 60s) → alert if sustained throttling for >5 minutes.

## Files in Scope

### IN SCOPE — modifiable
- `agents/sourcer.py` — refactored to router pattern. Calls each source layer, merges results, dedupes by business name + address fuzzy match (using `rapidfuzz`).
- `agents/sources/` — NEW directory.
  - `agents/sources/__init__.py`
  - `agents/sources/azure_maps.py` — Azure Maps POI Search adapter.
  - `agents/sources/yelp_fusion.py` — Yelp Fusion API adapter.
- `agents/website_finder.py` — NEW. Pattern-guess + Bing Web Search fallback + directory blocklist.
- `agents/lead_filter.py` — minor adjustments if smoke shows category drift.
- `agents/owner_researcher.py` — minor adjustments if smoke shows different failure modes.
- `agents/csv_assembler.py` — modifiable for FindyMail validation.
- `agents/website_crawler.py` — unchanged unless Phase 2 Playwright gate triggers.
- `tools.py` — adds Azure Maps client, Yelp Fusion client, Bing Web Search client. External API clients only (no business logic, no LLM calls).
- `config.py` — new threshold constants for both rate limits, refresh cadence, dedup match thresholds.
- `tests/` — TDD tests for new code paths.
- `.env` — adds `AZURE_MAPS_KEY`, `BING_SEARCH_KEY`, `YELP_FUSION_KEY`. Already gitignored.
- `requirements.txt` — adds `rapidfuzz` for dedup matching.

### IN SCOPE — modifiable only if smoke surfaces specific bug
- `agents/website_crawler.py` — Phase 2 conditional Playwright fallback only.
- `state.py` — only if `--resume` contract is broken.

### IN SCOPE — executed, NOT modified
- `run.py` — Premise 5 lock. CLI bug fixes only.
- `agents/__init__.py` — register new modules.

### IN SCOPE — created during work
- `docs/smoke-orlando-20.md` — Phase 1 deliverable.
- Worktree branches per task — `phase0/<slug>`, `tightening/<slug>`.

### OUT OF SCOPE — DO NOT TOUCH
- New agent files beyond `website_finder.py` and the per-source adapters listed above.
- LLM-decision-making in `run.py`.
- Personalization, Loom thumbnails, Instantly campaign creation/launch, Notion logging.
- Snov.io / Apollo / Hunter integrations.
- State contractor licensing registries (deferred — see below).
- PhantomBuster / LLM-driven scrapers (deferred).
- Approach B work (variants.yaml, pull_results, analyze.py).
- Adding paid surfaces beyond Anthropic + Azure Maps + Bing + Yelp Fusion.
- Google Places API in any form. Vistaline's Google footprint stays untouched.

### Deferred for later evaluation
- **PhantomBuster** — could be useful later for JS-rendered websites or multi-page traversal of contractor sites if Phase 2 Playwright fallback or hand-coded multi-page crawler proves uneconomic. Revisit only if smoke shows those specific failure modes.
- **LLM email extractor (Haiku Phase 1.5)** — revisit only if smoke shows obfuscated-email failure rate >20% on leads with discovered websites.
- **State contractor licensing registries** — revisit only if Azure + Yelp combined coverage in specific states proves <70% in smoke testing. Per-state engineering cost (1–2 days/state) is the gating factor.

## Cross-Cutting Rules

- Files touched must subset Files-in-Scope.
- TDD on every Phase 0 / Phase 2 source change.
- Code review subagent passes before merge.
- Worktree branch per implementation task.
- Smoke findings → Phase 2 tasks 1:1.
- Cost-discipline gate before generating any new task.

## Division of Labor

- **Claude executes:** all code, tests, git, Azure Maps + Yelp Fusion + Bing Web Search integration, rate limiting / jitter / category logic, dedup logic, throttle handlers.
- **Operator executes:** Azure subscription provisioning, Yelp Fusion API account, all API keys into `.env`, browser-based spot-checks, PRR outreach, decisions about refresh cadence.

---

## PHASE 0 — Architecture Build

### Task 0.1 — Verify environment runnable
Already done this session.

### Task 0.2 — Scaffold `tests/`
Create `tests/__init__.py` + placeholder. Verify pytest discovery.

### Task 0.3 — Operator provisions API keys (HUMAN)

Operator does:
1. Create separate Azure subscription (NOT Vistaline main).
2. Provision Azure Maps S1 + Bing Search v7 resources. Capture keys.
3. Create Yelp Fusion API account at developer.yelp.com. Capture key.
4. Attach payment method to both accounts.
5. Drop all three keys into `.env` as `AZURE_MAPS_KEY`, `BING_SEARCH_KEY`, `YELP_FUSION_KEY`.

Claude verifies all three load cleanly via `python-dotenv` (length check only, no value display).

### Task 0.4 — Add `rapidfuzz` to requirements + venv (TDD)

- `pip install rapidfuzz`
- Add to `requirements.txt`
- Smoke test: `python -c "from rapidfuzz import fuzz; print(fuzz.ratio('ABC Renovations', 'ABC Renovation'))"`

### Task 0.5 — Implement Azure Maps client in `tools.py` (TDD)

Test: mock HTTP responses, verify rate-limited POI Search call returns expected structure. Tests rate-limit jitter timing. Tests 429 back-off.

Implementation: `class AzureMapsClient` with `geocode(city, state)` and `search_poi(category, lat, lon, radius_m, limit)`. Rate-limited at `AZURE_MAPS_RATE_LIMIT_QPS`. Random jitter. Exponential back-off on 429/5xx.

Worktree: `phase0/azure-maps-client`.

### Task 0.6 — Implement Yelp Fusion client in `tools.py` (TDD)

Test: mock HTTP responses, verify rate-limited Yelp Fusion `/businesses/search` call returns expected structure. Tests Yelp-specific rate limits + 429 back-off.

Implementation: `class YelpFusionClient` with `search_businesses(category, location, radius_m, limit)`. Rate-limited at `YELP_RATE_LIMIT_QPS`. Random jitter. Exponential back-off.

Worktree: `phase0/yelp-fusion-client`.

### Task 0.7 — Implement Bing Web Search client in `tools.py` (TDD)

Test: mock response, verify search returns top non-directory URL.

Implementation: `class BingSearchClient` with `search(query, count=5)`.

Worktree: `phase0/bing-search-client`.

### Task 0.8 — Implement `agents/sources/azure_maps.py` (TDD)

Test: given `state="FL"`, `city="Orlando"`, `niche="kitchen remodelers"`, `count=10`, returns 10 normalized leads with `business_name`, `address`, `phone?`, `website?`.

Implementation: city → lat/lon via Azure Maps geocoding. POI Search with category filter. Query-pattern diversity across batches.

Worktree: `phase0/source-azure-maps`.

### Task 0.9 — Implement `agents/sources/yelp_fusion.py` (TDD)

Test: given same inputs, returns normalized leads from Yelp.

Implementation: Yelp `/businesses/search` with category filter `contractors,kitchen_and_bath,homeservices`, location string. Query-pattern diversity.

Worktree: `phase0/source-yelp-fusion`.

### Task 0.10 — Refactor `agents/sourcer.py` to router with dedup (TDD)

Test: mock both source adapters returning overlapping + distinct leads. Verify router merges results, dedupes by business-name + address fuzzy match (`rapidfuzz.fuzz.token_sort_ratio` > 85), returns count requested.

Implementation: calls each source layer in parallel (within respective rate limits), merges results, dedupes, returns top-N normalized leads.

Worktree: `phase0/sourcer-router-dedup`.

### Task 0.11 — Implement `agents/website_finder.py` (TDD)

Test: given business name + city + state, returns URL or None.

Implementation:
1. Pattern-guess (`<slug>.com`, `.net`, `.co`, `kitchensby<slug>.com`) with HEAD validation. Reject parked domains.
2. Fall back to Bing Web Search with directory blocklist (`yelp.com, bbb.org, angi.com, homeadvisor.com, houzz.com, facebook.com, instagram.com, linkedin.com, mapquest.com, yellowpages.com`).
3. HEAD-validate result.
4. Return None if both paths fail.

Worktree: `phase0/website-finder`.

### Task 0.12 — Wire it up in `run.py` (verify only, no logic change)

Confirm `python run.py --city "Orlando" --state FL --count 3 --niche "kitchen remodelers"` runs end-to-end. Wiring verification, not smoke test.

**Phase 0 deliverables:** new sourcer router + two source adapters + website_finder + clients merged. Tests green. Pipeline runs end-to-end on count=3.

**Gate to Phase 1:** Task 0.12 produces non-empty CSV with lead count matching `--count`.

---

## PHASE 1 — Smoke Test (Day 1–2 after Phase 0)

### Task 1.1 — count=5 smoke run
`python run.py --city "Orlando" --state FL --count 5 --niche "kitchen remodelers"`. Capture artifacts.

### Task 1.2 — Operator spot-check on count=5 (HUMAN)
Per-row: business-fit (Y/N), owner-name (Y/N/partial), email (Y/N/partial). Note source attribution per row (Azure / Yelp / merged-from-both).

### Task 1.3 — Resume contract verification on count=20
Start, SIGINT mid-batch, resume. Verify continuation, no duplicates, completes.

### Task 1.4 — Spot-check count=20 + write findings
Operator + Claude write `docs/smoke-orlando-20.md`:
- Header: total rows; business-fit accuracy; owner-name accuracy (target ≥80%); email-find rate; per-source contribution counts; dedup rate; website-finder hit rate; Azure rate-limit incidents; Yelp rate-limit incidents; resume contract verdict.
- Body: one line per failure: `<symptom> | <suspected file> | <fix sketch> | <count>`, frequency-sorted.

Failure categories: `wrong-business-fit`, `name-missing`, `name-wrong`, `email-missing`, `email-wrong`, `website-finder-miss`, `azure-throttled`, `yelp-throttled`, `dedup-missed-duplicate`, `dedup-false-merge`, `bing-search-error`, `js-rendered-page`, `crash-or-exception`, `other`.

**Gate to Phase 2:** findings populated. Zero failures + resume holds → jump to Phase 3.

---

## PHASE 2 — Tightening (conditional)

One task per finding, frequency-ordered, TDD-enforced, code-reviewed.

### Conditional sub-blocks
- **2.PW Playwright fallback:** trigger `js-rendered-page` ≥30% of findings.
- **2.AD-1 Sourcer overflow** in any `agents/sources/*` adapter.
- **2.AD-2 Owner-researcher Phase 2 cap** in `agents/owner_researcher.py`.
- **2.AD-3 Lead-filter junk warning** in `agents/lead_filter.py`.
- **2.AD-4 Website-finder hit-rate alert** in `agents/website_finder.py`.
- **2.AD-5 Azure throttle handler** in `tools.py` Azure client.
- **2.AD-6 Yelp throttle handler** in `tools.py` Yelp client.
- **2.AD-7 Dedup threshold tuning** in `agents/sourcer.py` if `dedup-missed-duplicate` or `dedup-false-merge` findings appear.
- **2.LE LLM email extractor (Haiku):** trigger `email-missing` >20% of leads_with_known_website.

### Task 2.KW — Keyword noise tightening (smoke finding: 7 occurrences)

Replace bare "kitchen" keyword rotation in both source adapters with terms that don't match food businesses.

**Files:** `agents/sources/azure_maps.py`, `agents/sources/yelp_fusion.py`

**Azure keywords** (replace `_KEYWORDS_BY_NICHE["kitchen remodelers"]`):
- `"kitchen and bath remodeling"`, `"kitchen cabinet installation"`, `"bathroom remodeling"`

**Yelp terms** (replace `_TERMS_BY_NICHE["kitchen remodelers"]`, drop `None`):
- `"kitchen and bath remodeling"`, `"kitchen cabinet installation"`, `"bathroom remodeling"`, `"home remodeling contractor"`

No logic changes — dict values only. No new tests needed (existing tests mock HTTP layer).
Verify with a count=5 run: food businesses should no longer appear in sourced results.

### Task 2.CD — Cross-run dedup cache (prevents re-sourcing same businesses across campaigns)

**New file: `agents/leads_cache.py`** — SQLite-backed seen-leads store.

Two public functions:
- `filter_unseen(leads, city, state_abbr, ttl_days) -> list[dict]` — returns only leads not in cache within TTL
- `mark_seen(leads, city, state_abbr, campaign_id)` — upserts new leads into cache

**DB:** `state/leads_cache.db` (auto-created, add to `.gitignore`)

Schema:
```sql
CREATE TABLE seen_leads (
    source        TEXT NOT NULL,
    source_id     TEXT NOT NULL,
    business_name TEXT NOT NULL,
    city          TEXT NOT NULL,
    state_abbr    TEXT NOT NULL,
    first_seen    TEXT NOT NULL,   -- ISO date YYYY-MM-DD
    campaign_id   TEXT NOT NULL,
    PRIMARY KEY (source, source_id)
)
```

**Modified: `agents/sourcer.py`** — after `_dedupe_cross_source`, before `_enrich_websites`:
```python
deduped = leads_cache.filter_unseen(deduped, state.city, state.state_abbr, CONFIG.leads_cache_ttl_days)
```
After `state.leads.append(...)` loop:
```python
leads_cache.mark_seen(deduped[:state.target_count], state.city, state.state_abbr, state.campaign_id)
```

**Modified: `config.py`** — add two fields:
```python
leads_cache_ttl_days: int = 30
leads_cache_path: str = "state/leads_cache.db"
```

If cache filtering causes sourcer to fall short of `target_count`, log a warning with how many uncached leads were found.

**Tests (TDD — all in `tests/test_leads_cache.py`):**
1. `filter_unseen` returns all leads when cache is empty
2. `filter_unseen` drops leads seen within TTL
3. `filter_unseen` keeps leads seen outside TTL (expired)
4. `mark_seen` writes correctly; second call on same lead is a no-op (upsert)
5. Sourcer integration: second run on same city returns 0 leads (all cached)

Cost-discipline gate on every task.

---

## PHASE 3 — Validation

### 3.1 — count=50 validation
Spot-check 20 random (`random.seed(42); random.sample(range(50), 20)`). Pass: ≥16/20 accurate + ≥40% email-find-rate.

### 3.2 — count=500 production
<2 hrs compute + <1 hr review. Output FindyMail CSV in `output/`.

### 3.3 — Hand-off
Print CSV path + summary: total leads, source breakdown, dedup rate, accuracy metrics, sourcing time, files modified, mitigation-compliance audit (rate limits honored, no sustained throttling, no out-of-scope file modified, no new paid surface introduced).

---

## Plan-level success criteria

- All Phase 0 components merged with green tests
- `.env` populated with all four required keys (Azure Maps, Bing Search, Yelp Fusion, Anthropic) — operator-side
- Phase 1 deliverables exist; `docs/smoke-orlando-20.md` populated
- Phase 2 finding-derived tasks (frequency ≥2) merged
- Phase 3 validation passes ≥16/20 spot-check + ≥40% email-find-rate
- Phase 3 production CSV produced within timing budget
- No file outside Files-in-Scope modified
- No paid surface beyond Anthropic + Azure Maps + Bing + Yelp Fusion introduced
- `run.py` did not gain LLM-decision logic
- All 13 mitigations (9 operator-side, 4 code-side) verified before production-volume run

## Open questions for go-time

1. Operator confirms Azure subscription + Yelp Fusion account provisioned, all keys in `.env`.
2. Subagent-driven-development skill upgrade vs. linear executing-plans (skill recommended subagent-driven).
