# Vistaline Lead-Gen Sourcer

Produces a FindyMail-ready leads CSV for a single US city. Sources local remodeling contractors from Azure Maps and Yelp Fusion, filters out franchises and junk via Claude, looks up owner names, and outputs the four-column upload file FindyMail expects.

## What it automates

| SOP step | Automated by |
|---|---|
| Niche + city targeting | CLI flags (`--city`, `--state`, `--niche`) |
| Lead sourcing | `sourcer` — Azure Maps + Yelp Fusion in parallel |
| Cross-run dedup | `leads_cache` — SQLite, 30-day TTL per city |
| Website discovery | `website_finder` — Brave search + HEAD validation |
| Filter & clean | `lead_filter` — Claude Haiku, SOP rules, batches of 25 |
| Owner name lookup | `owner_researcher` — three-phase + eponymous heuristic, parallel × 10 |
| FindyMail upload CSV | `csv_assembler` |

What's still manual on purpose: the FindyMail upload itself, all personalization, Clipio thumbnails, Instantly setup, and launch. This system delivers the input file you drop into FindyMail.

---

## Architecture

```
run.py (orchestrator — deterministic Python, no LLM)
  │
  ├── agents/sourcer.py
  │     ├── sources/azure_maps.py      Azure Maps POI Search (parallel worker A)
  │     ├── sources/yelp_fusion.py     Yelp Fusion API (parallel worker B)
  │     ├── website_finder.py          Brave Web Search + HEAD validation
  │     └── leads_cache.py             SQLite cross-run dedup (30-day TTL)
  │
  ├── agents/lead_filter.py            Claude Haiku — SOP filter rules
  │
  ├── agents/owner_researcher.py       Three-phase owner lookup, parallel × 10
  │     ├── (eponymous name heuristic) Phase 0: free pre-check (e.g. "Andrew Roby")
  │     ├── sources/owners/website.py  Phase 1: direct HTTP + Claude Sonnet (free)
  │     ├── sources/owners/opencorporates.py
  │     │                              Phase 2: OpenCorporates officer API (free tier)
  │     └── sources/owners/websearch.py
  │                                    Phase 3: BBB + Houzz + Google + review responses
  │                                             via Claude web_search (~$0.05/lead)
  │
  └── agents/csv_assembler.py          FindyMail CSV + master audit CSV
```

`state.py` holds the shared `CampaignState` dataclass — every agent reads and writes to it, and it persists to Supabase after each step. `config.py` centralises all API keys and tuning parameters. `tools.py` holds external API clients (no business logic, no LLM calls).

### Sourcing layer

The sourcer fans out two API calls in parallel via `ThreadPoolExecutor(2)`:

- **Azure Maps POI Search** — covers all 50 US states uniformly. Searches 3 keyword variants per niche (e.g. `"kitchen and bath remodeling"`, `"kitchen cabinet installation"`, `"bathroom remodeling"`).
- **Yelp Fusion** — supplements with review-site data. Also 3–4 keyword variants per niche. Kitchen niches deliberately exclude a bare category sweep to avoid food-business noise.

After fanout, results are merged via rapidfuzz `token_sort_ratio` (threshold 85). If the same business appears in both sources, Azure wins and its website/metadata are kept. Merged leads are tagged `azure_maps+yelp_fusion` in the audit trail.

**Website finder** runs on merged leads that have no website. It queries Brave Web Search, validates candidates with an HTTP HEAD check, and rejects a maintained blocklist of directory/aggregator/news URLs — `yelp.com`, `bbb.org`, `prnewswire.com`, `prweb.com`, and others.

**Cross-run dedup cache** (`agents/leads_cache.py`) prevents re-sourcing the same businesses across multiple runs for the same city. Source + ID pairs are stored in SQLite with a 30-day TTL. A lead seen within 30 days is filtered before it reaches the LLM filter, saving both Anthropic and API spend on repeat campaigns.

### Filter layer

`lead_filter.py` sends leads to Claude Haiku in batches of 25 with the SOP rules:

- Reject national franchises (Re-Bath, Bath Fitter, Bath Planet, Power Home Remodeling, Renuity, …)
- Reject toll-free numbers (800, 888, 877, 866 area codes)
- Reject area codes that don't match the target metro
- Reject single-service suppliers (tile supply, countertop slab yard, shower doors only, flooring wholesale)
- Reject out-of-area chains masquerading as local

Each batch returns a `KEEP`/`REJECT` verdict with a reason. Rejected leads still appear in the master CSV.

### Owner research layer

For every kept lead, phases run in order with early-exit on the first high/medium-confidence result.

**Phase 0 — eponymous name heuristic (free, no API).**
Before any network call, the business name itself is checked against a tight pattern: exactly two title-cased alphabetic words, neither all-caps (rules out acronyms like RRH/JFK), neither matching a blocklist of trade words (`construction`, `kitchen`, `design`, `the`, etc.). Catches contractors named after their owner — "Andrew Roby", "Bob Jones" — at zero cost. Returns `confidence=medium`.

**Phase 1 — website crawl (free).**
Fetches the homepage, finds links to About / Team / Meet / Owner / Founder / Contact sub-pages on the same domain, fetches up to 5 of them, and sends the extracted text to Claude Sonnet. Claude applies SOP rules to find the owner's name and — when a direct owner email is visible on the site — captures that too. Generic `info@` / `contact@` addresses are rejected. When Phase 1 returns both name AND email, the lead is fully resolved without FindyMail spending a credit.

**Phase 2 — OpenCorporates registry (free tier).**
A pure REST API call to OpenCorporates' v0.4 endpoint, looking up the company by name + state jurisdiction (`us_wi`, `us_nc`, etc.) and pulling the highest-priority current officer (Owner > President > CEO > Principal > Founder > Manager > Director). Free unauthenticated tier is 50 lookups/day; an `OPENCORPORATES_API_KEY` env var lifts that limit. Silent fallthrough on 429, no results, or matching officer not found — most coverage gaps here are sole proprietors and single-member LLCs that simply aren't in any state registry.

**Phase 3 — web search fallback (~$0.05/lead).**
Only runs when phases 0–2 return no confident name. Uses Claude with `web_search` to try, in order: BBB principal listing, Houzz profile via `site:houzz.com`, Google "owner" search, Google review responses ("Thanks — John, Owner" / "John and his team"), Google "founder" search. Confidence scoring distinguishes full-name-with-title (high) from first-name-only signed reviews (medium). `max_uses=7` per lead.

**Per-lead checkpointing.** Each result is applied to the lead immediately as its future completes (not in a post-loop batch). `state.save_leads()` is called after every completion so `--resume` skips already-researched leads. A mid-batch crash loses at most one in-flight result, not the entire batch.

Typical hit rate varies sharply by market: ~50% in metros dominated by kitchen/bath showrooms and design-build firms (Charlotte), ~75–90% in smaller markets dominated by sole-proprietor remodelers.

---

## Setup

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
# Fill in the required keys
```

### API keys

| Key | Where to get it |
|---|---|
| `ANTHROPIC_API_KEY` | [console.anthropic.com](https://console.anthropic.com) |
| `AZURE_MAPS_KEY` | Azure Portal → Azure Maps account → Authentication |
| `YELP_FUSION_KEY` | [fusion.yelp.com](https://fusion.yelp.com) → Create app → API key |
| `BRAVE_SEARCH_KEY` | [api.search.brave.com](https://api.search.brave.com) — Free tier: 2,000 queries/month |
| `OPENCORPORATES_API_KEY` | Optional. [opencorporates.com/api_accounts/new](https://opencorporates.com/api_accounts/new) — Phase 2 falls back to the unauthenticated 50/day tier when blank |

Optional (needed for the web UI and Railway backend):

| Key | Purpose |
|---|---|
| `SUPABASE_URL` | Campaign state + leads persistence |
| `SUPABASE_SERVICE_ROLE_KEY` | Supabase admin access |
| `VISTALINE_API_SECRET` | Frontend → backend auth header |

---

## Running

```bash
# 50 kitchen-remodeling leads in Orlando, FL
python run.py --city "Orlando" --state FL --niche "kitchen remodeling"

# Custom count
python run.py --city "Tampa" --state FL --count 75

# Different niche
python run.py --city "Austin" --state TX --niche "bathroom remodeling"

# Resume a crashed or stopped run
python run.py --resume <campaign-id>
```

State persists to Supabase after every agent step. If anything crashes, the printed campaign ID is your resume key. On resume:

- **Sourcer** — re-runs from scratch (fast, no LLM spend; dedup cache prevents re-adding seen leads)
- **Lead filter** — skipped entirely if already marked done
- **Owner researcher** — skips leads that already have `owner_full_name` set (per-lead checkpoint)
- **CSV assembler** — re-generates from persisted leads

---

## Output

Two files in `output/`:

**`<city>_<state>_<niche>_<date>__findymail.csv`** — the deliverable. Four columns FindyMail expects:

```
First Name, Last Name, Company, Domain
```

Only includes kept leads that have both an owner name and a domain.

**`<city>_<state>_<niche>_<date>__master.csv`** — full audit trail. Every lead the sourcer pulled — kept or rejected — with all fields: phone, address, area code, website, reject reason, owner research source, and email if captured in Phase 1.

---

## Cost breakdown

### Per-campaign cost (50 leads)

| Service | Free tier | Paid rate | Typical 50-lead cost |
|---|---|---|---|
| Azure Maps POI Search | $200 credit/month (new accounts) | $4.50 per 1,000 transactions | ~$0.05 |
| Yelp Fusion | 500 calls/day | — | $0 |
| Brave Web Search | 2,000 queries/month | $3 per 1,000 after free tier | $0 (within free tier) |
| Anthropic — lead filter | — | Claude Haiku ~$0.80/1M input tokens | ~$0.02–$0.05 |
| Anthropic — owner research | — | Claude Sonnet ~$3/1M input tokens | ~$0.30–$0.75 |
| **Total** | | | **$0.35–$0.85** |

### Where the money actually goes

**Lead filter (Claude Haiku)** is the cheap step. 50 leads batched into 2 groups of 25, each prompt ~2,000 tokens. Total: ~4,000 input tokens → less than $0.01. Haiku is used here deliberately — it's fast, cheap, and the classification task doesn't need Sonnet reasoning.

**Owner researcher (Claude Sonnet)** is where most of the spend lives. Phase 0 (eponymous heuristic) is free. Phase 1 (website crawl) is one Sonnet call with up to 5 scraped pages (~5,000–15,000 tokens) per lead. Phase 2 (OpenCorporates) is free. Phase 3 only fires for leads that escape phases 0–2 and adds ~2,000 tokens per lead for the `web_search` tool round-trips (`max_uses=7`). A 50-lead campaign with a typical ~50% Phase 1 hit rate runs about 25 Phase 1 calls + 10 Phase 3 calls, totalling roughly 200,000–400,000 input tokens → **$0.30–$0.75**.

**Brave Web Search** (website finder) fires once per lead that arrives with no website from the sourcer. In practice that's 20–40% of leads — maybe 15–25 queries per campaign. Well within the 2,000/month free tier for any reasonable campaign cadence.

**Azure Maps and Yelp** are negligible. The sourcer issues 3–4 keyword queries per niche per source (6–8 total API calls) regardless of how many leads come back. Azure is free for the first $200 of usage each month on new accounts; after that it's $4.50/1,000 transactions — so even at paid rates that's under $0.05 per campaign.

### Repeat campaigns on the same city

The cross-run dedup cache (SQLite, 30-day TTL) tracks which leads have already been sourced. On a second run in the same city within 30 days, already-seen leads are filtered out before they ever reach the LLM filter. This means:

- **Zero Anthropic spend** on re-filtering leads you already processed
- **Zero owner research spend** on businesses you already looked up
- The sourcer still runs (fast, no LLM) to catch genuinely new businesses that appeared since the last run

In practice: the first run for a city costs $0.35–$0.85. A re-run two weeks later, targeting new leads only, costs a fraction of that.

---

## Known limits

- **Owner hit rate is market-dependent.** Smaller metros with sole-proprietor remodelers see 75–90%. Metros dominated by kitchen/bath showrooms and design-build firms can drop to 40–55% — those operations rarely list individual owners anywhere public. JS-only sites (Wix, single-page React apps) won't yield readable text and fall through to Phase 3. Leads with no confident name are excluded from the FindyMail CSV but visible in the master CSV.
- **Azure Maps and Yelp cap at ~50 results per query.** 3–4 keyword variants per niche are used to widen coverage.
- **Cross-run dedup TTL is 30 days.** Configurable via `leads_cache_ttl_days` in `config.py`.
- **Brave free tier is 2,000 queries/month.** A budget guard in `config.py` caps usage; website finder degrades gracefully when the cap is hit.
- **Each parallel worker constructs its own API client.** Clients carry token-bucket state and are not thread-safe — they must not be shared across `ThreadPoolExecutor` workers.

---

## Web UI

A Next.js 16 frontend on Vercel drives campaign creation and lets you watch the live event stream, browse results, and download CSVs.

**Live:** `https://frontend-eight-xi-78.vercel.app`
**Backend:** `https://vistaline-lead-sourcing-agent-production.up.railway.app`

See [`frontend/AGENTS.md`](frontend/AGENTS.md) for frontend setup and deploy instructions.

---

## Further reading

- [`docs/plan-tightening-v1.md`](docs/plan-tightening-v1.md) — Phase 2 quality improvements: keyword noise fix, website blocklist, cross-run dedup, owner research checkpointing
- [`docs/superpowers/specs/2026-05-04-owner-researcher-v2-design.md`](docs/superpowers/specs/2026-05-04-owner-researcher-v2-design.md) — Owner researcher v2 design (shipped 2026-05-04). Note: the original Houzz direct-scrape phase was replaced with a `site:houzz.com` search inside Phase 3 after Houzz's SPA proved unscrapable.
- [`docs/superpowers/specs/2026-05-04-lead-stage-tracking-design.md`](docs/superpowers/specs/2026-05-04-lead-stage-tracking-design.md) — Planned: per-lead lifecycle stages (`researched → exported → processed`) so unfinished campaigns are visible at a glance.
- [`docs/superpowers/plans/`](docs/superpowers/plans/) — Implementation plans for each development phase
