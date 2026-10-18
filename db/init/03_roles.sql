CREATE ROLE bi_readonly LOGIN PASSWORD 'readonly_dev_pw';
GRANT CONNECT ON DATABASE analytics TO bi_readonly;
GRANT USAGE ON SCHEMA public TO bi_readonly;
GRANT SELECT ON orders, regions TO bi_readonly;
ALTER ROLE bi_readonly SET default_transaction_read_only = on;
ALTER ROLE bi_readonly SET statement_timeout = '5s';