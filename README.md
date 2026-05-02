# Vistaline Lead-Gen Sourcer

Produces a FindyMail-ready leads CSV for a single city. Sources contractors from Google Places, filters out franchises and junk, looks up owner names, and outputs the four-column upload file FindyMail expects.

## What it replaces from the SOP

| SOP step | Automated by |
|---|---|
| 2–3. Niche + Google Maps URL building | `sourcer` (no URLs needed — Places API) |
| 4. Lead scraping | `sourcer` (Google Places API) |
| 5. Filter & clean leads | `lead_filter` (Claude) |
| 6. BBB owner name lookup | `owner_researcher` (Claude + web search, parallel) |
| 7-prep. Build FindyMail upload CSV | `csv_assembler` |

What's still manual on purpose: the FindyMail upload itself, all personalization, Clipio thumbnails, Instantly setup, and launch. This system delivers the input file you drop into FindyMail, full stop.

## Why Google Places API (not PhantomBuster, not direct scraping)

- **No subscription**: $0 fixed cost vs $56/mo PhantomBuster.
- **Free tier**: 5,000 free Pro-tier events/month — covers 50+ cities.
- **Marginal cost**: ~$0.017 per place search after the free tier.
- **Reliable**: official API, won't break when Google changes Maps' HTML.
- **Fast**: synchronous JSON, no browser, no polling.

Direct browser scraping is the alternative. Free, but Google actively blocks scrapers, the HTML changes regularly, and you'll spend more on debugging than the API would cost. Skip it.

## Setup

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
# Fill in the two keys
```

### Keys you need

- **`ANTHROPIC_API_KEY`** — [console.anthropic.com](https://console.anthropic.com)
- **`GOOGLE_PLACES_KEY`** — [console.cloud.google.com](https://console.cloud.google.com):
  1. Create a project (or pick one).
  2. Enable the **Places API (New)** under APIs & Services → Library.
  3. APIs & Services → Credentials → Create credentials → API key.
  4. Restrict the key to the Places API only (good hygiene).
  5. Enable billing on the project. The free tier covers your usage; this is just the gate Google requires.

## Running

```bash
# Default: 50 bathroom-remodeling leads in Orlando, FL
python run.py --city "Orlando" --state FL

# Override count
python run.py --city "Tampa" --state FL --count 75

# Different niche
python run.py --city "Austin" --state TX --niche "kitchen remodeling"

# Resume a crashed or stopped run
python run.py --resume <campaign-id>
```

State persists to `state/<campaign-id>.json` after each step. If anything crashes, the printed campaign ID is your resume key — no re-scraping, no re-spending Claude tokens on already-filtered leads.

## Output

Two files in `output/`:

**`<city>_<state>_<niche>_<date>__findymail.csv`** — the deliverable. Four columns exactly as FindyMail expects:

```
First Name, Last Name, Company, Domain
```

Only includes leads that have both an owner first name AND a domain (the leads where FindyMail can actually find an email).

**`<city>_<state>_<niche>_<date>__master.csv`** — full audit trail. Every lead the sourcer pulled, kept or rejected, with all fields including reject reasons, phone, address, area code, owner research source. Useful for spot-checking and for any manual fallback work on leads that didn't get an owner found.

## Architecture

Three sub-agents and an orchestrator:

```
run.py (orchestrator)
  ├── agents/sourcer.py             Google Places API
  ├── agents/lead_filter.py         Claude — SOP filter rules
  ├── agents/owner_researcher.py    Two-phase owner lookup, parallel × 10
  │     ├── website_crawler.py      Phase 1: crawl company site (free)
  │     └── (Claude + web_search)   Phase 2: BBB/Google fallback
  └── agents/csv_assembler.py       Final CSVs
```

`tools.py` holds the Places API client. `state.py` holds the shared mutable campaign state — every agent reads from and writes to one `CampaignState` object that persists to disk after each step.

### How owner research works

For every kept lead, we run two phases in order, with an early-exit when Phase 1 fully resolves the lead:

**Phase 1 — crawl the company's own website.** We have the website URL from Places. The crawler fetches the homepage, finds links to About / Team / Meet / Owner / Founder / Contact pages on the same domain, fetches up to 5 of them, extracts clean text AND email addresses (from `mailto:` links and inline text). Then Claude reads the pages with the SOP rules to find the owner's name and — if a candidate email on the company's own domain is bound to the owner (e.g., "Mike Smith — mike@acmebath.com" or `mailto:mike@acmebath.com` next to his bio) — captures that email too. Generic info@/sales@/contact@ addresses are explicitly rejected as not being the owner's direct email.

When Phase 1 returns both name AND email, that lead is fully resolved — FindyMail won't waste a credit on it because their bulk upload deduplicates against domains they've already processed for you.

**Phase 2 — BBB and Google search.** Only runs when Phase 1 returns no confident name. Claude uses `web_search` to look up the BBB listing first, then falls back to Google + the company's About page. Phase 2 only produces a name (BBB doesn't list emails) — those leads still need FindyMail to find their email.

Combined Phase 1 + Phase 2 hit rate is typically 70–80%. The `master.csv` records both the source phase (`website` vs `bbb_search`) and any email captured in Phase 1.

## Limits and known things

- **Owner-name hit rate is ~70–80% combined** (website crawl + BBB fallback). Sites that are JS-only (Wix-rendered pages without a static fallback, single-page React apps) won't yield text the crawler can read — those leads fall through to the BBB phase. Leads where neither phase finds an owner are excluded from the FindyMail CSV but appear in the master CSV for any manual fallback work.
- **The crawler respects basic civility** — single requests, real User-Agent, 8-second timeout, max 5 pages per site, same-domain only.
- **Area-code filtering uses Claude's general knowledge.** For unfamiliar metros the first run may need a sanity check on rejected leads.
- **Google Places caps Text Search at ~60 results per query.** The sourcer issues 5 keyword variants per niche to widen the catch — that's why `KEYWORDS_BY_NICHE` in `agents/sourcer.py` exists. Add more keywords if a niche is producing thin results.
- **Places API requires billing enabled even for free-tier use.** No way around it; that's Google's policy.

## Cost per city

| Service | Per city |
|---|---|
| Google Places API | $0 (free tier) — or ~$0.10 paid |
| Anthropic API (filter + owner research) | ~$0.30–$0.80 |
| **Total** | **under $1** |
