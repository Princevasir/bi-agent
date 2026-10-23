"""Demo gap D2: five specialist agents, one job each, routed by a coordinator inside the graph."""
import inspect
from datetime import date

import pytest
from fastapi.testclient import TestClient

from app import agents
from app.bi import service
from app.bi.conversation import Turn
from app.llm import get_llm
from app.main import app
from routed_llm import RoutedLLM

TODAY = date(2026, 10, 24)
SQL = "SELECT r.name AS region, SUM(o.amount) AS revenue FROM orders o JOIN regions r ON o.region_id = r.id " \
      "WHERE o.status = 'completed' GROUP BY r.name"
HISTORY = [Turn(question="Revenue by region", sql=SQL, columns=["region", "revenue"],
                rows=[["North", 520], ["South", 500], ["West", 360]], answer="North led.")]


def steps(out):
    return [(s["agent"], s["step"]) for s in out["trace"]]


def ask(question, llm, history=None):
    return service.answer_question(question, lambda p: llm.generate(p).text, TODAY, history)


# ---- the agents and their boundaries ---------------------------------------------------------------------

def test_there_are_five_agents_with_one_job_each():
    assert [a.name for a in agents.AGENTS] == ["Coordinator", "Knowledge", "SQL", "Analyst", "Chart"]
    for a in agents.AGENTS:
        assert a.job and "\n" not in a.job and len(a.job) <= 120, a.name
        assert a.steps, a.name


def test_every_graph_step_belongs_to_exactly_one_agent():
    owned = [s for a in agents.AGENTS for s in a.steps]
    assert len(owned) == len(set(owned))
    graph_nodes = set(service.build_graph(lambda p: "").get_graph().nodes) - {"__start__", "__end__"}
    assert graph_nodes == set(owned)


def test_only_the_sql_agent_touches_the_database():
    for module in (agents.coordinator, agents.knowledge, agents.analyst, agents.chart):
        source = inspect.getsource(module)
        assert "run_readonly" not in source and "validate_sql" not in source, module.__name__
    assert "run_readonly" in inspect.getsource(agents.sql)


def test_the_chart_and_knowledge_agents_never_call_the_model():
    for module in (agents.knowledge, agents.chart):
        assert "generate" not in inspect.getsource(module), module.__name__


# ---- the coordinator routes inside the graph -------------------------------------------------------------

@pytest.mark.integration
def test_a_data_question_goes_through_knowledge_sql_analyst_and_chart():
    out = ask("What was revenue by region?", RoutedLLM(SQL, answer="North was 520."))
    assert out["route"] == "data"
    assert steps(out) == [("Coordinator", "route"), ("Knowledge", "find_knowledge"), ("SQL", "write_sql"),
                          ("SQL", "check_sql"), ("SQL", "execute"), ("Analyst", "explain"),
                          ("Analyst", "ground"), ("Chart", "draw")]
    assert out["chart"]["type"] == "bar"


@pytest.mark.integration
def test_a_follow_up_is_rewritten_by_the_coordinator_first():
    llm = RoutedLLM(SQL, answer="North was 520.", rewrite="What was revenue by region in August 2026?")
    out = ask("And August?", llm, HISTORY)
    assert steps(out)[:3] == [("Coordinator", "route"), ("Coordinator", "rewrite"), ("Knowledge", "find_knowledge")]
    assert out["interpreted_as"] == "What was revenue by region in August 2026?"


def test_a_chart_change_goes_to_the_chart_agent_without_the_model():
    llm = RoutedLLM("SELECT 1")
    out = ask("make it a pie chart", llm, HISTORY)
    assert out["route"] == "chart_change" and llm.prompts == []
    assert steps(out) == [("Coordinator", "route"), ("Chart", "redraw")]
    assert out["chart"]["type"] == "pie" and out["rows"] == HISTORY[0].rows and out["sql"] == SQL
    assert out["answer_source"] == "chart_change"


def test_a_chart_change_with_nothing_to_redraw_says_so():
    out = ask("make it a pie chart", RoutedLLM("SELECT 1"))
    assert out["route"] == "chart_change" and out["rows"] == [] and "no earlier result" in out["answer"].lower()


def test_a_question_about_the_data_goes_to_the_knowledge_agent_without_the_model():
    llm = RoutedLLM("SELECT 1")
    out = ask("What tables can I see?", llm)
    assert out["route"] == "catalog" and llm.prompts == [] and out["answer_source"] == "catalog"
    assert steps(out) == [("Coordinator", "route"), ("Knowledge", "catalog_answer")]
    assert out["intent"][0] and out["rows"]


@pytest.mark.integration
def test_a_declined_message_ends_at_the_sql_agent():
    out = ask("hello there", RoutedLLM("NO_QUERY"))
    assert steps(out)[-1] == ("SQL", "declined") and out["answer"] == service.NO_QUERY_ANSWER


# ---- the API ------------------------------------------------------------------------------------------------

client = TestClient(app)


@pytest.fixture
def model():
    llm = RoutedLLM(SQL, answer="North was 520.")
    app.dependency_overrides[get_llm] = lambda: llm
    yield llm
    app.dependency_overrides.pop(get_llm, None)


@pytest.mark.integration
def test_ask_returns_the_route_and_the_trace(model):
    body = client.post("/ask", json={"message": "What was revenue by region?"}).json()
    assert body["route"] == "data" and body["trace"][0] == {"agent": "Coordinator", "step": "route"}
    again = client.post("/ask", json={"message": "make it a donut", "conversation_id": body["conversation_id"]})
    assert again.json()["route"] == "chart_change" and again.json()["chart"]["type"] == "donut"


def test_ask_answers_catalog_questions_with_a_trace(model):
    body = client.post("/ask", json={"message": "What tables can I see?"}).json()
    assert body["route"] == "catalog" and [s["agent"] for s in body["trace"]] == ["Coordinator", "Knowledge"]
