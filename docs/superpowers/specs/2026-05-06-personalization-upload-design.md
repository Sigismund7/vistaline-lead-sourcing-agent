# Personalization Upload — Design Spec

**Date:** 2026-05-06
**Author:** Daschel + Claude (brainstorming pair)
**Status:** Approved, not yet implemented

---

## Problem

After a campaign completes, the operator downloads the FindyMail CSV, uploads it to FindyMail to get emails added, then manually handles personalization. There is no way to feed the enriched CSV back into the system — personalization (X Project, Y Detail, LinkedIn) has to be done by hand.

## Goal

Add an upload button to the campaign results page. The operator uploads the FindyMail-returned CSV (which now contains emails). The system matches rows back to the campaign's existing leads by domain, writes emails onto them, runs the personalizer and LinkedIn finder, and makes a final agency-format CSV available for download from the same campaign page.

## Non-goals (v1)

- A new nav item or dedicated personalization page
- Re-running personalization on leads that already have x_project/y_detail
- Bulk upload across multiple campaigns at once
- Showing personalization progress as a live stream (status polling is enough)
- Any changes to the sourcing or filtering pipeline

## Workflow

```
Campaign results page
  → operator clicks "Upload enriched CSV"
  → selects the FindyMail-returned CSV from their machine
  → POST /campaigns/{id}/enrich   (multipart form-data)
      ├── parse CSV rows
      ├── match each row to a campaign lead by domain (strip www., lowercase)
      ├── write email onto matched leads in Supabase
      └── start background thread: personalizer.run() → linkedin_finder.run()
  ← 202 Accepted immediately
  → campaign status flips to "personalizing"
  → frontend polls campaign status (same polling it already does)
  → when status returns to "completed":
      "Download Agency CSV" button appears
  → GET /campaigns/{id}/leads/agency.csv
      └── streams 13-col agency CSV (already implemented in csv_agency.write_agency)
```

## Matching logic

Primary key: `domain` — strip `www.`, lowercase both sides, compare exactly.

- FindyMail returns the same domain we gave them, so no fuzzy matching is needed.
- Enriched CSV rows with no matching campaign lead: skipped, counted in a log entry.
- Campaign leads with no matching enriched row: email stays blank, personalizer skips them (existing `no_email_skip` behaviour).

## What's already built

- `agents/personalizer.py` — vision-based X Project / Y Detail extraction, parallel, idempotent
- `agents/linkedin_finder.py` — LinkedIn URL lookup via web_search, idempotent
- `agents/csv_agency.py` — `write_agency()` generates the 13-column Instantly-ready CSV
- `run.py --personalize` — CLI end-to-end runner (not used by the API path but confirms the pipeline works)

## New backend code

### `POST /campaigns/{campaign_id}/enrich`

In `api/main.py`. Accepts `multipart/form-data` with a single `file` field (CSV).

Steps:
1. Load campaign leads from Supabase (`db.table("leads").select("*").eq("campaign_id", id)`).
2. Parse the uploaded CSV with `csv.DictReader`. Match rows to leads by domain.
3. For each matched lead: set `lead["email"]` to the value from the CSV. Upsert the updated lead rows to Supabase.
4. Set campaign `status = "personalizing"` and save.
5. Start a `threading.Thread` targeting `_run_personalization(campaign_id)`.
6. Return `{"ok": True, "matched": N, "unmatched": M}` with status 202.

`_run_personalization(campaign_id)`:
- Loads `CampaignState` from Supabase.
- Resets the `personalizer` and `linkedin_finder` completed-steps flags so they re-run.
- Calls `personalizer.run(state, ...)` then `linkedin_finder.run(state, ...)`.
- Calls `state.save_leads()` then sets `state.status = "completed"` and saves.

### `GET /campaigns/{campaign_id}/leads/agency.csv`

In `api/main.py`. Loads leads from Supabase, builds a `CampaignState`, calls `write_agency()`, streams the result as `text/csv` with `Content-Disposition: attachment`.

## New frontend code

### Campaign results page (`frontend/app/campaigns/[id]/results/page.tsx`)

Two new UI elements, added alongside the existing FindyMail CSV and Master CSV download buttons:

**"Upload enriched CSV" button**
- Renders a hidden `<input type="file" accept=".csv">`.
- On file selection: POST to `/api/proxy/campaigns/{id}/enrich` as `multipart/form-data`.
- While uploading: button shows "Uploading…" and is disabled.
- On 202: show a status message "Personalization running — this takes a few minutes."
- Start polling campaign status every 10 seconds (same pattern as the existing live run view).

**"Download Agency CSV" button**
- Visible only when `campaign.status === "completed"` AND at least one lead has `personalization_status === "ok"`.
- Links to `GET /api/proxy/campaigns/{id}/leads/agency.csv`.

## Schema changes

None. All personalization fields (`x_project`, `y_detail`, `y_source`, `linkedin_url`, `linkedin_source`, `personalization_status`, `email`) already exist on the `leads` table.

The `campaigns` table already has a `status` column. The new value `"personalizing"` does not require a migration — the column is `TEXT` with no constraint.

## Error handling

- CSV parse error (not a valid CSV, wrong encoding): return `422 Unprocessable Entity` with a message the frontend displays inline.
- Zero rows matched: return `422` — operator likely uploaded the wrong file.
- Personalizer crash mid-run: caught by the background thread, sets `status = "failed"`, frontend shows the existing "failed" campaign state.

## Acceptance criteria

1. Operator uploads a FindyMail-returned CSV on the results page. The backend matches leads by domain, writes emails, and starts personalization. The response is immediate (202).
2. While personalizing, the campaign shows status "personalizing". When done, status returns to "completed".
3. "Download Agency CSV" button appears after personalization completes and produces a valid 13-column CSV with X Project and Y Detail filled for leads that had a gallery to screenshot.
4. Leads with no matching row in the enriched CSV (no email found by FindyMail) are skipped gracefully — they appear in the master CSV with blank email and personalization_status = "no_email_skip".
5. Uploading a wrong or empty CSV returns a clear error message inline, not a 500.
6. Re-uploading a new enriched CSV on an already-personalized campaign re-runs personalization on any leads with a new email (idempotency: leads that already have x_project set are skipped by the personalizer).
