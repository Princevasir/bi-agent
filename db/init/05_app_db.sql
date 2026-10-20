CREATE ROLE app_rw LOGIN PASSWORD 'app_dev_pw';
CREATE DATABASE appdb OWNER app_rw;
REVOKE CONNECT ON DATABASE appdb FROM PUBLIC;
\connect appdb
CREATE TABLE users (
  id SERIAL PRIMARY KEY,
  username TEXT UNIQUE NOT NULL CHECK (username = lower(username)),
  password_hash TEXT NOT NULL,
  role TEXT NOT NULL CHECK (role IN ('analyst', 'limited')),
  is_active BOOLEAN NOT NULL DEFAULT TRUE,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
GRANT SELECT, INSERT, UPDATE ON users TO app_rw;
GRANT USAGE, SELECT ON SEQUENCE users_id_seq TO app_rw;