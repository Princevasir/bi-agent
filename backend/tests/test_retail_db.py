"""Loading the retail dataset into Postgres, and the access rules the database enforces.

Uses the retail_test database so the demo data in retail is never touched.
"""
import os

import psycopg
import pytest
from psycopg import errors

from retail.generate import collect
from retail.load import load

pytestmark = pytest.mark.integration

HOST = "localhost:5433"
OWNER_URL = os.getenv("RETAIL_TEST_OWNER_URL", f"postgresql://retail_owner:retail_owner_dev_pw@{HOST}/retail_test")
LOGINS = {
    "analyst": f"postgresql://retail_analyst:retail_analyst_dev_pw@{HOST}/retail_test",
    "limited": f"postgresql://retail_limited:retail_limited_dev_pw@{HOST}/retail_test",
    "manager": f"postgresql://retail_manager:retail_manager_dev_pw@{HOST}/retail_test",
}
SEED = 7


@pytest.fixture(scope="module")
def loaded():
    return load(OWNER_URL, seed=SEED, scale="tiny")


def query(url, sql):
    with psycopg.connect(url, connect_timeout=5) as conn:
        return conn.execute(sql).fetchall()


def test_row_counts_match_the_generator(loaded):
    expected = {t: len(rows) for t, rows in collect(seed=SEED, scale="tiny").items()}
    assert loaded == expected
    for table, n in expected.items():
        assert query(OWNER_URL, f"SELECT count(*) FROM {table}")[0][0] == n, table


def test_loading_again_replaces_the_data(loaded):
    again = load(OWNER_URL, seed=SEED, scale="tiny")
    assert again == loaded
    assert query(OWNER_URL, "SELECT count(*) FROM orders")[0][0] == loaded["orders"]


def test_foreign_keys_are_declared(loaded):
    n = query(OWNER_URL, """
        SELECT count(*) FROM information_schema.table_constraints
        WHERE constraint_type = 'FOREIGN KEY' AND table_schema = 'public'""")[0][0]
    assert n >= 40


def test_every_foreign_key_column_is_indexed(loaded):
    unindexed = query(OWNER_URL, """
        SELECT c.conrelid::regclass::text, a.attname
        FROM pg_constraint c
        JOIN pg_attribute a ON a.attrelid = c.conrelid AND a.attnum = c.conkey[1]
        WHERE c.contype = 'f' AND c.connamespace = 'public'::regnamespace
          AND NOT EXISTS (
            SELECT 1 FROM pg_index i
            WHERE i.indrelid = c.conrelid AND i.indkey[0] = c.conkey[1])""")
    assert unindexed == []


def test_every_table_has_a_primary_key(loaded):
    missing = query(OWNER_URL, """
        SELECT t.table_name FROM information_schema.tables t
        WHERE t.table_schema = 'public' AND t.table_type = 'BASE TABLE'
          AND NOT EXISTS (
            SELECT 1 FROM information_schema.table_constraints c
            WHERE c.table_name = t.table_name AND c.constraint_type = 'PRIMARY KEY')""")
    assert missing == []


def test_check_constraints_reject_bad_rows(loaded):
    with psycopg.connect(OWNER_URL) as conn:
        with pytest.raises(errors.CheckViolation):
            conn.execute("UPDATE order_items SET quantity = 0 WHERE order_item_id = 1")
        conn.rollback()


# ---- access rules, enforced by the database -------------------------------

def test_analyst_can_read_sales_and_non_personal_customer_columns(loaded):
    assert query(LOGINS["analyst"], "SELECT count(*) FROM orders")[0][0] == loaded["orders"]
    assert query(LOGINS["analyst"], "SELECT count(*) FROM customers WHERE signup_date IS NOT NULL")[0][0] > 0


@pytest.mark.parametrize("sql", [
    "SELECT email FROM customers LIMIT 1",
    "SELECT phone FROM customers LIMIT 1",
    "SELECT first_name FROM customers LIMIT 1",
    "SELECT street FROM customer_addresses LIMIT 1",
    "SELECT salary FROM employees LIMIT 1",
    "SELECT * FROM customers LIMIT 1",
])
def test_analyst_is_refused_personal_and_salary_columns(loaded, sql):
    with pytest.raises(errors.InsufficientPrivilege):
        query(LOGINS["analyst"], sql)


def test_manager_can_read_personal_columns(loaded):
    assert query(LOGINS["manager"], "SELECT email FROM customers LIMIT 1")[0][0].endswith("@example.com")
    assert query(LOGINS["manager"], "SELECT salary FROM employees LIMIT 1")


def test_limited_can_read_the_product_catalogue_only(loaded):
    assert query(LOGINS["limited"], "SELECT count(*) FROM products")[0][0] > 0
    assert query(LOGINS["limited"], "SELECT count(*) FROM stores")[0][0] > 0
    for table in ("orders", "order_items", "customers", "payments", "employees"):
        with pytest.raises(errors.InsufficientPrivilege):
            query(LOGINS["limited"], f"SELECT 1 FROM {table} LIMIT 1")


@pytest.mark.parametrize("role", sorted(LOGINS))
def test_every_login_is_read_only(loaded, role):
    with psycopg.connect(LOGINS[role]) as conn:
        with pytest.raises((errors.ReadOnlySqlTransaction, errors.InsufficientPrivilege)):
            conn.execute("INSERT INTO regions (region_id, name) VALUES (999, 'x')")


@pytest.mark.parametrize("role", sorted(LOGINS))
def test_logins_cannot_reach_the_sample_or_app_databases(role):
    user_url = LOGINS[role]
    for db in ("analytics", "appdb"):
        with pytest.raises(psycopg.OperationalError):
            query(user_url.rsplit("/", 1)[0] + "/" + db, "SELECT 1")
