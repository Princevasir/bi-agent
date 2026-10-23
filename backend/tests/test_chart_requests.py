"""F1c: a chart type named in the question is used when it fits; chart-only follow-ups redraw."""
from datetime import date

import pytest
from fastapi.testclient import TestClient

from app.bi import service
from app.bi.chart import apply_request, build_chart_spec, is_chart_only, requested_chart
from app.llm import get_llm
from app.main import app
from routed_llm import RoutedLLM

client = TestClient(app)
REGIONS = (["region", "revenue"], [["North", 270.0], ["South", 300.0], ["West", 240.0]])
MONTHS = (["month", "revenue"], [["2026-08", 570.0], ["2026-09", 810.0]])
REGION_SQL = "SELECT r.name AS region, SUM(o.amount) AS revenue FROM orders o JOIN regions r ON r.id = o.region_id GROUP BY r.name"


@pytest.fixture(autouse=True)
def clear_llm_override():
    yield
    app.dependency_overrides.pop(get_llm, None)


# ---- spotting a chart type in the user's words -------------------------------------------------

@pytest.mark.parametrize("text,kind", [
    ("Show revenue by region as a pie chart", "pie"),
    ("make it a donut", "donut"), ("as a doughnut chart please", "donut"),
    ("revenue by category as a treemap", "treemap"), ("show it as a tree map", "treemap"),
    ("visits to orders as a funnel", "funnel"), ("monthly change as a waterfall", "waterfall"),
    ("revenue by region and status as a stacked bar chart", "stacked_bar"),
    ("revenue by month and region as a stacked area chart", "area"),
    ("grouped bars please", "grouped_bar"), ("show a heatmap of revenue", "heatmap"),
    ("as a heat map", "heatmap"), ("sankey of region to status", "sankey"), ("spider chart", "radar"),
    ("price against quantity as a scatter plot", "scatter"), ("bubble chart", "bubble"),
    ("histogram of order amounts", "histogram"), ("box plot of order amounts", "box"),
    ("revenue by country on a map", "map"), ("purchase orders as a gantt chart", "gantt"),
    ("revenue by month as a line chart", "line"), ("show that as a line", "line"),
    ("as an area chart", "area"), ("revenue by region as a bar chart", "bar"), ("as a column chart", "bar"),
])
def test_chart_types_are_recognised(text, kind):
    assert requested_chart(text) == kind


@pytest.mark.parametrize("text", [
    "What was online revenue last month?", "How many order lines were returned?",
    "Show the product roadmap", "Revenue by region", "barbecue sales", "boxes shipped by carrier",
])
def test_ordinary_words_are_not_chart_requests(text):
    assert requested_chart(text) is None


@pytest.mark.parametrize("text,only", [
    ("make it a pie chart", True), ("as a donut", True), ("pie chart please", True),
    ("Can you show that as a line instead?", True), ("switch to a treemap", True),
    ("Show revenue by region as a pie chart", False), ("What about August as a bar chart?", False),
    ("Revenue by region", False),
])
def test_chart_only_messages(text, only):
    assert is_chart_only(text) is only


# ---- applying the request -------------------------------------------------------------------------

def test_a_request_that_fits_becomes_the_suggestion():
    spec, note = apply_request(build_chart_spec(*REGIONS), "pie")
    assert spec["type"] == "pie" and spec["options"][0] == "pie" and "bar" in spec["options"]
    assert note is None


def test_a_request_that_does_not_fit_is_explained():
    spec, note = apply_request(build_chart_spec(*MONTHS), "pie")
    assert spec["type"] == "line"
    assert note.startswith("A pie chart doesn't fit this result") and "line chart" in note


def test_no_request_changes_nothing():
    spec = build_chart_spec(*REGIONS)
    assert apply_request(spec, None) == (spec, None)


def test_a_request_when_no_chart_fits_is_explained():
    spec, note = apply_request(None, "pie")
    assert spec is None and "doesn't fit" in note


# ---- through the workflow and the API -----------------------------------------------------------

def test_answer_uses_the_requested_chart(monkeypatch):
    monkeypatch.setattr(service, "run_readonly", lambda sql, **kw: {
        "columns": REGIONS[0], "rows": REGIONS[1], "truncated": False})
    llm = RoutedLLM(REGION_SQL, answer="South led with 300.")
    out = service.answer_question("Show revenue by region as a pie chart", lambda p: llm.generate(p).text,
                                  date(2026, 10, 15))
    assert out["chart"]["type"] == "pie" and out["chart_note"] is None


@pytest.mark.integration
def test_make_it_a_donut_redraws_the_last_result_without_a_query(monkeypatch, audit_events):
    llm = RoutedLLM(REGION_SQL, answer="South led with 300.")
    app.dependency_overrides[get_llm] = lambda: llm
    first = client.post("/ask", json={"message": "Revenue by region"}).json()
    calls = len(llm.prompts)

    def no_query(*a, **kw):
        raise AssertionError("must not run a query")

    monkeypatch.setattr(service, "run_readonly", no_query)
    r = client.post("/ask", json={"message": "make it a donut", "conversation_id": first["conversation_id"]})
    assert r.status_code == 200
    body = r.json()
    assert len(llm.prompts) == calls                         # no model call
    assert body["chart"]["type"] == "donut" and body["rows"] == first["rows"] and body["sql"] == first["sql"]
    assert body["answer_source"] == "chart_change"
    assert [e["event"] for e in audit_events][-1] == "chart_change"


def test_a_chart_change_with_nothing_to_redraw_says_so(monkeypatch):
    llm = RoutedLLM("SELECT 1")
    app.dependency_overrides[get_llm] = lambda: llm
    r = client.post("/ask", json={"message": "make it a pie chart"})
    assert r.status_code == 200
    assert "no earlier result" in r.json()["answer"].lower() and llm.prompts == []
