-- Retail demo databases (M28). Tables and data are created by the generator:
--   cd backend && .venv/bin/python -m retail.load --scale full
-- retail holds the demo data; retail_test is rebuilt by the integration tests.
CREATE ROLE retail_owner   LOGIN PASSWORD 'retail_owner_dev_pw';
CREATE ROLE retail_analyst LOGIN PASSWORD 'retail_analyst_dev_pw';
CREATE ROLE retail_limited LOGIN PASSWORD 'retail_limited_dev_pw';
CREATE ROLE retail_manager LOGIN PASSWORD 'retail_manager_dev_pw';

ALTER ROLE retail_analyst SET default_transaction_read_only = on;
ALTER ROLE retail_limited SET default_transaction_read_only = on;
ALTER ROLE retail_manager SET default_transaction_read_only = on;
ALTER ROLE retail_analyst SET statement_timeout = '15s';
ALTER ROLE retail_limited SET statement_timeout = '15s';
ALTER ROLE retail_manager SET statement_timeout = '15s';

CREATE DATABASE retail OWNER retail_owner;
CREATE DATABASE retail_test OWNER retail_owner;

-- Only the logins named here may connect; by default every role may connect to a new database.
REVOKE CONNECT ON DATABASE retail, retail_test FROM PUBLIC;
GRANT CONNECT ON DATABASE retail, retail_test TO retail_owner, retail_analyst, retail_limited, retail_manager;
REVOKE CONNECT ON DATABASE analytics FROM PUBLIC;
GRANT CONNECT ON DATABASE analytics TO bi_readonly, bi_limited;
