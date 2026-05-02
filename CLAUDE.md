# Vistaline Lead-Gen Sourcer — Project Instructions

## What this is

A Python pipeline that sources remodeling-contractor leads for a single city and produces a FindyMail-ready CSV. Three sub-agents and an orchestrator. Stops at the FindyMail upload — does not handle email enrichment, personalization, thumbnails, or campaign launch.

## How it runs

```bash
python run.py --city "Orlando" --state FL --count 50
python run.py --resume <campaign-id>     # after a crash
```

## Architecture rules — do not violate

- **The orchestrator (`run.py`) is deterministic Python, not an LLM-decision-loop.** The pipeline is well-defined; do not introduce agentic planning at the orchestrator level.
- **Each sub-agent has one job and writes back to the shared `CampaignState`.** Don't chain agents directly. Don't have one agent reach into another.
- **State persists to disk after every step** via `state.mark_done(step_name)`. Every agent must check `state.is_done(...)` at the top and return early — this is what makes resume work. Do not break this.
- **`tools.py` only holds external API clients.** No business logic. No LLM calls.
- **LLM calls live inside agents.** No exceptions.
- **Agents never share LLM clients across threads.** Each parallel worker constructs its own `Anthropic()` client — the SDK is not safe to share across `ThreadPoolExecutor` workers.

## Coding conventions

- Type hints on every function signature.
- Docstrings on every module and every public function.
- No comments that just restate the code. Comments explain *why*, not *what*.
- Use `dataclass` for structured data, never raw dicts for things that have a known schema.
- File paths use `pathlib.Path`, never raw strings.
- HTTP requests always have `timeout=`. Never an unbounded request.
- Errors that come from external APIs are caught and logged; errors that come from our own bugs are allowed to crash so we see them.

## Cost discipline

- **Never add a paid API call without a prompt to me first.** This includes Anthropic API calls in new places, FindyMail-style enrichment services, paid scrapers.
- The current paid surfaces are: Anthropic API (Claude calls in `lead_filter`, `owner_researcher`), Google Places API (in `sourcer`). Adding a third needs my approval.
- When adding parallelism, default to `MAX_PARALLEL = 8` unless there's a specific reason to go higher. Higher concurrency = higher rate-limit risk.

## What's already built

- `agents/sourcer.py` — Google Places API Text Search, multiple keyword variants per niche
- `agents/lead_filter.py` — Claude with the SOP filter rules, batches of 25
- `agents/owner_researcher.py` — two-phase: website crawl (free) then BBB+Google fallback (web_search). Phase 1 captures both name and owner email when visible
- `agents/website_crawler.py` — pure HTTP+BeautifulSoup, no LLM
- `agents/csv_assembler.py` — FindyMail upload CSV (4 cols) + master CSV (everything)
- `state.py`, `tools.py`, `config.py`, `run.py`

## What's deliberately NOT built (don't add without asking)

- Snov.io / Apollo / Hunter integrations — evaluated and declined for the SMB-contractor segment
- FindyMail API integration — workflow is to upload the CSV manually
- Personalization (xProject, yDetail) — out of scope for this pipeline
- Clipio thumbnail generation — out of scope
- Instantly campaign creation/launch — out of scope
- Notion market manager — user enters city via CLI

## Testing approach

- For pure-Python helpers (URL normalization, area-code extraction, email regex, JSON parsing): write tests as standalone scripts in `tests/`. No pytest framework — keep dependencies minimal.
- For agents that hit external APIs: don't mock. Test against a real run with `--count 5` on a small city, inspect the master CSV.
- After any change to `agents/*.py`, run a smoke test: `python -c "from agents import sourcer, lead_filter, owner_researcher, csv_assembler; print('OK')"` to catch import errors.

## What good "next features" look like

When I ask for a new feature, default to:
1. Read the relevant existing file first.
2. Propose where the change goes (which file, which function) before writing code.
3. Keep changes small. One agent at a time.
4. Add a test for the new logic if it's pure Python.
5. Run the smoke import test before finishing.

## Things I'll probably ask for

- "Tighten the website crawler" — likely add Playwright fallback for JS-only sites, or more keyword variations
- "Add Phase 3 Snov.io fallback" — only if I explicitly ask; declined for now
- "Add caching for owner research across runs" — SQLite keyed on (business_name, city)
- "Switch model" — change `claude-sonnet-4-20250514` to a newer model in the agent files
- "Add Notion logging" — write a campaign summary back to a Notion page after a successful run

## Anti-patterns I've already rejected

- Agentic orchestrator (LLM deciding what to do next at the run.py level) — overkill for a deterministic pipeline
- Direct browser scraping of Google Maps via Playwright — breaks too often, Places API is cheaper and more reliable
- OpenClaw or similar agent frameworks — adds abstraction without adding value for this scope
- Mocking external APIs in tests — too brittle, tests against real APIs at small `--count`
