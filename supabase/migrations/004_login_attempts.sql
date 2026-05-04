CREATE TABLE IF NOT EXISTS login_attempts (
    id                 BIGSERIAL PRIMARY KEY,
    ip                 TEXT NOT NULL,
    username_attempted TEXT NOT NULL DEFAULT '',
    succeeded          BOOLEAN NOT NULL DEFAULT FALSE,
    attempted_at       TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX login_attempts_ip_time ON login_attempts (ip, attempted_at);

ALTER TABLE login_attempts ENABLE ROW LEVEL SECURITY;
-- No policies = only service role can access
