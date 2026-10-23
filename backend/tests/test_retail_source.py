"""M29b: the app answers from the retail data, with the catalog in the prompt and column rules."""
import pytest
from fastapi.testclient import TestClient

from app import access, catalog, policy
from app.bi import schema, service
from app.bi.sql_guard import PERSONAL_DATA_MESSAGE, SQLRejected, validate_sql
from app.bi.text_to_sql import build_prompt, rules_text
from app.llm import get_llm
from app.main import app
from app.policy import PolicyError
from retail.load import load
from routed_llm import RoutedLLM

client = TestClient(app)
OWNER_URL = "postgresql://retail_owner:retail_owner_dev_pw@localhost:5433/retail_test"
PERSONAL = {
    ("customers", "first_name"), ("customers", "last_name"), ("customers", "email"), ("customers", "phone"),
    ("customer_addresses", "street"), ("customer_addresses", "postal_code"),
    ("employees", "first_name"), ("employees", "last_name"), ("employees", "email"), ("employees", "salary"),
}
REVENUE_BY_REGION = (
    "SELECT r.name AS region, SUM(oi.line_total) AS revenue FROM orders o "
    "JOIN order_items oi ON oi.order_id = o.order_id JOIN stores s ON s.store_id = o.store_id "
    "JOIN countries c ON c.country_id = s.country_id JOIN regions r ON r.region_id = c.region_id "
    "WHERE o.status = 'completed' GROUP BY r.name ORDER BY r.name")


@pytest.fixture
def retail(monkeypatch):
    monkeypatch.setenv("DATA_SOURCE", "retail")
    schema.clear_cache()
    yield
    schema.clear_cache()


@pytest.fixture(autouse=True)
def clear_llm_override():
    yield
    app.dependency_overrides.pop(get_llm, None)


@pytest.fixture(scope="module")
def loaded():
    load(OWNER_URL, seed=7, scale="tiny")


# ---- the policy and the roles -------------------------------------------------------------------------

def test_sample_is_the_default_source_and_unchanged():
    assert access.data_source() == "sample"
    assert access.tables_for("analyst") == ("orders", "regions")
    assert access.denied_columns("analyst") == frozenset()


def test_retail_roles(retail):
    assert len(access.tables_for("analyst")) == 29
    assert set(access.tables_for("limited")) == {"regions", "countries", "stores", "warehouses", "categories",
                                                  "brands", "products", "product_prices"}
    assert access.db_env_for("analyst") == "RETAIL_DATABASE_URL"
    assert access.db_env_for("limited") == "RETAIL_DATABASE_URL_LIMITED"


def test_an_unknown_data_source_is_refused(monkeypatch):
    monkeypatch.setenv("DATA_SOURCE", "warehouse")
    with pytest.raises(PolicyError, match="DATA_SOURCE"):
        access.data_source()


def test_retail_policy_invariants():
    roles = policy.get().sources["retail"].roles
    described = set(catalog.load().tables)
    assert all(set(r.tables) <= described for r in roles.values())
    assert set(roles["limited"].tables) <= set(roles["analyst"].tables)
    assert not any(r.personal_data for r in roles.values()), "no app role may read personal data yet"


def test_personal_columns_are_denied_on_retail(retail):
    assert access.denied_columns("analyst") == PERSONAL
    assert access.denied_columns("limited") == PERSONAL


# ---- GR-SQL-05: column rules in the validator ---------------------------------------------------------

DENIED = frozenset(PERSONAL)
ALL = tuple(catalog.load().tables)


@pytest.mark.parametrize("sql", [
    "SELECT email FROM customers",
    "SELECT c.email FROM customers c",
    "SELECT first_name, last_name FROM customers",
    "SELECT * FROM customers",
    "SELECT c.* FROM orders o JOIN customers c ON c.customer_id = o.customer_id",
    "WITH x AS (SELECT email FROM customers) SELECT * FROM x",
    "SELECT salary FROM employees ORDER BY salary DESC LIMIT 1",
    "SELECT avg(salary) FROM employees",
    "SELECT street FROM customer_addresses",
])
def test_personal_data_is_refused_before_the_database(sql):
    with pytest.raises(SQLRejected) as e:
        validate_sql(sql, ALL, DENIED)
    assert e.value.user_message == PERSONAL_DATA_MESSAGE


@pytest.mark.parametrize("sql", [
    "SELECT customer_id, signup_date FROM customers",
    "SELECT count(*) FROM customers",
    "SELECT * FROM orders",
    "SELECT o.order_id, c.country_id FROM orders o JOIN customers c ON c.customer_id = o.customer_id",
    "SELECT job_title, count(*) FROM employees GROUP BY job_title",
])
def test_non_personal_columns_are_allowed(sql):
    assert validate_sql(sql, ALL, DENIED)


def test_without_denied_columns_nothing_changes():
    assert validate_sql("SELECT * FROM orders")


# ---- the prompt ------------------------------------------------------------------------------------------

def test_rules_mention_personal_data_only_where_it_is_denied(retail, monkeypatch):
    assert "personal data" in rules_text("analyst").lower()
    monkeypatch.setenv("DATA_SOURCE", "sample")
    assert "personal data" not in rules_text("analyst").lower()


@pytest.mark.integration
def test_retail_prompt_comes_from_the_catalog(retail, loaded):
    text = schema.schema_text("analyst")
    assert "orders: Customer orders, online and in stores" in text
    assert "One row per order." in text
    assert "Revenue counts completed orders only" in text
    assert "customer_id -> customers.customer_id" in text
    assert "status text [completed, cancelled]" in text
    assert "  - signup_date " in text
    for column in ("email", "phone", "first_name", "last_name", "street", "postal_code", "salary"):
        assert f"  - {column} " not in text, column     # "email" is also a marketing channel value
    metrics = schema.metrics_text("analyst")
    assert "revenue" in metrics and "SUM(order_items.line_total)" in metrics


@pytest.mark.integration
def test_limited_sees_only_its_tables(retail, loaded):
    text = schema.schema_text("limited")
    assert "products:" in text and "orders:" not in text and "customers:" not in text
    assert "SUM(order_items.line_total)" not in schema.metrics_text("limited")


@pytest.mark.integration
def test_the_retail_prompt_fits_the_local_model(retail, loaded):
    from datetime import date
    prompt = build_prompt("What was revenue by region in 2025?", date(2026, 10, 15), "analyst")
    assert len(prompt) < 40_000, len(prompt)       # about 10,000 tokens; the local window is 16,384


# ---- end to end -----------------------------------------------------------------------------------------

@pytest.mark.integration
def test_ask_answers_from_the_retail_data(retail, loaded):
    app.dependency_overrides[get_llm] = lambda: RoutedLLM(REVENUE_BY_REGION, answer="Revenue by region.")
    r = client.post("/ask", json={"message": "Revenue by region"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["columns"] == ["region", "revenue"]
    assert {row[0] for row in body["rows"]} <= {"North America", "Europe", "Asia Pacific"}


@pytest.mark.integration
def test_ask_for_personal_data_gets_a_clear_refusal(retail, loaded, monkeypatch, audit_events):
    def no_query(*a, **kw):
        raise AssertionError("must not reach the database")

    monkeypatch.setattr(service, "run_readonly", no_query)
    app.dependency_overrides[get_llm] = lambda: RoutedLLM("SELECT email FROM customers")
    r = client.post("/ask", json={"message": "Show customer emails"})
    assert r.status_code == 422
    assert r.json() == {"detail": PERSONAL_DATA_MESSAGE}
    assert [e["event"] for e in audit_events] == ["sql_rejected"]


@pytest.mark.integration
def test_retail_prompt_includes_the_sql_hints(retail, loaded):
    from datetime import date
    prompt = build_prompt("Revenue by quarter in 2025", date(2026, 10, 15), "analyst")
    assert "EXTRACT(QUARTER FROM orders.ordered_at)" in prompt


def test_sample_prompt_has_no_retail_hints(monkeypatch):
    from datetime import date
    import app.bi.text_to_sql as t2s
    monkeypatch.setattr(t2s, "schema_text", lambda role="analyst": "orders(id integer)")
    assert "EXTRACT(QUARTER FROM orders.ordered_at)" not in build_prompt("x", date(2026, 10, 15))


@pytest.mark.integration
def test_missing_status_filter_is_repaired_and_the_number_is_right(retail, loaded):
    import psycopg
    bad = ("SELECT SUM(order_items.line_total) AS revenue FROM orders JOIN order_items "
           "ON orders.order_id = order_items.order_id WHERE orders.ordered_at >= '2025-01-01' "
           "AND orders.ordered_at < '2026-01-01'")
    good = bad.replace("WHERE ", "WHERE orders.status = 'completed' AND ")
    sqls = iter([bad, good])
    prompts = []

    class Model(RoutedLLM):
        def generate(self, prompt):
            prompts.append(prompt)
            if prompt.startswith("You write PostgreSQL"):
                return super().generate(prompt).__class__(text=next(sqls), input_tokens=1, output_tokens=1)
            return super().generate(prompt)

    app.dependency_overrides[get_llm] = lambda: Model("", answer="Revenue.")
    r = client.post("/ask", json={"message": "What was revenue in 2025?"})
    assert r.status_code == 200, r.text
    with psycopg.connect(OWNER_URL) as conn:
        truth = float(conn.execute(good).fetchone()[0])
    assert r.json()["sql_repairs"] == 1 and r.json()["rows"] == [[truth]]
    assert any("orders.status = 'completed'" in p and "previous query failed" in p for p in prompts)
