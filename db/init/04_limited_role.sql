CREATE ROLE bi_limited LOGIN PASSWORD 'limited_dev_pw';
GRANT CONNECT ON DATABASE analytics TO bi_limited;
GRANT USAGE ON SCHEMA public TO bi_limited;
GRANT SELECT ON regions TO bi_limited;
ALTER ROLE bi_limited SET default_transaction_read_only = on;
ALTER ROLE bi_limited SET statement_timeout = '5s';