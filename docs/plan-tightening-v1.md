# Plan: Sourcing Tool — Universal Architecture v1

**Source-of-truth design doc:** `docs/office-hours-renovation.md`
**Status:** APPROVED for execution (2026-05-02)
**Architecture:** Azure Maps POI Search (universal sourcer, all 50 states) → Bing Web Search API (website finder) → existing free HTTP+BS4 crawler + two-phase researcher
**Scope:** Sourcing pipeline only. Tool produces FindyMail-ready CSV at production size. Operator workflow downstream (Instantly variants, PRR tracking, decision gate) is out of scope.

## Architecture

```
agents/sourcer.py          → Azure Maps POI Search (universal sourcing across all US states)
agents/website_finder.py   → Pattern-guess + Bing Web Search API fallback (NEW)
agents/website_crawler.py  → existing free HTTP+BS4 (unchanged)
agents/owner_researcher.py → existing two-phase (Phase 1 regex on crawled text, Phase 2 web_search fallback)
agents/lead_filter.py      → existing Claude SOP filter (unchanged unless smoke shows category drift)
agents/csv_assembler.py    → existing FindyMail CSV writer (unchanged unless smoke shows column issues)
run.py                     → existing deterministic orchestrator (Premise 5 lock — no modifications beyond bug fixes)
```

## Decision log (architecture journey, preserved for future readers)

1. **Started:** tighten existing Google Places + BBB pipeline.
2. **Compliance review** surfaced Google Maps Platform ToS issue (explicit "no mailing lists / telemarketing lists" clause in Acceptable Use Policy).
3. **Burner Google account** evaluated → rejected (active evasion posture, fingerprinting linkage risk, more ops overhead).
4. **State contractor licensing registries** evaluated → rejected after coverage analysis (only ~35–40 states have programmatically-accessible registries; remaining 10–15 are gap states; per-state engineering scales linearly; too narrow for universal sourcing requirement).
5. **Azure Maps POI Search** selected as universal sourcer. Microsoft's Azure Maps Service Specific Terms do NOT contain the "no mailing lists" clause that Google Maps does. B2B sales prospecting is contemplated as a permitted commercial use. Detection systems are less aggressive than Google's. Universal coverage across all 50 US states.
6. **PhantomBuster + LLM-based scrapers** evaluated → deferred. Could be useful later for specific failure modes (JS-rendered sites, obfuscated emails) but not as primary architecture.

## Locked Constraints

1. Premises 1–5 from design doc.
2. `run.py` stays deterministic Python — no LLM-decision logic, no agentic branching at orchestrator level.
3. Cost discipline: paid surfaces are **Anthropic API + Azure Maps POI Search + Bing Web Search API**. Any additional paid surface requires new approval.
4. Azure subscription is **operator-side concern**: must be SEPARATE from Vistaline Digital's main Azure/Microsoft account. Confirmed by operator.
5. Companion PRR-outreach is human-only.

## Mitigation Stack — Operator-Side (must be true before / during operation)

1. **Separate Azure subscription** — not Vistaline's main Azure/Microsoft account. Blast-radius containment if anything ever goes sideways. ✅ confirmed by operator.
2. **Tier S1 (production tier with SLA)** for Azure Maps, NOT free S0. Free tier has aggressive throttling that triggers abuse signals when hit; S1 is the paid commercial tier Microsoft expects production users to be on. Cost: ~/mo entry, scales with volume.
3. **Real payment method attached to the Azure account.** Microsoft is meaningfully less likely to suspend a paying customer than a free-tier abuser.
4. **`BING_SEARCH_KEY` provisioned on same Azure account.** Single-vendor stack, single billing relationship.
5. **Don't combine Azure Maps data with Google Places (or other competitor mapping) data in the same operation or output.** Microsoft's terms forbid mixed-source mapping displays; we stay clean by sourcing exclusively from Azure inside the pipeline.
6. **Don't redistribute raw POI Search responses anywhere downstream.** Process responses inside the pipeline; output is enriched FindyMail-ready CSV only. Raw API responses do not leave `output/` directory of this pipeline.
7. **Refresh cycle for cached lead data:** any lead older than 30 days gets re-sourced or expires from working set. Honors Azure Maps caching ToS. Operator decides exact cadence; recommend weekly full refresh.

## Mitigation Stack — Code-Side (built into the pipeline, enforced by code)

8. **Rate limit:** 1–2 calls/sec to Azure Maps POI Search with random jitter. Configured in `config.py` as `AZURE_MAPS_RATE_LIMIT_QPS = 1.5` and `AZURE_MAPS_JITTER_MS = 200`. Looks like a normal application, not bulk extraction.
9. **Diverse query patterns:** sourcer rotates category/geography combinations rather than issuing 1000 identical-shape queries with only lat/lon varying. Pattern looks like genuine app traffic.
10. **Category filters in POI Search calls:** call POI Search with `categorySet=<construction/renovation>` plus geographic point, NOT raw text-only queries. Categorical API surface is what Microsoft built for this; using it correctly looks like correct use.
11. **Throttle response handler:** monitor for HTTP 429 (rate limited) and 5xx responses; exponential back-off; alert if sustained throttling indicates Microsoft is unhappy with our usage shape.

## Files in Scope

### IN SCOPE — modifiable
- `agents/sourcer.py` — replace existing Google-Places implementation with Azure Maps POI Search. Includes city → lat/lon geocoding, category filtering, rate limiting, jitter, query-pattern diversity.
- `agents/website_finder.py` — NEW. Pattern-guess (`.com/.net/.co` HEAD validation) + Bing Web Search fallback + directory blocklist + HEAD-validation of returned URL.
- `agents/lead_filter.py` — minor adjustments if smoke shows registry-vs-Places data shape differences.
- `agents/owner_researcher.py` — minor adjustments if smoke shows different failure modes vs prior (Google Places + BBB) pipeline.
- `agents/csv_assembler.py` — modifiable for FindyMail validation if smoke surfaces column issues.
- `tools.py` — adds Azure Maps client + Bing Web Search client. External API clients only (no business logic, no LLM calls — per CLAUDE.md).
- `config.py` — new threshold constants (rate limits, jitter, query-pattern parameters, refresh cadence).
- `tests/` — new TDD tests for new code paths.
- `.env` — adds `AZURE_MAPS_KEY` and `BING_SEARCH_KEY`. Already gitignored.
- `requirements.txt` — adds Azure SDK dependency if needed for the SDK path; otherwise plain `requests` suffices.

### IN SCOPE — modifiable only if smoke surfaces a specific bug
- `agents/website_crawler.py` — only modify for Playwright fallback (Phase 2 conditional sub-block 2.PW). Otherwise unchanged.
- `state.py` — only modify if `--resume` contract is broken (Phase 1 task 1.3).

### IN SCOPE — executed, NOT modified
- `run.py` — Premise 5 lock. No LLM-decision logic. No new branching. Modifiable only for CLI bug fixes on existing surface.
- `agents/__init__.py` — register new `website_finder` module.

### IN SCOPE — created during work
- `docs/smoke-orlando-20.md` — Phase 1 deliverable.
- Worktree branches per Phase 0 / Phase 2 task — `phase0/<slug>`, `tightening/<slug>`.

### OUT OF SCOPE — DO NOT TOUCH
- New agent files beyond `website_finder.py`.
- LLM-decision-making in `run.py` (Premise 5 hard lock).
- Personalization, Loom thumbnails, Instantly campaign creation/launch, Notion logging.
- Snov.io / Apollo / Hunter API integrations (declined upstream).
- State contractor licensing registries (decision-logged out).
- PhantomBuster / LLM-driven scrapers (deferred — see below).
- Approach B work (variants.yaml, pull_results.py, analyze.py, dashboard).
- Adding paid surfaces beyond Anthropic + Azure Maps + Bing Web Search.

### Deferred for later evaluation
- **PhantomBuster** — set aside. Could be useful later for: (a) JS-rendered website handling if Playwright isn't built, (b) multi-page traversal of contractor sites if email-find rate is low. Revisit only if smoke surfaces those specific failure modes AND building the in-house equivalent (Playwright fallback / multi-page crawler) is judged uneconomic.
- **LLM-based email extractor (Haiku) in `owner_researcher.py` Phase 1.5** — set aside. Cheap (~.001/lead). Revisit only if smoke shows obfuscated-email failure rate >20% on leads with discovered websites.
- **State contractor licensing registries (per-state adapters)** — set aside. Per-state engineering cost too high vs. universal Azure Maps. Revisit if Azure Maps coverage in specific high-value states proves insufficient.

## Cross-Cutting Rules (every task, every phase)

- Files touched must subset Files-in-Scope.
- TDD on every Phase 0 / Phase 2 source change: failing test → implement → green test.
- Code review subagent passes before merge.
- Worktree branch per implementation task.
- Smoke findings → Phase 2 tasks 1:1.
- Cost-discipline gate before generating any new task.

## Division of Labor

- **Claude executes:** all code, tests, git, Azure Maps + Bing Web Search integration, rate limiter / jitter / category logic, throttle handling.
- **Operator executes:** separate Azure subscription provisioning, Azure Maps S1 + Bing Search v7 keys, browser-based spot-checks of website + owner-name + email accuracy per row, PRR outreach, decisions about refresh cadence.

---

## PHASE 0 — Architecture Build

**Goal:** universal Azure Maps + Bing pipeline runs end-to-end before any smoke test.

### Task 0.1 — Verify environment runnable

Already done this session. `.env` exists with placeholders for Azure Maps + Bing keys; `.venv` is active; imports pass.

### Task 0.2 — Scaffold `tests/`

Create `tests/__init__.py` (empty). Add placeholder `tests/test_smoke.py` with one test asserting all `agents/*` modules import. Verify `python -m pytest tests/ -q` passes.

### Task 0.3 — Operator provisions Azure + Bing keys (HUMAN)

Operator does:
1. Create separate Azure subscription (NOT Vistaline main).
2. Provision Azure Maps S1 resource. Capture `AZURE_MAPS_KEY`.
3. Provision Bing Search v7 resource. Capture `BING_SEARCH_KEY`.
4. Attach payment method to subscription.
5. Drop both keys into `.env`.

Claude verifies `.env` loads both cleanly via `python-dotenv` — length checks only, no value display.

### Task 0.4 — Implement Azure Maps client in `tools.py` (TDD)

Test: `tests/test_azure_maps_client.py` — mock HTTP responses, verify rate-limited POI Search call returns expected structure. Tests rate-limit jitter timing. Tests 429 back-off.

Implementation: `tools.py` adds `class AzureMapsClient` with:
- `geocode(city, state) -> (lat, lon)` — uses Azure Maps Search Address API
- `search_poi(category, lat, lon, radius_m, limit) -> list[dict]` — POI Search call
- Internal token-bucket rate limiter at `AZURE_MAPS_RATE_LIMIT_QPS`
- Random jitter `0..AZURE_MAPS_JITTER_MS` per call
- Exponential back-off on 429 / 5xx (base 1s, max 60s)

Worktree: `phase0/azure-maps-client`. Code-reviewed before merge.

### Task 0.5 — Replace `agents/sourcer.py` with Azure Maps version (TDD)

Test: `tests/test_sourcer.py` — given `state="FL"`, `city="Orlando"`, `niche="kitchen remodelers"`, `count=5`, returns 5 normalized leads with `business_name`, `address`, optional `phone`, optional `website`.

Implementation:
- Geocode city → (lat, lon) via Azure Maps client.
- POI Search with `categorySet=<construction/renovation/kitchen-remodeling>` (look up correct Azure Maps category code from POI category reference; document the choice in code comments). Radius defaults to 25 km, configurable via `config.py`.
- Query-pattern diversity: rotate categories within the same niche if multiple match (e.g., "remodeling contractor" + "kitchen designer" + "general contractor"), distribute across batches.
- Remove Google Places code from `agents/sourcer.py` (not commented — removed). Legacy preserved on a tag `legacy/google-places-sourcer` if needed.

Worktree: `phase0/sourcer-azure-maps`. Code-reviewed.

### Task 0.6 — Implement Bing Web Search client in `tools.py` (TDD)

Test: `tests/test_bing_search_client.py` — mock response, verify search returns top non-directory URL.

Implementation: `class BingSearchClient` with `search(query, count=5)` method. Uses `BING_SEARCH_KEY`. Returns parsed result list with URLs.

Worktree: `phase0/bing-search-client`. Code-reviewed.

### Task 0.7 — Implement `agents/website_finder.py` (TDD)

Test: `tests/test_website_finder.py` — given business name + city + state, returns URL or None.

Implementation:
1. Pattern-guess: `<slug>.com`, `<slug>.net`, `<slug>.co`, `kitchensby<slug>.com`. HEAD-request each with timeout=5s. Return first 200 OK that's not a parked domain (heuristic: page size > 1KB, no parking-page signature like `Buy this domain` or `parked.aabaco.com`).
2. Fall back to Bing Web Search: query `"<business name>" <city> <state>`. Filter results: skip directory domains (`yelp.com`, `bbb.org`, `angi.com`, `homeadvisor.com`, `houzz.com`, `facebook.com`, `instagram.com`, `linkedin.com`, `mapquest.com`, `yellowpages.com`).
3. HEAD-validate the candidate URL.
4. Return None if both paths fail.

Worktree: `phase0/website-finder`. Code-reviewed.

### Task 0.8 — Wire it up in `run.py` (verify only)

No logic changes (Premise 5 lock). Confirm `python run.py --city "Orlando" --state FL --count 3 --niche "kitchen remodelers"` runs end-to-end and produces non-empty output. This is wiring verification, not smoke test — output quality judged in Phase 1.

**Phase 0 deliverables:**
- New `agents/sourcer.py` (Azure Maps), `agents/website_finder.py` (NEW), `tools.py` extensions (Azure Maps + Bing clients) merged
- `tests/` populated with green test suite covering all new code
- `.env` populated with Azure + Bing keys (operator)
- Pipeline runs end-to-end on count=3 producing non-empty output

**Gate to Phase 1:** Task 0.8 produces non-empty CSV with lead count matching `--count` argument.

---

## PHASE 1 — Smoke Test (Day 1–2 after Phase 0)

### Task 1.1 — count=5 smoke run

Command: `python run.py --city "Orlando" --state FL --count 5 --niche "kitchen remodelers"`. Capture stdout/stderr to `output/smoke-5-stdout.log`; the master CSV; state files.

### Task 1.2 — Operator spot-check on count=5 (HUMAN)

For each of the 5 rows, operator opens website + verifies: business legitimacy, owner-name accuracy, email accuracy. Records per row: business-fit (Y/N), owner-name (Y/N/partial), email (Y/N/partial).

### Task 1.3 — Resume contract verification on count=20

Start: `python run.py --city "Orlando" --state FL --count 20 --niche "kitchen remodelers"`. Wait until ≥5 leads in state. SIGINT. Capture campaign-id. Resume: `python run.py --resume <campaign-id>`. Verify: continues from prior position, no duplicate rows, completes to count=20.

### Task 1.4 — Spot-check count=20 + write findings

Operator: per-row protocol from 1.2 across all 20 rows.

Claude writes `docs/smoke-orlando-20.md`:
- Header: total rows; accurate-owner-name count (target ≥16/20 = 80%); email-find-rate; business-fit-rate; website-finder hit-rate; Azure Maps API errors; resume contract verdict.
- Body: one line per failure, format `<symptom> | <suspected file> | <fix sketch> | <count>`, grouped by symptom, sorted by frequency desc.

Failure categories: `wrong-business-fit`, `name-missing`, `name-wrong`, `email-missing`, `email-wrong`, `website-finder-miss`, `azure-maps-rate-limited`, `azure-maps-throttled`, `bing-search-error`, `js-rendered-page`, `crash-or-exception`, `other`.

**Phase 1 deliverables:** `docs/smoke-orlando-20.md`, `output/smoke-5-stdout.log`, count=20 master CSV.

**Gate to Phase 2:** findings file populated. If zero failures + resume contract holds, Phase 2 is empty; jump to Phase 3.

---

## PHASE 2 — Tightening (Day 3–5, conditional on Phase 1)

One task per finding row, frequency-ordered, TDD-enforced, on worktree branches, code-reviewed before merge.

### Conditional sub-block 2.PW — Playwright fallback

Trigger: `js-rendered-page` finding count ≥ `0.30 * total_findings`.

If triggered: add Playwright fallback in `agents/website_crawler.py`. Default off; flip on via `config.py` flag. Cost-discipline check: Playwright is open-source, no new paid surface. Extend timeline ~2 days.

If NOT triggered: log to "Deferred to v2" section.

### Conditional sub-block 2.AD — Adaptability hooks (each gated independently)

- **2.AD-1: Sourcer overflow early-exit** in `agents/sourcer.py` — only if smoke shows Azure Maps returns >`target * 1.3` candidates before downstream filtering.
- **2.AD-2: Owner-researcher Phase 2 cap** in `agents/owner_researcher.py` — only if Phase 2 fallback fires unexpectedly often.
- **2.AD-3: Lead-filter junk warning** in `agents/lead_filter.py` — only if >75% of leads filter as junk/wrong-fit.
- **2.AD-4: Website-finder hit-rate alert** in `agents/website_finder.py` — only if hit-rate <60%.
- **2.AD-5: Azure Maps throttle handler** in `tools.py` — only if smoke surfaces sustained 429/5xx responses, indicating mitigation 8 (rate limit) is too aggressive.

### Conditional sub-block 2.LE — LLM email extractor (Haiku)

Trigger: smoke finding `email-missing` count > `0.20 * leads_with_known_website`.

If triggered: add Phase 1.5 step in `owner_researcher.py` — single Haiku call over crawled text for email extraction with obfuscation handling. Cost ~.001/lead, ~.50/500-lead batch.

If NOT triggered: log as deferred.

### Cost-discipline gate (every Phase 2 task)

Before generating any task: would the proposed fix introduce a new external API/library/service requiring payment beyond Anthropic + Azure Maps + Bing Web Search? If yes → STOP and escalate.

---

## PHASE 3 — Validation (Day 6–7)

### Task 3.1 — count=50 validation + spot-check

Command: `python run.py --city "Orlando" --state FL --count 50 --niche "kitchen remodelers"`. Spot-check 20 random rows via `random.seed(42); random.sample(range(50), 20)`.

Pass: ≥16/20 (80%) accurate owner-name + business-fit AND email-find-rate ≥40% on full 50.
Fail: STOP, generate Phase 2.5 follow-up tasks, re-validate before count=500.

### Task 3.2 — count=500 production run

Command: `python run.py --city "Orlando" --state FL --count 500 --niche "kitchen remodelers"`. Time end-to-end. Confirm <2 hrs compute + <1 hr operator review. Output: 500-lead FindyMail-ready CSV in `output/`.

### Task 3.3 — Hand-off

Print full path of FindyMail CSV. Print summary: total leads, business-fit rate, owner-name accuracy, email-find-rate, website-finder hit-rate, sourcing time, files modified during tightening, mitigation-compliance audit (rate-limit honored, no 429 sustained periods, no out-of-scope file modified).

Tool's job is done. Operator-side workflow downstream.

---

## Plan-level success criteria

- All Phase 0 components merged with green tests
- `.env` populated with both Azure + Bing keys (operator)
- Phase 1 deliverables exist; `docs/smoke-orlando-20.md` populated
- Phase 2 finding-derived tasks (frequency ≥2) merged
- Phase 3 validation passes ≥16/20 spot-check + ≥40% email-find-rate
- Phase 3 production CSV produced within timing budget
- No file outside Files-in-Scope modified
- No paid surface beyond Anthropic + Azure Maps + Bing Web Search introduced
- `run.py` did not gain LLM-decision logic
- All 11 mitigations (7 operator-side, 4 code-side) verified before production-volume run

## Open questions for go-time

1. Operator confirms separate Azure subscription provisioned, S1 tier active, payment method attached, both keys in `.env`.
2. Subagent-driven-development skill upgrade vs. linear executing-plans? Skill recommended subagent-driven for higher quality. Operator has not yet confirmed switch.
