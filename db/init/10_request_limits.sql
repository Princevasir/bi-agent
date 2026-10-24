-- Per-user request limits shared by every backend instance (GR-COST-01, GR-COST-03), used when
-- STATE_STORE=postgres. Times are Unix seconds from the backend's clock.
-- Apply to a running database: docker compose exec -T db psql -U admin -d postgres < db/init/10_request_limits.sql
\connect appdb

CREATE TABLE IF NOT EXISTS request_usage (        -- one row per question asked (same shape as token_usage)
  spent_at DOUBLE PRECISION NOT NULL,
  username TEXT,
  tokens INTEGER NOT NULL CHECK (tokens >= 0)
);
CREATE INDEX IF NOT EXISTS request_usage_user ON request_usage (username, spent_at);

CREATE TABLE IF NOT EXISTS running_questions (    -- at most one running question per user
  username TEXT PRIMARY KEY,
  started_at DOUBLE PRECISION NOT NULL
);

GRANT SELECT, INSERT, UPDATE, DELETE ON request_usage, running_questions TO app_rw;
