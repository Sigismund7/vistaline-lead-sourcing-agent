-- campaigns
CREATE TABLE campaigns (
  id             TEXT        PRIMARY KEY,
  city           TEXT        NOT NULL,
  state_abbr     TEXT        NOT NULL,
  niche          TEXT        NOT NULL,
  target_count   INTEGER     NOT NULL DEFAULT 50,
  triggered_by   TEXT        NOT NULL DEFAULT 'DG',
  status         TEXT        NOT NULL DEFAULT 'queued',  -- queued | running | completed | failed
  total_leads    INTEGER     NOT NULL DEFAULT 0,
  kept_leads     INTEGER     NOT NULL DEFAULT 0,
  with_owner     INTEGER     NOT NULL DEFAULT 0,
  with_email     INTEGER     NOT NULL DEFAULT 0,
  spend_usd      NUMERIC(8,4) NOT NULL DEFAULT 0,
  completed_steps TEXT[]     NOT NULL DEFAULT '{}',
  created_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  completed_at   TIMESTAMPTZ,
  error_message  TEXT
);

-- leads (populated after owner_researcher completes)
CREATE TABLE leads (
  id              UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
  campaign_id     TEXT        NOT NULL REFERENCES campaigns(id) ON DELETE CASCADE,
  business_name   TEXT        NOT NULL DEFAULT '',
  phone           TEXT        NOT NULL DEFAULT '',
  website         TEXT        NOT NULL DEFAULT '',
  address         TEXT        NOT NULL DEFAULT '',
  area_code       TEXT        NOT NULL DEFAULT '',
  domain          TEXT        NOT NULL DEFAULT '',
  place_id        TEXT        NOT NULL DEFAULT '',
  kept            BOOLEAN     NOT NULL DEFAULT TRUE,
  reject_reason   TEXT        NOT NULL DEFAULT '',
  owner_full_name TEXT        NOT NULL DEFAULT '',
  owner_first     TEXT        NOT NULL DEFAULT '',
  owner_last      TEXT        NOT NULL DEFAULT '',
  owner_source    TEXT        NOT NULL DEFAULT '',
  email           TEXT        NOT NULL DEFAULT '',
  excluded_by_user BOOLEAN    NOT NULL DEFAULT FALSE
);

-- events (pipeline log entries, streamed live via Realtime)
CREATE TABLE events (
  id          UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
  campaign_id TEXT        NOT NULL REFERENCES campaigns(id) ON DELETE CASCADE,
  step        TEXT        NOT NULL,
  level       TEXT        NOT NULL DEFAULT 'info',  -- info | warn | error | success
  message     TEXT        NOT NULL,
  detail      TEXT,
  duration_ms INTEGER,
  ts          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Indexes for common queries
CREATE INDEX leads_campaign_id ON leads (campaign_id);
CREATE INDEX events_campaign_id_ts ON events (campaign_id, ts);

-- Enable Realtime on the tables the frontend subscribes to
ALTER PUBLICATION supabase_realtime ADD TABLE campaigns;
ALTER PUBLICATION supabase_realtime ADD TABLE events;
