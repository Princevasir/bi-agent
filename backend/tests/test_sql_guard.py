import pytest

from app.bi import sql_guard as validate_sql_module
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

# ---- GR-SQL-01: read-only statement shapes and approved functions only ----

BYPASSES = {
    "T-SQL01-01 query string": "SELECT query_to_xml('select note from internal_notes', true, true, '')",
    "T-SQL01-02 table to xml": "SELECT table_to_xml('internal_notes', true, true, '')",
    "T-SQL01-03 delete in cte": "WITH d AS (DELETE FROM orders RETURNING *) SELECT * FROM d",
    "T-SQL01-03 insert in cte": "WITH i AS (INSERT INTO regions (id, name) VALUES (9, 'x') RETURNING id) SELECT id FROM i",
    "T-SQL01-04 update in cte in union": (
        "WITH u AS (UPDATE orders SET amount = 0 RETURNING id) SELECT id FROM u UNION SELECT id FROM orders"),
    "T-SQL01-05 row generator": "SELECT generate_series(1, 1000000000)",
    "T-SQL01-06 repeat": "SELECT repeat('x', 100000000) FROM regions",
    "T-SQL01-06 lpad": "SELECT lpad('x', 100000000, 'y') FROM regions",
    "T-SQL01-07 version": "SELECT version()",
    "T-SQL01-07 server address": "SELECT inet_server_addr()",
    "T-SQL01-07 setting": "SELECT current_setting('data_directory')",
    "T-SQL01-07 current user": "SELECT current_user",
    "T-SQL01-07 current database": "SELECT current_database()",
    "T-SQL01-08 unknown function": "SELECT made_up_fn(amount) FROM orders",
    "T-SQL01-09 schema-qualified function": "SELECT pg_catalog.lower(name) FROM regions",
    "T-SQL01-10 quoted upper case": "SELECT \"QUERY_TO_XML\"('select 1', true, true, '')",
    "T-SQL01-10 mixed case": "SELECT Query_To_Xml('select 1', true, true, '')",
    "T-SQL01-11 in subquery": "SELECT (SELECT version()) FROM regions",
    "T-SQL01-11 in cte": "WITH v AS (SELECT version() AS v) SELECT v FROM v",
    "T-SQL01-11 in having": "SELECT region_id FROM orders GROUP BY region_id HAVING count(*) > length(version())",
    "T-SQL01-11 in order by": "SELECT id FROM orders ORDER BY md5(status)",
    "T-SQL01-11 in window": "SELECT sum(amount) OVER (ORDER BY made_up_fn(id)) FROM orders",
    "T-SQL01-11 in case": "SELECT CASE WHEN amount > 0 THEN version() END FROM orders",
    "T-SQL01-11 in union branch": "SELECT name FROM regions UNION SELECT version()",
    "T-SQL01-12 table function": "SELECT * FROM generate_series(1, 10)",
    "T-SQL01-12 lateral unnest": "SELECT * FROM regions, LATERAL unnest(ARRAY[1, 2]) AS u",
    "T-SQL01-14 union to forbidden table": "SELECT name FROM regions UNION SELECT note FROM internal_notes",
    "locking in subquery": "SELECT * FROM (SELECT * FROM orders FOR UPDATE) s",
}


@pytest.mark.parametrize("sql", BYPASSES.values(), ids=BYPASSES.keys())
def test_bypass_attempts_are_rejected(sql):
    with pytest.raises(SQLRejected):
        validate_sql(sql)


def test_table_function_gets_a_clear_message():
    with pytest.raises(SQLRejected, match="function"):
        validate_sql("SELECT * FROM generate_series(1, 10)")


def test_union_to_forbidden_table_names_the_table():
    with pytest.raises(SQLRejected, match="internal_notes"):
        validate_sql("SELECT name FROM regions UNION SELECT note FROM internal_notes")


ACCEPTED = {
    "T-SQL01-13 union": "SELECT name FROM regions UNION SELECT status FROM orders",
    "T-SQL01-13 union all": "SELECT name FROM regions UNION ALL SELECT status FROM orders",
    "T-SQL01-13 intersect": "SELECT id FROM regions INTERSECT SELECT region_id FROM orders",
    "T-SQL01-13 except": "SELECT id FROM regions EXCEPT SELECT region_id FROM orders",
    "T-SQL01-15 dates": (
        "SELECT date_trunc('month', order_date), to_char(order_date, 'YYYY-MM'), "
        "extract(month FROM order_date), date_part('year', order_date) FROM orders"),
    "T-SQL01-15 date arithmetic": (
        "SELECT now(), current_date, make_date(2026, 1, 1), age(order_date), "
        "order_date + interval '1 month', date '2026-01-01' FROM orders"),
    "T-SQL01-15 conditional and maths": (
        "SELECT coalesce(sum(amount), 0), nullif(count(*), 0), round(avg(amount)::numeric, 2), "
        "abs(1), ceil(1.2), floor(1.2), greatest(1, 2), least(1, 2) FROM orders"),
    "T-SQL01-15 aggregates": (
        "SELECT count(DISTINCT region_id), min(amount), max(amount), stddev(amount), "
        "percentile_cont(0.5) WITHIN GROUP (ORDER BY amount), string_agg(status, ','), "
        "count(*) FILTER (WHERE status = 'completed') FROM orders"),
    "T-SQL01-15 windows": (
        "SELECT rank() OVER (ORDER BY amount), row_number() OVER (), dense_rank() OVER (), "
        "lag(amount) OVER (ORDER BY id), lead(amount) OVER (ORDER BY id), "
        "sum(amount) OVER (PARTITION BY region_id) FROM orders"),
    "T-SQL01-15 strings and casts": (
        "SELECT CASE WHEN amount > 1 THEN 'a' ELSE 'b' END, CAST(amount AS int), amount::text, "
        "lower(status), upper(status), trim(status), length(status), concat(status, 'x'), "
        "substring(status, 1, 2), replace(status, 'a', 'b'), status || 'x' FROM orders"),
    "T-SQL01-17 comment is inert": "SELECT 1 FROM regions -- ; DROP TABLE orders",
    "cte reading allowed tables": (
        "WITH m AS (SELECT region_id, sum(amount) AS s FROM orders GROUP BY region_id) "
        "SELECT r.name, m.s FROM m JOIN regions r ON r.id = m.region_id ORDER BY m.s DESC LIMIT 1"),
}


@pytest.mark.parametrize("sql", ACCEPTED.values(), ids=ACCEPTED.keys())
def test_normal_analytics_sql_is_accepted(sql):
    assert validate_sql(sql)


# ---- GR-SQL-02: query structure limits --------------------------------------

def nine_table_join():
    return "SELECT 1 FROM orders o0 " + " ".join(
        f"JOIN orders o{i} ON o{i}.id = o{i - 1}.id" for i in range(1, 9))


def nested(depth):
    sql = "SELECT id FROM orders"
    for _ in range(depth):
        sql = f"SELECT id FROM ({sql}) AS s"
    return sql


TOO_BROAD = {
    "T-SQL02-01 comma join without condition": "SELECT count(*) FROM orders, orders AS o2, orders AS o3",
    "T-SQL02-02 cross join": "SELECT count(*) FROM orders CROSS JOIN regions",
    "T-SQL02-03 on true": "SELECT 1 FROM orders o JOIN regions r ON true",
    "T-SQL02-03 on constant comparison": "SELECT 1 FROM orders o JOIN regions r ON 1 = 1",
    "T-SQL02-04 comma join with unrelated where": (
        "SELECT 1 FROM orders o, regions r WHERE o.status = 'completed'"),
    "T-SQL02-04 same-table comparison only": "SELECT 1 FROM orders o JOIN regions r ON o.id = o.region_id",
    "T-SQL02-05 cross join inside a cte": (
        "WITH x AS (SELECT o.id FROM orders o CROSS JOIN regions r) SELECT count(*) FROM x"),
    "T-SQL02-06 nine tables": nine_table_join(),
    "T-SQL02-07 subqueries four deep": nested(4),
}


@pytest.mark.parametrize("sql", TOO_BROAD.values(), ids=TOO_BROAD.keys())
def test_too_broad_queries_are_rejected(sql):
    with pytest.raises(SQLRejected) as e:
        validate_sql(sql)
    assert e.value.user_message == validate_sql_module.TOO_BROAD_MESSAGE


STRUCTURE_OK = {
    "T-SQL02-08 join on": "SELECT r.name FROM orders o JOIN regions r ON o.region_id = r.id",
    "T-SQL02-08 left join": "SELECT r.name FROM regions r LEFT JOIN orders o ON o.region_id = r.id",
    "T-SQL02-08 using": "SELECT 1 FROM orders JOIN regions USING (id)",
    "T-SQL02-08 comma join with condition in where": (
        "SELECT r.name, sum(o.amount) FROM orders o, regions r WHERE o.region_id = r.id GROUP BY r.name"),
    "T-SQL02-08 unqualified join columns": "SELECT 1 FROM orders JOIN regions ON region_id = id",
    "T-SQL02-08 self join": "SELECT 1 FROM orders a JOIN orders b ON a.region_id = b.region_id AND a.id < b.id",
    "T-SQL02-09 share of a one-row total": (
        "SELECT r.name, sum(o.amount) / t.total FROM orders o JOIN regions r ON o.region_id = r.id "
        "CROSS JOIN (SELECT sum(amount) AS total FROM orders) AS t GROUP BY r.name, t.total"),
    "T-SQL02-09 one-row cte": (
        "WITH t AS (SELECT sum(amount) AS total FROM orders) "
        "SELECT o.id, o.amount / t.total FROM orders o CROSS JOIN t"),
    "T-SQL02-10 eight tables": "SELECT 1 FROM orders o0 " + " ".join(
        f"JOIN orders o{i} ON o{i}.id = o{i - 1}.id" for i in range(1, 8)),
    "T-SQL02-10 subqueries three deep": nested(3),
    "T-SQL02-10 union branches are not nesting": (
        "SELECT id FROM orders UNION SELECT id FROM orders UNION SELECT id FROM orders UNION SELECT id FROM orders"),
}


@pytest.mark.parametrize("sql", STRUCTURE_OK.values(), ids=STRUCTURE_OK.keys())
def test_well_formed_queries_pass_the_structure_limits(sql):
    assert validate_sql(sql)


def test_structure_limits_come_from_the_environment(monkeypatch):
    monkeypatch.setenv("SQL_MAX_TABLES", "2")
    with pytest.raises(SQLRejected):
        validate_sql("SELECT 1 FROM orders o JOIN regions r ON o.region_id = r.id JOIN regions r2 ON r2.id = r.id")
    monkeypatch.setenv("SQL_MAX_DEPTH", "1")
    with pytest.raises(SQLRejected):
        validate_sql(nested(2))


def test_other_rejections_keep_the_generic_message():
    with pytest.raises(SQLRejected) as e:
        validate_sql("SELECT * FROM internal_notes")
    assert e.value.user_message is None
