"""GR-PRIV-03: aggregate results never describe fewer than 5 customers (owner's decision, 24 October 2026)."""
from datetime import date

import pytest
import sqlglot

from app import limits, policy
from app.bi import schema
from app.bi.service import answer_question
from app.bi.small_groups import HELPER, suppress_small_groups, with_customer_count
from retail.load import load
from routed_llm import RoutedLLM

TODAY = date(2026, 10, 24)
OWNER_URL = "postgresql://retail_owner:retail_owner_dev_pw@localhost:5433/retail_test"


def same_sql(a, b):
    return sqlglot.parse_one(a, read="postgres").sql() == sqlglot.parse_one(b, read="postgres").sql()


# ---- adding the customer count -------------------------------------------------------------------------

def test_a_grouped_customer_query_gets_a_customer_count():
    sql = ("SELECT lt.name, AVG(o.total_amount) FROM orders o JOIN loyalty_memberships lm ON lm.customer_id = o.customer_id "
           "JOIN loyalty_tiers lt ON lt.tier_id = lm.tier_id GROUP BY lt.name ORDER BY 2 DESC")
    assert same_sql(with_customer_count(sql),
                    "SELECT lt.name, AVG(o.total_amount), COUNT(DISTINCT o.customer_id) AS bi_group_customers "
                    "FROM orders o JOIN loyalty_memberships lm ON lm.customer_id = o.customer_id "
                    "JOIN loyalty_tiers lt ON lt.tier_id = lm.tier_id GROUP BY lt.name ORDER BY 2 DESC")


def test_the_customers_table_is_preferred_when_present():
    sql = "SELECT c.loyalty_tier, COUNT(*) FROM customers c JOIN orders o ON o.customer_id = c.customer_id GROUP BY 1"
    assert "COUNT(DISTINCT c.customer_id)" in with_customer_count(sql)


def test_a_single_group_without_group_by_is_checked_too():
    sql = "SELECT AVG(o.total_amount) FROM orders o WHERE o.store_id = 3"
    assert "COUNT(DISTINCT o.customer_id)" in with_customer_count(sql)


def test_an_unaliased_table_is_qualified_by_its_name():
    assert "COUNT(DISTINCT orders.customer_id)" in with_customer_count("SELECT SUM(total_amount) FROM orders")


@pytest.mark.parametrize("sql", [
    "SELECT r.name, COUNT(*) FROM regions r JOIN countries c ON c.region_id = r.region_id GROUP BY 1",   # no customers
    "SELECT order_id, total_amount FROM orders LIMIT 10",                                                 # not aggregated
    "SELECT order_id, SUM(total_amount) OVER (ORDER BY order_id) FROM orders",                            # window only
    "WITH t AS (SELECT customer_id, SUM(total_amount) s FROM orders GROUP BY 1) SELECT AVG(s) FROM t",    # not handled
    "SELECT 1 UNION SELECT 2",
])
def test_queries_it_does_not_apply_to(sql):
    assert with_customer_count(sql) is None


# ---- hiding small groups ---------------------------------------------------------------------------------

def test_groups_under_the_minimum_are_removed_and_the_helper_column_dropped():
    columns = ["tier", "avg_spend", HELPER]
    rows = [["Bronze", 120.0, 40], ["Platinum", 980.0, 3], ["Gold", 450.0, 5]]
    assert suppress_small_groups(columns, rows, 5) == (["tier", "avg_spend"], [["Bronze", 120.0], ["Gold", 450.0]], 1)


def test_a_result_without_the_helper_is_unchanged():
    assert suppress_small_groups(["a"], [[1]], 5) == (["a"], [[1]], 0)


def test_the_minimum_comes_from_the_policy_and_can_only_be_raised(monkeypatch):
    assert policy.get().sql["min_group_customers"] == 5 and limits.privacy_min_group() == 5
    monkeypatch.setenv("PRIVACY_MIN_GROUP", "10")
    assert limits.privacy_min_group() == 10
    monkeypatch.setenv("PRIVACY_MIN_GROUP", "1")
    assert limits.privacy_min_group() == 5            # lowering it would weaken privacy


# ---- end to end on the retail test data ---------------------------------------------------------------------

@pytest.fixture(scope="module")
def loaded():
    load(OWNER_URL, seed=7, scale="tiny")


@pytest.fixture
def retail(monkeypatch, loaded):
    monkeypatch.setenv("DATA_SOURCE", "retail")
    schema.clear_cache()
    yield
    schema.clear_cache()


def ask(sql, question="Average spend per customer", answer="See the table."):
    llm = RoutedLLM(sql, answer=answer)
    return answer_question(question, lambda p: llm.generate(p).text, TODAY, role="analyst")


@pytest.mark.integration
def test_per_customer_groups_are_all_hidden(retail):
    out = ask("SELECT o.customer_id, AVG(o.total_amount) AS avg_spend FROM orders o "
              "WHERE o.status = 'completed' GROUP BY o.customer_id")
    # every identified customer is hidden; only the anonymous guest-orders group (customer_id NULL) remains
    assert all(r[0] is None for r in out["rows"]) and out["suppressed_groups"] > 0
    assert "fewer than 5 customers" in out["answer"]


@pytest.mark.integration
def test_large_groups_are_shown_without_the_helper_column(retail):
    sql = ("SELECT o.channel, COUNT(*) AS orders FROM orders o WHERE o.status = 'completed' GROUP BY o.channel "
           "ORDER BY o.channel")
    out = ask(sql)
    assert out["rows"] and out["suppressed_groups"] == 0 and out["columns"] == ["channel", "orders"]
    assert out["sql"].startswith("SELECT o.channel, COUNT(*)")          # the user sees their own query


def test_rows_with_no_identifiable_customers_are_kept():
    # Guest orders have no customer_id: such a row cannot single out a customer (seen: the "Unknown"
    # region, 2.6M of guest revenue, was wrongly hidden on the full retail data).
    columns = ["region", "revenue", HELPER]
    rows = [["Europe", 12225840.39, 9000], ["Unknown", 2619434.10, 0], ["Tiny", 50.0, 2]]
    assert suppress_small_groups(columns, rows, 5) == (["region", "revenue"],
                                                       [["Europe", 12225840.39], ["Unknown", 2619434.10]], 1)
