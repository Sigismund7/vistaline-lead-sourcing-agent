# Lead Stage Tracking — Design Spec

**Date:** 2026-05-04
**Author:** Daschel + Claude (brainstorming pair)
**Status:** Approved, not yet implemented

---

## Problem

Once a campaign finishes, the only signal we have is "completed" — meaning the CSV was generated. We don't know whether the operator actually downloaded the FindyMail CSV, uploaded it, or whether the leads have moved through Instantly. If a campaign produces 21 leads and the operator forgets to upload them, those leads sit forever invisible. Multiply across ten cities and a chunk of work silently never reaches a human.

## Goal

A lifecycle stage on every kept lead, advanced manually for now, designed so an Instantly webhook can later promote leads automatically without schema change. Operators can glance at the campaigns list and see what work is unfinished.

## Non-goals (v1)

- Instantly API integration — the schema must support it, but no webhook code in v1
- Per-lead reply / bounce / open tracking
- Bulk multi-campaign workflows
- Drip-sequence stage history (we only store the *current* stage)
- Email enrichment status (FindyMail's job, not ours)

## Stage values

A single column `lead_stage` on the `leads` table. Allowed values, ordered:

| # | Stage | How it advances | Set by |
|---|---|---|---|
| 0 | `researched` | Default after `owner_researcher` completes for the lead | Pipeline |
| 1 | `exported` | Operator clicks "Download FindyMail CSV" on the campaign results page | Frontend |
| 2 | `processed` | Operator clicks "Mark as uploaded" after pasting the CSV into FindyMail | Frontend |
| 3 | `in_sequence` | (future) Instantly webhook fires when lead is added to a campaign sequence | Instantly |
| 4 | `replied` / `bounced` / `unsubscribed` | (future) Instantly webhook | Instantly |

Stages 3+ are reserved for the Instantly integration. They are valid values but never written by v1 code.

## Data model

```sql
ALTER TABLE leads ADD COLUMN lead_stage TEXT NOT NULL DEFAULT 'researched';
ALTER TABLE leads ADD COLUMN stage_updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW();
```

That's it — no separate stage history table in v1. When Instantly integration ships, we'll add `lead_stage_history` for audit. For now, current state plus timestamp is enough.

A new index helps the campaigns-list "% processed" query stay fast:

```sql
CREATE INDEX leads_stage_by_campaign ON leads (campaign_id, lead_stage);
```

## State transition rules

- Stages are an **ordered ladder** — a lead can only advance to a higher stage, never go back.
- Bulk transitions are allowed: "Mark all kept leads in this campaign as processed" sets every lead at stage `< processed` to `processed`.
- A lead with no `owner_full_name` and `kept = false` is **not** in the ladder — its `lead_stage` stays `'researched'` but it's filtered out of the UI counters.

## UI changes

### Campaigns list page (`/campaigns`)

Each campaign card adds a third stat next to "kept leads":

```
21 kept · 21 researched · 0 exported · 0 processed
```

A subtle warning chip ("Unprocessed") appears on any completed campaign whose `processed` count is below `kept`. Clicking the chip jumps to the results page.

### Campaign results page (`/campaigns/[id]/results`)

Two existing buttons — "Master CSV" and "FindyMail CSV" — get a side-effect: clicking the FindyMail download button also PATCHes every selected lead's stage to `exported`. The Master CSV button does *not* advance stage (it's just an audit dump).

A new primary button: **"Mark all as uploaded to FindyMail"** — sits next to the download buttons. Clicking it advances every kept lead from any stage `< processed` to `processed`. Confirmation modal: "Confirm you've uploaded the FindyMail CSV. This advances all 21 leads to processed."

A new column in the leads table: **Stage**, showing the current stage as a small chip (`researched`, `exported`, `processed`). Per-row override available via a dropdown — useful when only some leads were uploaded (operator manually moved a few, then realized they wanted to skip the rest).

### Optional v1.5: per-lead checkbox advance

If the operator needs to mark only a subset, the existing row checkboxes (currently used to filter the FindyMail export) can also drive a "Mark selected as processed" action. Reuse the same UI control — no new selection model.

## API changes

Two new endpoints on the FastAPI backend:

```
PATCH /campaigns/{id}/leads/{lead_id}/stage
  body: { stage: "exported" | "processed" }
  rules: rejects downgrades, rejects unknown stages

PATCH /campaigns/{id}/leads/stage  (bulk)
  body: { lead_ids: ["..."] | "all_kept", stage: "exported" | "processed" }
  returns: { updated: <count> }
```

Both endpoints update `stage_updated_at` to `NOW()` and emit a single SQL UPDATE — no per-lead loop.

## Backend / pipeline changes

`agents/owner_researcher.py` does not need to set `lead_stage` explicitly — the DB default `'researched'` covers it. The CSV download endpoints in `frontend/app/api/proxy/[...path]/route.ts` need a small post-fetch hook: after successfully streaming the FindyMail CSV, fire the bulk PATCH to mark all included leads as `exported`.

## Why this design

1. **Single column, no history table** — keeps schema small. Every common query is "what stage is this lead in *right now*", not "show audit trail". The day we need history, we add a table; we don't pre-build it.
2. **Ordered ladder, no skipping** — prevents impossible states like `replied` before `processed`. Validation at API boundary, enforced by a CHECK constraint:
   ```sql
   CHECK (lead_stage IN ('researched','exported','processed','in_sequence','replied','bounced','unsubscribed'))
   ```
3. **Future Instantly stages reserved upfront** — adding `in_sequence` etc. now means no DB migration when Instantly ships. The webhook handler will be the only new code.
4. **Stage transitions are idempotent** — clicking "Mark as processed" twice is safe; it's an `UPDATE WHERE lead_stage < 'processed'` so the second click affects zero rows.
5. **No new toggles, no new forms** — the new-campaign form is unchanged. This is a post-pipeline read/update feature.

## Out of scope, but worth flagging

- **Per-campaign vs per-lead view of stage progress.** v1 shows aggregate counts on the campaigns list and per-row chips on the results page. We're not building a kanban-style "all leads across all campaigns at stage X" view. If that becomes useful, it's a single new query.
- **Stage filtering in the leads table.** We're not adding a "show only `exported`" filter to the results table in v1. Add later if you find yourself eyeballing 50-row tables looking for one chip.
- **Bulk reverse migrations** — there is no "reset all to researched" admin button. If you screw up a stage assignment, fix it via the per-row dropdown or a SQL one-liner. Keeping a destructive admin action out of the UI by design.

## Acceptance criteria

1. A new completed campaign starts with `kept_leads` leads all at stage `researched` (DB default).
2. Clicking "Download FindyMail CSV" on `/campaigns/[id]/results` causes the included leads to flip to `exported` within one round-trip; the chip updates without a page refresh.
3. Clicking "Mark all as uploaded to FindyMail" prompts for confirmation, then advances all kept leads from `< processed` to `processed`. The campaigns list "Unprocessed" chip disappears.
4. A per-row dropdown on the results table lets operators advance/override a single lead's stage. The dropdown only offers stages `>=` the current one (no downgrades).
5. Re-clicking "Mark as processed" is a no-op (idempotent).
6. Existing campaigns (rows in `leads` predating the migration) get `lead_stage = 'researched'` from the column default — no manual backfill required.

## Implementation notes for whoever picks this up

- The DB migration goes in `supabase/migrations/004_lead_stages.sql` (next number after 003 from owner-researcher v2).
- The CHECK constraint should be added in the same migration as the column itself.
- The two PATCH endpoints belong in `api/main.py` next to the existing campaign routes.
- Frontend changes touch three files only: `frontend/app/campaigns/page.tsx` (list view counters), `frontend/app/campaigns/[id]/results/page.tsx` (per-row stage column + bulk button), and one new component for the stage chip dropdown.
- Tests: a unit test for the no-downgrade rule in the API; a smoke test that downloading the FindyMail CSV side-effects the stage flip. No integration test for the Instantly stages — they're not wired up.
