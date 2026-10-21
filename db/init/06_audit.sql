\connect appdb
CREATE SCHEMA audit AUTHORIZATION admin;
CREATE TABLE audit.events (
  id BIGSERIAL PRIMARY KEY,
  ts TIMESTAMPTZ NOT NULL DEFAULT now(),
  request_id TEXT,
  username TEXT,
  role TEXT,
  event TEXT NOT NULL,
  status_code INT,
  detail JSONB NOT NULL DEFAULT '{}'::jsonb
);
GRANT USAGE ON SCHEMA audit TO app_rw;
GRANT INSERT ON audit.events TO app_rw;
GRANT USAGE ON SEQUENCE audit.events_id_seq TO app_rw;
