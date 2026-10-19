import pytest

from app.bi.sql_guard import SQLRejected, validate_sql

REJECTED = [
    "DROP TABLE orders",
    "DELETE FROM orders",
    "UPDATE orders SET amount=0",
    "SELECT 1; SELECT 2",
    "SELECT * FROM internal_notes",
    "SELECT * FROM pg_catalog.pg_tables",
    "SELECT * FROM information_schema.columns",
    "SELECT pg_sleep(5)",
    "SELECT * INTO x FROM orders",
    "SELECT * FROM orders FOR UPDATE",
    "",
]

# Exactly what the real model returned in M15, including the trailing semicolon.
REVENUE_BY_REGION = """SELECT r.name AS region_name, SUM(o.amount) AS revenue
FROM orders o
JOIN regions r ON o.region_id = r.id
WHERE o.status = 'completed' AND o.order_date BETWEEN '2026-09-01' AND '2026-09-30'
GROUP BY r.name;"""

WITH_QUERY = (
    "WITH completed AS (SELECT * FROM orders WHERE status = 'completed') "
    "SELECT COUNT(*) FROM completed"
)


@pytest.mark.parametrize("sql", REJECTED)
def test_dangerous_sql_is_rejected(sql):
    with pytest.raises(SQLRejected):
        validate_sql(sql)


def test_revenue_by_region_is_accepted():
    result = validate_sql(REVENUE_BY_REGION)
    assert result.upper().startswith("SELECT")
    assert "orders" in result
    assert ";" not in result


def test_with_query_is_accepted():
    result = validate_sql(WITH_QUERY)
    assert result.upper().startswith("WITH")