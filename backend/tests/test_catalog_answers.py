"""M29c part 2: questions about the data are answered from the role's catalog, without the model."""
import pytest
from fastapi.testclient import TestClient

from app.bi import schema
from app.bi.catalog_answers import answer, catalog_question
from app.llm import get_llm
from app.main import app
from retail.load import load
from routed_llm import RoutedLLM

client = TestClient(app)
OWNER_URL = "postgresql://retail_owner:retail_owner_dev_pw@localhost:5433/retail_test"

CAT = {
    "orders": {"name": "orders", "domain": "Sales", "description": "Customer orders.", "grain": "One row per order.",
               "caveats": ["Revenue counts completed orders only."], "primary_key": ["order_id"],
               "foreign_keys": [{"column": "customer_id", "table": "customers", "references": "customer_id"}],
               "referenced_by": [{"table": "order_items", "column": "order_id"}], "rows": 281682,
               "columns": [{"name": "order_id", "type": "integer", "nullable": False, "primary_key": True,
                            "references": None, "description": "Order key.", "values": [], "unit": "", "pii": False},
                           {"name": "status", "type": "text", "nullable": False, "primary_key": False,
                            "references": None, "description": "Order outcome.", "values": ["completed", "cancelled"],
                            "unit": "", "pii": False}]},
    "order_items": {"name": "order_items", "domain": "Sales", "description": "Products on each order.",
                    "grain": "One row per product on an order.", "caveats": [], "primary_key": ["order_item_id"],
                    "foreign_keys": [], "referenced_by": [], "rows": 513734,
                    "columns": [{"name": "line_total", "type": "numeric", "nullable": False, "primary_key": False,
                                 "references": None, "description": "What the customer paid for the line.",
                                 "values": [], "unit": "USD", "pii": False}]},
    "regions": {"name": "regions", "domain": "Geography", "description": "Sales regions.", "grain": "One row per region.",
                "caveats": [], "primary_key": ["region_id"], "foreign_keys": [], "referenced_by": [], "rows": 3,
                "columns": [{"name": "region_id", "type": "integer", "nullable": False, "primary_key": True,
                             "references": None, "description": "Region key.", "values": [], "unit": "", "pii": False}]},
}
METRICS = [{"name": "revenue", "description": "Money paid for completed orders.",
            "definition": "SUM(order_items.line_total) WHERE orders.status = 'completed'"}]


# ---- recognising questions about the data ------------------------------------------------------------

@pytest.mark.parametrize("text,intent", [
    ("Show me the list of tables with description", ("list_tables", None)),
    ("What tables do I have access to?", ("list_tables", None)),
    ("what data can I see", ("list_tables", None)),
    ("Describe the orders table", ("describe_table", "orders")),
    ("What columns does order items have?", ("describe_table", "order_items")),
    ("tell me about the regions table", ("describe_table", "regions")),
    ("What does line_total mean?", ("explain_column", "line_total")),
    ("what is line total", ("explain_column", "line_total")),
    ("Which metrics are defined?", ("metrics", None)),
    ("How is revenue defined?", ("metrics", None)),
])
def test_questions_about_the_data_are_recognised(text, intent):
    assert catalog_question(text, CAT) == intent


@pytest.mark.parametrize("text", [
    "What was revenue by region in September 2026?", "How many orders were cancelled?",
    "Show revenue by month", "List the regions", "What is our total revenue?", "Which region had the most orders?",
])
def test_data_questions_are_left_to_the_model(text):
    assert catalog_question(text, CAT) is None


# ---- answering -------------------------------------------------------------------------------------------

def test_list_of_tables():
    out = answer(("list_tables", None), CAT, METRICS)
    assert out["columns"] == ["table", "business_area", "description", "rows"]
    assert [r[0] for r in out["rows"]] == ["regions", "order_items", "orders"]     # business-area order
    assert "3 tables" in out["answer"] and out["sql"] == "" and out["answer_source"] == "catalog"


def test_describing_a_table():
    out = answer(("describe_table", "orders"), CAT, METRICS)
    assert out["columns"] == ["column", "type", "key", "description"]
    assert out["rows"][0] == ["order_id", "integer", "PK", "Order key."]
    assert "completed, cancelled" in out["rows"][1][3]
    assert "One row per order." in out["answer"] and "Revenue counts completed orders only." in out["answer"]


def test_explaining_a_column():
    out = answer(("explain_column", "line_total"), CAT, METRICS)
    assert out["rows"] == [["order_items", "line_total", "numeric", "What the customer paid for the line. (USD)"]]


def test_metrics():
    out = answer(("metrics", None), CAT, METRICS)
    assert out["columns"] == ["metric", "definition", "description"] and out["rows"][0][0] == "revenue"


def test_a_table_the_role_cannot_see_is_answered_as_unknown():
    limited = {"regions": CAT["regions"]}
    assert catalog_question("Describe the orders table", limited) == ("describe_table", "orders")
    out = answer(("describe_table", "orders"), limited, [])
    assert out["rows"] == [] and "no table called orders that you can access" in out["answer"].lower()


# ---- through /ask and /catalog ----------------------------------------------------------------------------

@pytest.fixture
def retail(monkeypatch):
    load(OWNER_URL, seed=7, scale="tiny")
    monkeypatch.setenv("DATA_SOURCE", "retail")
    schema.clear_cache()
    yield
    schema.clear_cache()
    app.dependency_overrides.pop(get_llm, None)


@pytest.mark.integration
def test_ask_answers_from_the_catalog_without_the_model(retail, audit_events):
    llm = RoutedLLM("SELECT 1")
    app.dependency_overrides[get_llm] = lambda: llm
    r = client.post("/ask", json={"message": "Show me the list of tables with description"})
    assert r.status_code == 200
    body = r.json()
    assert len(body["rows"]) == 29 and body["answer_source"] == "catalog" and llm.prompts == []
    assert audit_events[-1]["event"] == "catalog_question"


@pytest.mark.integration
def test_catalog_route_is_filtered_by_role(retail):
    from app.appdb import User
    from app.auth import current_user
    analyst = client.get("/catalog").json()
    assert analyst["source"] == "retail" and len(analyst["tables"]) == 29
    customers = next(t for t in analyst["tables"] if t["name"] == "customers")
    assert "email" not in [c["name"] for c in customers["columns"]]
    app.dependency_overrides[current_user] = lambda: User(username="bob", role="limited")
    try:
        limited = client.get("/catalog").json()
    finally:
        app.dependency_overrides[current_user] = lambda: User(username="test-analyst", role="analyst")
    names = {t["name"] for t in limited["tables"]}
    assert "orders" not in names and "products" in names
    assert all(r["table"] in names for t in limited["tables"] for r in t["referenced_by"])


def test_catalog_route_needs_sign_in():
    from app.auth import current_user
    saved = app.dependency_overrides.pop(current_user)
    try:
        assert client.get("/catalog").status_code == 401
    finally:
        app.dependency_overrides[current_user] = saved


@pytest.mark.parametrize("text", [
    "Show me sample data from the customers table", "preview the orders table",
    "show me the first 10 rows of the regions table", "give me some example rows from orders",
    "show some records from the order items table",
])
def test_requests_for_rows_go_to_the_model_not_the_catalog(text):
    assert catalog_question(text, CAT) is None
