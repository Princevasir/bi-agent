-- Shared state for more than one backend instance (demo gap D11): conversations, the sign-in
-- throttle and the token ledger, used when STATE_STORE=postgres. Times are Unix seconds from the
-- backend's clock, so the same code works with the in-memory stores and with injected test clocks.
-- Apply to a running database: docker compose exec -T db psql -U admin -d postgres < db/init/09_shared_state.sql
\connect appdb

CREATE TABLE IF NOT EXISTS conversations (
  key TEXT PRIMARY KEY,                       -- username:conversation_id
  turns JSONB NOT NULL DEFAULT '[]',
  updated_at DOUBLE PRECISION NOT NULL
);
CREATE INDEX IF NOT EXISTS conversations_updated_at ON conversations (updated_at);

CREATE TABLE IF NOT EXISTS login_failures (
  username TEXT NOT NULL,
  failed_at DOUBLE PRECISION NOT NULL
);
CREATE INDEX IF NOT EXISTS login_failures_user ON login_failures (username, failed_at);

CREATE TABLE IF NOT EXISTS login_locks (
  username TEXT PRIMARY KEY,
  locked_until DOUBLE PRECISION NOT NULL
);

CREATE TABLE IF NOT EXISTS token_usage (
  spent_at DOUBLE PRECISION NOT NULL,
  username TEXT,
  tokens INTEGER NOT NULL CHECK (tokens >= 0)
);
CREATE INDEX IF NOT EXISTS token_usage_spent_at ON token_usage (spent_at);

GRANT SELECT, INSERT, UPDATE, DELETE ON conversations, login_failures, login_locks, token_usage TO app_rw;
