-- 2026-05-03 — personalization columns for X Project / Y Detail / LinkedIn.
-- Adds the post-FindyMail enrichment fields. All default to empty string so
-- existing rows continue to load via state.CampaignState.load.
ALTER TABLE leads
  ADD COLUMN IF NOT EXISTS x_project TEXT DEFAULT '',
  ADD COLUMN IF NOT EXISTS y_detail TEXT DEFAULT '',
  ADD COLUMN IF NOT EXISTS y_source TEXT DEFAULT '',
  ADD COLUMN IF NOT EXISTS linkedin_url TEXT DEFAULT '',
  ADD COLUMN IF NOT EXISTS linkedin_source TEXT DEFAULT '',
  ADD COLUMN IF NOT EXISTS personalization_status TEXT DEFAULT '';
