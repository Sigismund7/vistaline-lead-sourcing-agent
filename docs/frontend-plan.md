# Vistaline Lead-Gen Sourcer — Frontend & Hosted Architecture Plan

Living document. Source of truth for the hosted UI built on top of the existing Python pipeline. Append-only — record decisions with date and rationale.

Created: 2026-05-02 by Daschel + Claude.

---

## 1. Vision

A hosted, branded internal tool where Vistaline teammates can run the lead-sourcing pipeline against any U.S. city, watch each agent's work step-by-step in real time, preview and trim the result list, then export a FindyMail-ready CSV. Replaces the current CLI flow (`python run.py --city ...`) with a polished web UI without throwing away any of the existing Python pipeline.

The tool feels like an extension of vistalinedigital.com — same wordmark, same blue, same confident voice.

---

## 2. Brand reference (extracted from vistalinedigital.com 2026-05-02)

- **Wordmark:** "VistalineDigital" — "Vistaline" in electric blue, "Digital" in dark/white depending on background. Heavy geometric sans-serif.
- **Primary blue (provisional):** `#2563EB` (Tailwind `blue-600`) — *operator to confirm exact hex.*
- **Type (provisional):** heavy display sans for headlines (likely **Geist**, the v0 default since the site was built with v0). Regular sans for body. *Operator to confirm.*
- **Aesthetic:** photography-driven hero (luxury home interiors), bold blue accent words inside white headlines, solid blue CTAs with white labels and arrow icons, ~8px button radius.
- **Voice:** confident, action-led — *"Build Faster. Scale Smarter. Automate Everything."* / *"Scale Your Residential Contracting Business Profitably."*
- **Built with v0:** site uses Vercel's v0 + shadcn/ui. Internal tool should match that aesthetic so brand transfer is automatic and zero rework.

---

## 3. Architecture

The orchestrator (`run.py`) is deterministic Python today. We don't change that — we wrap it. The FastAPI HTTP layer sits on top of the existing agents; agents stay agents; `state.py` swaps its JSON-on-disk backend for Postgres rows but keeps its interface (`save`, `load`, `mark_done`, `is_done`). CLAUDE.md's architecture rules remain intact.

```
┌─────────────────────────────────────────────────────────────┐
│  Browser (teammates)                                        │
└──────────────────────────────┬──────────────────────────────┘
                               │ HTTPS
              ┌────────────────▼────────────────┐
              │  Vercel — Next.js 15 + shadcn   │
              │  /login                         │
              │  /campaigns (list + history)    │
              │  /campaigns/new (config form)   │
              │  /campaigns/:id (live run view) │
              │  /campaigns/:id/results (table) │
              └────────────────┬────────────────┘
                               │ REST + SSE
        ┌──────────────────────▼──────────────────────┐
        │  Railway — FastAPI (Python 3.11)            │
        │  POST /api/campaigns      (new run)         │
        │  GET  /api/campaigns/:id/events  (SSE)      │
        │  GET  /api/campaigns/:id/leads              │
        │  POST /api/campaigns/:id/leads/:id/exclude  │
        │  GET  /api/campaigns/:id/csv                │
        │  ─────────────────────────                  │
        │  Wraps existing run.py orchestrator.        │
        │  Pipeline runs as asyncio task, publishes   │
        │  events via Redis pub/sub for SSE fan-out.  │
        └──────────────────────┬──────────────────────┘
                               │
        ┌──────────────────────▼──────────────────────┐
        │  Postgres + Redis (Railway)                 │
        │  users · campaigns · leads · events · niches│
        └──────────────────────┬──────────────────────┘
                               │
        ┌──────────────────────▼──────────────────────┐
        │  External APIs (called by agents/* code)    │
        │  Azure Maps · Yelp Fusion · Brave · Anthropic│
        └──────────────────────────────────────────────┘
```

### Backend migration (incremental — does NOT block Phase 0)

| Today | After |
|---|---|
| `state.py` writes JSON to `state/<id>.json` | Same `CampaignState` class; `save`/`load`/`mark_done` write to Postgres rows |
| `Lead.place_id` is Google-specific | Renamed `source_id` + `source` (`azure` / `yelp` / `google`) — already flagged in obs 306 |
| `agents/*.run(state, key)` calls `state.info()` and prints to stdout | Same — but `state.info()` also inserts an `events` row + publishes Redis pub/sub message |
| `run.py` is the entrypoint | `run.py` still works for CLI debugging; FastAPI route invokes the same orchestrator function |
| Resume via `--resume <id>` | Same logic; UI surfaces a "Resume" button on crashed campaigns |

The CLAUDE.md invariant ("state persists after every step; every agent checks `is_done()` and returns early") is preserved without modification. The orchestrator stays deterministic Python — no LLM-decision-loop at the run.py level.

---

## 4. Tech stack (locked)

- **Frontend host:** Vercel
- **Frontend stack:** Next.js 15 (App Router) + Tailwind + shadcn/ui + Radix + Geist font
- **Backend host:** Railway (Python 3.11, FastAPI, Postgres, Redis)
- **Backend framework:** FastAPI + `sse-starlette` for live events + `asyncio.create_task` for pipeline runs (promote to Celery / Dramatiq later if concurrency demands it)
- **DB:** Postgres on Railway (or Supabase if we choose Supabase Auth)
- **Pub/sub for live events:** Redis on Railway — fans out one writer (the running pipeline) to N SSE clients per campaign
- **Auth:** Clerk (free ≤10k MAU, Google SSO, drop-in for Next.js)
- **CSV export:** generated on demand from DB rows; downloaded directly from frontend

---

## 5. UX patterns (locked from research)

- **Run view layout:** left rail = step list with status pills (queued / running / done / failed / skipped) + duration; right pane = streaming event cards. Auto-collapse done steps; auto-expand failed.
- **Event tone:** terse system messages — `Sourced 47 leads from Yelp Fusion · 3.2s` — never first-person agent narrative.
- **Niche selector:** searchable combobox; presets at top, "Custom..." at bottom. Selecting a preset pre-fills an editable keyword-variants field. Reject locked catalogs.
- **Result review:** Clay-style table preview before export. Checkboxes to exclude rows. Downloaded CSV reflects only kept rows. Per-row `reject_reason` visible.
- **Cost visibility:** running estimate during the run (Anthropic + API spend), total displayed on result screen, per-user month-to-date shown in nav.
- **Aesthetic:** Linear/Vercel/Resend density — monochrome neutrals + one electric-blue accent. Motion ≤150ms ease-out on state changes only. No decorative gradients, no bouncy progress bars.

---

## 6. Niche catalog (v1 pre-seed)

Stored in DB table `niches`. Each row: `slug`, `display_name`, `default_keyword`, `keyword_variants` (array). Presets shown at top of the niche combobox; users can pick "Custom..." to define their own (saved per-user).

Pre-seed list (operator confirmed 2026-05-02):

1. Kitchen remodelers
2. Bathroom remodelers
3. Roofing
4. HVAC
5. Deck builders
6. Pool builders
7. ADU / granny flat builders
8. Garage conversions
9. Whole-home remodels
10. Painters
11. Flooring
12. Landscapers

Keyword variants for each are TBD — derived from current `agents/sourcer.py` keyword expansion logic and operator review.

---

## 7. Lead schema (frontend-visible)

Same as today's `Lead` dataclass, plus:

- `source_id` + `source` (replacing Google-specific `place_id`)
- `excluded_at`, `excluded_by` (for row-exclude in preview)
- `created_at`, `updated_at`

Migration covered in §3.

---

## 8. Sequencing

| Phase | Scope | Branch | Status |
|---|---|---|---|
| Phase 0 | Two-layer sourcing (Azure Maps + Yelp Fusion + Brave) — backend-only, CLI-driven | `phase0-*-stack` | In progress (Yelp cycle now) |
| Phase 1 — frontend skeleton | Next.js + shadcn scaffold on Vercel + auth + niche catalog UI + new-campaign form (mocked API) | `phase1-frontend-skeleton` | Not started |
| Phase 2 — FastAPI wrap | FastAPI service on Railway wrapping existing `run.py`; Postgres/Redis; SSE events; campaign list endpoint | `phase2-api-layer` | Not started |
| Phase 3 — live run view | Step rail + event stream UI; resume button; cancel mid-run | `phase3-live-run` | Not started |
| Phase 4 — preview & export | Result table with row-exclude; CSV download endpoint; cost panel | `phase4-preview-export` | Not started |
| Phase 5 — polish & deploy | Brand pass, error states, empty states, responsive review, production deploy | `phase5-polish` | Not started |

Phase 0 must complete before Phase 2 (the engine has to work CLI-first). Phase 1 can run in parallel with the tail of Phase 0 since it's UI-only with mocked API.

---

## 9. Decisions log

| Date | Decision | Rationale |
|---|---|---|
| 2026-05-02 | Hosted multi-user web UI with live agent step view | Operator brief — teammates need to run campaigns without the CLI |
| 2026-05-02 | Vercel for frontend; Railway (provisional) for Python backend | Operator confirmed Vercel; brand site is on v0/Vercel; Python pipeline cannot run in serverless functions due to multi-minute runtime |
| 2026-05-02 | FastAPI + SSE (not WebSockets, not Inngest, not Vercel AI SDK) | One-way events; SSE auto-reconnects; simplest fit for known-shape pipeline |
| 2026-05-02 | Next.js + shadcn/ui + Geist | Brand site is built on v0 (same stack); zero brand-transfer rework |
| 2026-05-02 | Pre-seed 12-niche catalog; allow custom entry below presets | Operator chose preset + custom hybrid |
| 2026-05-02 | Cost visibility per-run and month-to-date | Operator approved; protects against runaway API spend |
| 2026-05-02 | Pre-export row-exclude review screen (Clay-style) | Operator approved |
| 2026-05-02 | Living plan doc at `docs/frontend-plan.md`, append-only | Operator requested |
| 2026-05-02 | Run-view event tone: terse system messages, not agent narrative | Pipeline is deterministic — first-person voice is wrong shape |
| 2026-05-02 | Auth: **Clerk** | Operator pick — drop-in, free tier, Google SSO, future-proof |
| 2026-05-02 | API keys: **shared agency keys server-side**, per-user cost caps enforced | Operator pick — Vistaline pays the bill, simpler UX, no BYOK friction |
| 2026-05-02 | Concurrent campaigns enabled day 1 | Operator pick — teammates can run different cities simultaneously |
| 2026-05-02 | Cost caps: **soft warning at $10/run, hard abort at $25/run, both configurable** | Operator pick — soft warning is minimal interrupt; hard abort protects against runaway spend |
| 2026-05-02 | Backend host: **Railway** (locked, not Vercel) | Vercel functions cap at 15 min and don't fit long-running stateful Python pipelines with SSE; Railway Hobby ~$5/month is the cheapest viable option |
| 2026-05-02 | Headline font: **Geist** (v0 default) confirmed | Operator confirmed — site uses v0, internal tool inherits same font |
| 2026-05-02 | Single-tenant data model — internal Vistaline team only, forever | Operator confirmed — no org/tenant boundaries needed; saves schema complexity |
| 2026-05-02 | Visual polish: production-quality internal-tool aesthetic (Linear/Vercel/Resend density) | Operator: "internal tool forever, but might as well make it look decent" |

---

## 10. Open questions (remaining — non-blocking for Phase 1)

1. **Exact primary-blue hex.** Provisional `#2563EB` (Tailwind `blue-600`). Will verify against the site when the first screen renders in Phase 1; trivial to swap. Operator can drop a precise hex into this section anytime.
2. **Logo file.** Operator to drop SVG and/or PNG at `docs/brand/logo.svg` (and `logo-mark.svg` if separate symbol exists). Until then, the header renders the wordmark as text using Geist heavy + the primary blue.
3. **Production domain.** Defaulting to `app.vistalinedigital.com` (SaaS convention). Vercel domain can be reconfigured anytime; only affects Clerk allowed-origin list.
