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
| Owner name lookup | `owner_researcher` — two-phase, parallel × 10 |
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
  ├── agents/owner_researcher.py       Two-phase owner lookup, parallel × 10
  │     ├── website_crawler.py         Phase 1: direct HTTP + BeautifulSoup (free)
  │     └── (Claude + web_search)      Phase 2: BBB / Google fallback
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

For every kept lead, two phases run in order with an early-exit when Phase 1 fully resolves the lead.

**Phase 1 — website crawl (free).**
Fetches the homepage, finds links to About / Team / Meet / Owner / Founder / Contact sub-pages on the same domain, fetches up to 5 of them, and sends the extracted text to Claude Sonnet. Claude applies SOP rules to find the owner's name and — when a direct owner email is visible on the site — captures that too. Generic `info@` / `contact@` addresses are rejected. When Phase 1 returns both name AND email, the lead is fully resolved without FindyMail spending a credit.

**Phase 2 — BBB + Google web search.**
Only runs when Phase 1 returns no confident name. Uses Claude with `web_search` to hit the BBB listing first, then falls back to Google. Produces a name only.

**Per-lead checkpointing.** Each result is applied to the lead immediately as its future completes (not in a post-loop batch). `state.save_leads()` is called after every completion so `--resume` skips already-researched leads. A mid-batch crash loses at most one in-flight result, not the entire batch.

Typical hit rate: ~70–80% combined.

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
| `GOOGLE_PLACES_KEY` | [console.cloud.google.com](https://console.cloud.google.com) — Places API (New), billing enabled |
| `AZURE_MAPS_KEY` | Azure Portal → Azure Maps account → Authentication |
| `YELP_FUSION_KEY` | [fusion.yelp.com](https://fusion.yelp.com) → Create app → API key |
| `BRAVE_SEARCH_KEY` | [api.search.brave.com](https://api.search.brave.com) — Free tier: 2,000 queries/month |

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

## Cost per city (50 leads)

| Service | Cost |
|---|---|
| Azure Maps POI Search | ~$0.05 est. |
| Yelp Fusion | Free tier (500 calls/day) |
| Brave Web Search | Free tier (2,000 queries/month shared) |
| Anthropic API (filter + owner research) | ~$0.30–$0.80 |
| **Total** | **under $1** |

Repeat campaigns on the same city are cheaper — the cross-run dedup cache filters already-seen leads before they reach the LLM filter.

---

## Known limits

- **Owner hit rate ~70–80%.** JS-only sites (Wix, single-page React apps) won't yield readable text — those fall to Phase 2. Leads with no confident name from either phase are excluded from the FindyMail CSV but visible in the master CSV.
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
- [`docs/superpowers/specs/2026-05-04-owner-researcher-v2-design.md`](docs/superpowers/specs/2026-05-04-owner-researcher-v2-design.md) — Planned v2 owner researcher with Houzz scrape + OpenCorporates registry (target hit rate ~92–95%)
- [`docs/superpowers/plans/`](docs/superpowers/plans/) — Implementation plans for each development phase
