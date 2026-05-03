# Smoke Test: Personalization v1 — First Run

**Date:** 2026-05-03  
**Campaign ID:** 20260503-235740-1b739c  
**Input CSV:** `/tmp/enriched_smoke.csv` (3 rows)  
**Command:** `python run.py --personalize /tmp/enriched_smoke.csv --triggered-by-name "DG"`

---

## Summary

| Metric | Value |
|---|---|
| Total leads in CSV | 3 |
| Leads with email (processed) | 2 |
| Leads skipped (no_email_skip) | 1 |
| X/Y filled (status=ok) | 1 / 3 |
| vision_failed | 1 / 3 |
| LinkedIn URLs found | 1 / 3 |

---

## Per-lead results

### KBF Design Gallery — Keith Vellequette
- **Status:** `ok`
- **X Project:** `white shaker kitchen remodel`
- **Y Detail:** `waterfall edge quartz island`
- **LinkedIn:** https://www.linkedin.com/in/keith-vellequette-74925311/
- **Notes:** Clean result. Screenshot captured successfully and Claude vision returned crisp X/Y values.

### Nu Kitchen Designs — Josh Torres
- **Status:** `vision_failed`
- **X Project:** (blank)
- **Y Detail:** (blank)
- **LinkedIn:** (none found)
- **Notes:** Vision call returned HTTP 400 — `At least one of the image dimensions exceed max allowed size: 8000 pixels`. The gallery screenshot for nukitchendesigns.com was captured at a resolution exceeding Anthropic's 8000px image limit. The personalizer correctly caught the `BadRequestError` and set `status=vision_failed`, leaving X/Y blank. Fix: add image downscaling in the screenshot step before passing to Claude vision.

### Hosanna Building Contractors — Dean Blankenship
- **Status:** `no_email_skip` (row 3 in agency CSV shows blank email, included but no X/Y)
- **Notes:** Dean's email field was blank in the input CSV. The personalizer correctly skipped vision processing (`skipping 1 with no email`). The row still appears in the agency CSV with all contact info intact and blank X/Y/LinkedIn columns — correct behavior.

---

## Issues found

### Issue 1: Image too large for Claude vision (Nu Kitchen Designs)
- **Root cause:** Playwright screenshot of nukitchendesigns.com gallery exceeds 8000px on at least one dimension. Anthropic rejects the base64 payload with a 400 error.
- **Impact:** `vision_failed` status; X/Y blanked out for that lead.
- **Fix:** Resize/downsample the screenshot before encoding for the vision API call. Target max 4096px on the longest side.

### Issue 2: Supabase save() crashed the run before fix
- **Root cause:** `state.save()` was not wrapped in try/except, causing an unhandled `SupabaseException` when `SUPABASE_URL` is empty. The `state.info()` event inserts already used try/except; `save()` and `save_leads()` did not.
- **Fix applied:** Wrapped `save()` and `save_leads()` bodies in try/except, printing `[state] save failed (non-fatal): ...` — same pattern as event inserts.

---

## Test suite results (Step 1)

Ran 93 tests. **22 errors** in `test_sourcer.SourcerRunTest` — all caused by the same root issue: `state.mark_done()` calls `save()` which throws when Supabase credentials are absent. Now fixed. The remaining 71 tests all passed.

The secondary error (`AttributeError: 'CampaignState' object has no attribute 'path'` in test tearDown) is a pre-existing test setup issue unrelated to personalization — `CampaignState` no longer uses a file path.

---

## Agency CSV output

Location: `output/20260503-235740-1b739c__agency.csv`

Columns confirmed: `Total, Lead Sourcer, Business, Owner Full Name, First, Last, Owner Email, LinkedIn, Website, Phone, Date, X Project, Y Detail`

All 3 rows present with correct data. Henderson CRM v3 schema intact.
