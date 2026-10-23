"""GR-ACC-01 and GR-ACC-02: queries must follow the catalog's metric rules (retail only)."""
import shutil
from pathlib import Path

import pytest

from app import access, catalog
from app.bi.sql_guard import SQLRejected, validate_sql

ALL = tuple(catalog.load().tables)
RULES = catalog.load().rules
CATALOG_DIR = Path(__file__).resolve().parents[1] / "catalog"

# What the local model actually wrote on 23 Oct 2026 for "pie chart of revenue by quarter in 2025".
MODEL_QUARTERS = (
    "SELECT EXTRACT(QUARTER FROM orders.ordered_at) AS quarter, SUM(order_items.line_total) AS revenue "
    "FROM orders JOIN order_items ON orders.order_id = order_items.order_id "
    "WHERE orders.ordered_at >= '2025-01-01' AND orders.ordered_at < '2026-01-01' "
    "GROUP BY quarter ORDER BY quarter")
COMPLETED = " AND o.status = 'completed'"
BASE = ("SELECT SUM(oi.line_total) FROM orders o JOIN order_items oi ON oi.order_id = o.order_id "
        "WHERE o.ordered_at >= '2025-01-01'")


def check(sql):
    return validate_sql(sql, ALL, rules=RULES)


# ---- the rules file ------------------------------------------------------------------------------------

def test_rules_are_loaded_from_the_catalog():
    assert {r.id for r in RULES} == {"completed-orders-only", "no-double-counting"}


def test_rules_naming_unknown_columns_are_refused(tmp_path):
    target = tmp_path / "catalog"
    shutil.copytree(CATALOG_DIR, target)
    f = target / "rules.toml"
    f.write_text(f.read_text().replace('"order_items.line_total"', '"order_items.made_up"', 1))
    with pytest.raises(catalog.CatalogError, match="made_up"):
        catalog.load(target)


# ---- GR-ACC-01: money and units count completed orders only --------------------------------------------

@pytest.mark.parametrize("sql", [
    MODEL_QUARTERS,
    BASE,
    "SELECT SUM(line_total) FROM order_items",
    "SELECT AVG(total_amount) FROM orders",
    "SELECT SUM(oi.quantity) FROM order_items oi JOIN products p ON p.product_id = oi.product_id",
    "WITH x AS (SELECT oi.line_total FROM order_items oi) SELECT SUM(line_total) FROM x",
])
def test_money_without_a_status_filter_is_sent_back(sql):
    with pytest.raises(SQLRejected) as e:
        check(sql)
    assert e.value.repairable and "orders.status = 'completed'" in str(e.value)


@pytest.mark.parametrize("sql", [
    BASE + COMPLETED,
    MODEL_QUARTERS.replace("GROUP BY", "AND orders.status = 'completed' GROUP BY"),
    BASE + " AND o.status IN ('completed')",
    BASE + " AND o.status = 'cancelled'",                                       # asked about cancelled orders
    "SELECT o.status, SUM(oi.line_total) FROM orders o JOIN order_items oi ON oi.order_id = o.order_id GROUP BY o.status",
    "SELECT SUM(oi.line_total) FILTER (WHERE o.status = 'completed') FROM orders o JOIN order_items oi ON oi.order_id = o.order_id",
    "SELECT SUM(CASE WHEN o.status = 'completed' THEN oi.line_total END) FROM orders o JOIN order_items oi ON oi.order_id = o.order_id",
    "SELECT o.order_id, o.total_amount FROM orders o ORDER BY o.total_amount DESC LIMIT 10",   # a list, no total
    "SELECT COUNT(*) FROM orders",
    "SELECT SUM(poi.quantity) FROM purchase_order_items poi",                                 # stock bought, not sold
    "SELECT SUM(r.refund_amount) FROM returns r",
])
def test_queries_that_follow_the_rule_pass(sql):
    assert check(sql)


# ---- GR-ACC-02: per-order amounts are not summed after joining items ------------------------------------

@pytest.mark.parametrize("sql", [
    "SELECT SUM(o.total_amount) FROM orders o JOIN order_items oi ON oi.order_id = o.order_id WHERE o.status = 'completed'",
    "SELECT AVG(o.subtotal) FROM orders o JOIN order_items oi ON oi.order_id = o.order_id WHERE o.status = 'completed'",
])
def test_double_counting_is_sent_back(sql):
    with pytest.raises(SQLRejected) as e:
        check(sql)
    assert e.value.repairable and "line_total" in str(e.value)


def test_per_order_amounts_without_the_items_join_pass():
    assert check("SELECT SUM(o.total_amount) FROM orders o WHERE o.status = 'completed'")


# ---- only where a catalog defines rules -------------------------------------------------------------------

def test_no_rules_means_no_checks():
    assert validate_sql("SELECT SUM(amount) FROM orders")


def test_metric_rules_follow_the_data_source(monkeypatch):
    assert access.metric_rules() == ()
    monkeypatch.setenv("DATA_SOURCE", "retail")
    assert {r.id for r in access.metric_rules()} == {"completed-orders-only", "no-double-counting"}
