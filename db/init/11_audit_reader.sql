-- A read-only login for alerting and audits (GR-OBS-02): it reads the audit trail and the token
-- ledger, nothing else. Local development password; replace it anywhere shared.
-- Apply to a running database: docker compose exec -T db psql -U admin -d postgres < db/init/11_audit_reader.sql
DO $$ BEGIN
  IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'audit_reader') THEN
    CREATE ROLE audit_reader LOGIN PASSWORD 'audit_reader_dev_pw';
  END IF;
END $$;
GRANT CONNECT ON DATABASE appdb TO audit_reader;
\connect appdb
GRANT USAGE ON SCHEMA audit TO audit_reader;
GRANT SELECT ON audit.events TO audit_reader;
GRANT SELECT ON token_usage TO audit_reader;
