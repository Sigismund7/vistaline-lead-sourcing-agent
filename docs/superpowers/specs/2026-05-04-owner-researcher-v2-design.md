# Owner Researcher v2 — Design Spec

**Date:** 2026-05-04
**Author:** Daschel + Claude (brainstorming pair)
**Status:** Approved, ready for implementation plan

---

> # 🚨🚨🚨 ACTION REQUIRED — DASCHEL 🚨🚨🚨
> # UPGRADE OPENCORPORATES SUBSCRIPTION
>
> **Free tier = 50 lookups/day. This will choke any campaign over ~50 leads.**
>
> Go to: **https://opencorporates.com/api_accounts/new**
>
> - Sign up for a paid API plan
> - Paid tier is ~$0.50 per 1,000 lookups (dirt cheap)
> - Set the API token as `OPENCORPORATES_API_KEY` in:
>   - Railway env vars (backend)
>   - `.env.local` (local dev)
>
> **Until upgraded:** Phase 3 will silently rate-limit at 50 leads/day and fall through to Phase 4 (paid web_search). You'll quietly burn extra Anthropic dollars.
>
> # 🚨🚨🚨 DO NOT FORGET 🚨🚨🚨

---

## Goal

Push owner-name hit rate from ~75% to **~92-95%** while keeping per-lead Anthropic spend at or below current levels. Universal coverage across all 50 US states without per-state adapters.

## Non-goals (v1)

- Per-state contractor licensing-board adapters (CSLB, Sunbiz, etc.)
- Cross-campaign caching of lookup results
- Cross-validation / "confirmed by 2 sources" UI signals
- Google/Yelp review-response scraping
- LinkedIn / Facebook / WHOIS signals
- Re-researching leads from prior campaigns

## Pipeline architecture

Four sequential phases per lead. Each phase short-circuits when the prior found a confident answer (`confidence in ("high", "medium")`). All four phases are nationwide — same code path runs in any US state.

| # | Phase | Source | Cost | Toggleable | Default |
|---|---|---|---|---|---|
| 1 | Website crawl | Direct HTTP + BeautifulSoup + Claude parse | Free | No (always on) | — |
| 2 | Houzz scrape | Direct HTTP scrape of Houzz search + profile page | Free | Yes | ON |
| 3 | Business registry | OpenCorporates API officer lookup | Free tier (50/day), paid tier ~$0.50/1k | Yes | ON |
| 4 | Web search fallback | Claude `web_search` tool: BBB → Google "owner" → Google "founder" | ~$0.04/lead reaching this phase | Yes | ON |

**Cumulative hit rate** (estimated): ~92-95%
**Average cost per lead** when all toggles on: ~$0.012 (Phase 4 only fires on the ~15% surviving phases 1-3)

## UI changes — new-campaign form

Three checkboxes added to `frontend/app/campaigns/new/page.tsx`, persisted as columns on the `campaigns` table:

- ☑ **Houzz lookup** *(free)* — default ON
- ☑ **Business registry** *(free, may rate-limit)* — default ON
- ☑ **Web search fallback** *(~$0.04/lead)* — default ON

Phase 1 is not toggleable. Toggles are passed through to the runner, persisted on the campaign row, and read by the owner_researcher to decide which phases to run.

## Backend module structure

```
agents/
  owner_researcher.py          # orchestrator, decides phase ordering + toggles
  sources/
    owners/                    # NEW directory
      website.py               # Phase 1 (extracted from existing _phase1_website)
      houzz.py                 # Phase 2 (NEW)
      opencorporates.py        # Phase 3 (NEW)
      websearch.py             # Phase 4 (extracted from existing _phase2_bbb)
tools.py                       # adds HouzzClient, OpenCorporatesClient
```

Each phase module exports a single function with a uniform signature:

```python
def lookup(lead: Lead, state: CampaignState, anthropic_key: str) -> dict:
    """Return {owner_full_name, owner_email?, source_url?, evidence?, confidence}.

    confidence: "high" | "medium" | "low" | "none"
    """
```

This makes the orchestrator a simple loop over enabled phases, each returning the same shape.

## Source-specific design

### Phase 2 — Houzz

**Disambiguation strategy: name + city fuzzy match (Option B from brainstorming).**

Per lead:
1. HTTP GET `https://www.houzz.com/professionals/search?q={url-encoded business_name}`
2. Parse search results HTML, extract `(name, location, profile_url)` for up to 20 results
3. For each result, score `rapidfuzz.token_sort_ratio(result_location_city, state.city)`
4. Pick the highest score ≥ 85; else return `confidence="none"`
5. Fetch the matched profile page, extract the "About" / "Overview" section text
6. Send text to Claude (Sonnet, low max_tokens) to pull owner name + optional owner email

**Anti-bot caveats:**
- Houzz uses Cloudflare. Use a realistic User-Agent (Chrome on macOS).
- Respect a soft rate ceiling: a single lead = at most 2 HTTP requests (search + profile). With `MAX_PARALLEL=10` leads concurrent, that's 20 simultaneous requests max.
- If we get a 403 / Cloudflare challenge: log, mark phase as "failed for this lead", fall through to Phase 3.

**Failure mode:** silent fallthrough. Houzz being down or blocking us never breaks a campaign.

### Phase 3 — OpenCorporates (business registry)

**API:** `https://api.opencorporates.com/v0.4/companies/search?q={name}&jurisdiction_code=us_{state}&api_token={KEY}`

Per lead:
1. Search by `business_name` + `jurisdiction_code` derived from `state.state_abbr` (e.g., "FL" → `us_fl`)
2. If multiple results, fuzzy-match address city; pick best match.
3. Fetch the matched company's officer list.
4. Look for officer titles matching `Owner|President|CEO|Principal|Founder|Manager` (in that priority order).
5. Return the highest-priority officer's name with `confidence="high"`.

**Failure modes:**
- 429 rate-limit (free tier exceeded): log, return `confidence="none"`, fall through.
- No results / no matching officer: log, fall through.
- 5xx / network error: log, fall through.

**Env var:** `OPENCORPORATES_API_KEY` added to Railway secrets and `frontend/.vercel/` env vars.

### Phase 4 — Web search fallback (existing, retained)

No code change to the search prompt. Renamed UI label from "BBB + Google fallback" to "Web search fallback" because the toggle controls all three searches (BBB, Google "owner", Google "founder"), not just BBB.

## Schema changes

```sql
ALTER TABLE campaigns ADD COLUMN use_houzz BOOLEAN NOT NULL DEFAULT TRUE;
ALTER TABLE campaigns ADD COLUMN use_registry BOOLEAN NOT NULL DEFAULT TRUE;
ALTER TABLE campaigns ADD COLUMN use_websearch BOOLEAN NOT NULL DEFAULT TRUE;
```

Lead schema unchanged. The `owner_source` field already accepts arbitrary strings; new values: `"website"`, `"houzz"`, `"opencorporates"`, `"web_search"`.

## State persistence — `--resume` behavior preserved

- `state.is_done("owner_researcher")` checkpoint still applies to the agent overall.
- Per-lead pre-existing `owner_full_name` is still skipped (line 239 of current code: `if l.kept and not l.owner_full_name`). Confirmed in brainstorming as desired behavior.

## Concurrency

- `MAX_PARALLEL=10` retained (current owner_researcher value, conforms to CLAUDE.md ceiling).
- Each parallel worker constructs its own `Anthropic`, `HouzzClient`, `OpenCorporatesClient` — never shared (CLAUDE.md thread-safety rule).
- Phases run sequentially *within* a single lead's worker; parallelism is across leads.

## Toggles in the runner

The orchestrator reads three booleans from the campaign row and constructs the phase list dynamically:

```python
phases = [website_phase]
if campaign.use_houzz: phases.append(houzz_phase)
if campaign.use_registry: phases.append(registry_phase)
if campaign.use_websearch: phases.append(websearch_phase)
```

Each parallel worker iterates `phases` and short-circuits on the first `confidence in ("high", "medium")`.

## Cost discipline (CLAUDE.md compliance)

- **No new paid Anthropic surfaces.** Houzz and OpenCorporates are free / direct HTTP.
- **OpenCorporates paid tier upgrade** is a configuration change handled by the user, not new code we add. The code accepts whatever API key is set.
- **Phase 4 (web_search) cost is unchanged** from current Phase 2.

## Testing approach

- **Unit tests** (`tests/test_houzz.py`, `tests/test_opencorporates.py`): pure-Python helpers — fuzzy-match scoring, officer-priority selection, jurisdiction code mapping. No mocks, no API calls.
- **Smoke test** after each agent module change: `python -c "from agents.sources.owners import website, houzz, opencorporates, websearch; print('OK')"`.
- **Integration test**: real `python run.py --city "Tampa" --state FL --count 10` campaign, inspect master CSV, confirm `owner_source` distribution looks sane (mix of values, not 100% web_search).

## Acceptance criteria

1. Three toggles render on `/campaigns/new`, persist to DB, and are reflected in the running pipeline.
2. A campaign with all three toggles ON achieves >85% owner-name hit rate on a 25-lead test in any US state.
3. A campaign with **only websearch ON** (Houzz + registry off) behaves identically to current production behavior.
4. A campaign with **all three toggles OFF** runs Phase 1 only, no API spend beyond Anthropic Sonnet calls for website parsing.
5. OpenCorporates rate-limit (HTTP 429) silently falls through; campaign still completes.
6. Cloudflare-blocked Houzz request silently falls through; campaign still completes.
7. `python run.py --resume <id>` resumes mid-research without re-doing leads that already have an owner.
