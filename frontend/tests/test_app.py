"""F1: the real Streamlit app, driven by AppTest with the backend replaced by stand-ins."""
import tomllib
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

import client
from client import BackendError

FRONTEND = Path(__file__).resolve().parents[1]
REGIONS = {
    "question": "Revenue by region in September 2026?", "interpreted_as": "Revenue by region in September 2026?",
    "sql": "SELECT r.name AS region_name, SUM(o.amount) AS revenue FROM orders o JOIN regions r ON r.id = o.region_id GROUP BY 1",
    "columns": ["region_name", "revenue"], "rows": [["North", 270], ["South", 300], ["West", 240]],
    "truncated": False, "answer": "South led with 300.", "answer_source": "model",
    "chart": {"type": "bar", "options": ["bar", "pie", "donut", "treemap"], "x": "region_name", "y": "revenue"},
    "conversation_id": "c-1",
}
SINGLE = {**REGIONS, "sql": "SELECT SUM(amount) AS revenue FROM orders", "columns": ["revenue"],
          "rows": [[810.0]], "answer": "Revenue was 810.", "chart": None}
DECLINED = {**REGIONS, "sql": "", "columns": [], "rows": [], "chart": None,
            "answer": "I can only answer questions about the data you have access to, and I can't change data."}
NO_DATA = {**REGIONS, "columns": ["revenue"], "rows": [], "chart": None, "answer": "No matching data was found."}


class Backend:
    """Records calls; answers with a canned result or raises."""

    def __init__(self, result=REGIONS):
        self.result, self.calls = result, []

    def post_json(self, path, payload, timeout=90.0, token=None):
        self.calls.append((path, payload, token))
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


@pytest.fixture
def backend(monkeypatch):
    b = Backend()
    monkeypatch.setattr(client, "post_json", b.post_json)
    monkeypatch.setattr(client, "login", lambda u, p: {"access_token": "tok", "role": "analyst"})
    return b


def signed_in_app():
    at = AppTest.from_file(str(FRONTEND / "app.py"), default_timeout=20)
    at.session_state["token"], at.session_state["role"], at.session_state["username"] = "tok", "analyst", "alice"
    return at.run()


def all_text(at):
    return " ".join(str(e.value) for kind in ("markdown", "caption", "title", "header", "subheader")
                    for e in getattr(at, kind))


# ---- sign-in -------------------------------------------------------------------------

def test_sign_in_page_has_a_pitch_and_no_chat(backend):
    at = AppTest.from_file(str(FRONTEND / "app.py"), default_timeout=20).run()
    assert not at.exception
    assert [t.label for t in at.text_input] == ["Username", "Password"]
    assert "Ask questions about your business data" in all_text(at)
    assert len(at.chat_input) == 0


def test_signing_in_shows_the_welcome_screen(backend):
    at = AppTest.from_file(str(FRONTEND / "app.py"), default_timeout=20).run()
    at.text_input[0].input("alice")
    at.text_input[1].input("correct horse battery")
    at.button[0].click().run()
    assert at.session_state["token"] == "tok"
    assert "What would you like to know?" in all_text(at)
    assert len([b for b in at.button if b.key and b.key.startswith("example-")]) >= 3


def test_sidebar_shows_user_and_role(backend):
    at = signed_in_app()
    sidebar = " ".join(str(e.value) for e in at.sidebar.markdown)
    assert "alice" in sidebar and "analyst" in sidebar.lower()


# ---- asking ---------------------------------------------------------------------------

def test_an_example_question_is_sent_to_the_backend(backend):
    at = signed_in_app()
    example = next(b for b in at.button if b.key and b.key.startswith("example-"))
    example.click().run()
    assert not at.exception
    [(path, payload, token)] = backend.calls
    assert path == "/ask" and payload["message"] == example.label and token == "tok"


def test_answer_has_headline_tabs_and_a_plotly_chart(backend):
    at = signed_in_app()
    at.chat_input[0].set_value("Revenue by region in September 2026?").run()
    assert not at.exception
    assert "South led with 300." in all_text(at)
    assert [t.label for t in at.tabs] == ["📊 Chart", "🧾 Table", "🧩 SQL"]
    assert len(at.get("plotly_chart")) == 1
    assert len(at.dataframe) == 1


def test_single_value_gets_a_big_number_card(backend):
    backend.result = SINGLE
    at = signed_in_app()
    at.chat_input[0].set_value("What was revenue in September 2026?").run()
    [metric] = at.metric
    assert (metric.label, metric.value) == ("Revenue", "810")
    assert "📊 Chart" not in [t.label for t in at.tabs]


def test_declined_question_is_shown_as_a_friendly_note(backend):
    backend.result = DECLINED
    at = signed_in_app()
    at.chat_input[0].set_value("hello").run()
    assert any("I can only answer" in str(i.value) for i in at.info)
    assert len(at.tabs) == 0


def test_no_data_is_shown_as_a_friendly_note(backend):
    backend.result = NO_DATA
    at = signed_in_app()
    at.chat_input[0].set_value("Revenue in April 2026?").run()
    assert any("No matching data was found." in str(i.value) for i in at.info)


def test_too_broad_query_is_a_warning_not_a_crash(backend):
    backend.result = BackendError("The generated query was too broad to run safely. Try a more specific question.", 422)
    at = signed_in_app()
    at.chat_input[0].set_value("count everything").run()
    assert not at.exception
    assert any("too broad" in str(w.value) for w in at.warning)


def test_model_unavailable_is_an_error(backend):
    backend.result = BackendError("The language model is unavailable.", 503)
    at = signed_in_app()
    at.chat_input[0].set_value("Revenue?").run()
    assert any("unavailable" in str(e.value) for e in at.error)


def test_an_expired_session_signs_out(backend):
    backend.result = BackendError("Not authenticated", 401)
    at = signed_in_app()
    at.chat_input[0].set_value("Revenue?").run()
    assert at.session_state["token"] is None
    assert any("session expired" in str(w.value).lower() for w in at.warning)


def test_history_is_shown_again_after_a_rerun(backend):
    at = signed_in_app()
    at.chat_input[0].set_value("Revenue by region in September 2026?").run()
    at.run()
    assert "South led with 300." in all_text(at)
    assert len(at.get("plotly_chart")) == 1


# ---- sidebar actions -----------------------------------------------------------------------

def test_sign_out_returns_to_the_sign_in_page(backend):
    at = signed_in_app()
    at.button(key="sign-out").click().run()
    assert at.session_state["token"] is None
    assert [t.label for t in at.text_input] == ["Username", "Password"]


def test_new_conversation_clears_the_chat(backend):
    at = signed_in_app()
    at.chat_input[0].set_value("Revenue by region in September 2026?").run()
    at.button(key="new-conversation").click().run()
    assert at.session_state["messages"] == [] and at.session_state["conversation_id"] is None
    assert "What would you like to know?" in all_text(at)


# ---- theme -------------------------------------------------------------------------------------

def test_theme_and_privacy_settings():
    config = tomllib.loads((FRONTEND / ".streamlit" / "config.toml").read_text())
    assert config["theme"]["primaryColor"]
    assert config["browser"]["gatherUsageStats"] is False


def test_earlier_answers_are_drawn_before_a_new_question_is_sent(backend, monkeypatch):
    """Streamlit fades whatever it has not redrawn yet; history must be redrawn before the slow call."""
    import streamlit as st
    at = signed_in_app()
    at.chat_input[0].set_value("Revenue by region in September 2026?").run()
    seen = {}
    real = backend.post_json

    def post_json(path, payload, timeout=90.0, token=None):
        seen["charts_already_drawn"] = st.session_state.get("_charts_drawn", 0)
        return real(path, payload, timeout, token)

    monkeypatch.setattr(client, "post_json", post_json)
    at.chat_input[0].set_value("Show revenue by month").run()
    assert seen["charts_already_drawn"] == 1


def test_the_product_is_called_bi_agent_not_the_demo_company(backend):
    for at in (AppTest.from_file(str(FRONTEND / "app.py"), default_timeout=20).run(), signed_in_app()):
        text = all_text(at) + " ".join(str(e.value) for e in at.sidebar.markdown)
        assert "BI Agent" in text and "Trailhead" not in text



# ---- F1b: chart-type selector ---------------------------------------------------------------------

def chart_json(at):
    return at.get("plotly_chart")[0].proto.spec


def test_selector_offers_only_the_chart_types_that_fit(backend):
    at = signed_in_app()
    at.chat_input[0].set_value("Revenue by region in September 2026?").run()
    [selector] = at.selectbox
    assert selector.label == "Chart type"
    assert selector.options == ["Bar", "Pie", "Donut", "Treemap"]
    assert selector.value == "bar" and '"type":"bar"' in chart_json(at)


def test_switching_the_chart_type_redraws_it(backend):
    at = signed_in_app()
    at.chat_input[0].set_value("Revenue by region in September 2026?").run()
    at.selectbox[0].set_value("pie").run()
    assert not at.exception
    assert '"type":"pie"' in chart_json(at)


def test_no_selector_when_only_one_chart_fits(backend):
    backend.result = {**REGIONS, "columns": ["price", "quantity"], "rows": [[1.0, 2.0], [2.0, 3.0], [3.0, 5.0]],
                      "chart": {"type": "scatter", "options": ["scatter"], "x": "price", "y": "quantity"}}
    at = signed_in_app()
    at.chat_input[0].set_value("Price against quantity").run()
    assert len(at.selectbox) == 0 and len(at.get("plotly_chart")) == 1


# ---- F1c: requested chart types --------------------------------------------------------------------

def test_requested_chart_is_shown_first(backend):
    backend.result = {**REGIONS, "chart": {**REGIONS["chart"], "type": "pie",
                                           "options": ["pie", "bar", "donut", "treemap"]}}
    at = signed_in_app()
    at.chat_input[0].set_value("Revenue by region as a pie chart").run()
    assert at.selectbox[0].value == "pie" and '"type":"pie"' in chart_json(at)


def test_a_request_that_does_not_fit_shows_why(backend):
    note = "A pie chart doesn't fit this result: it needs one category and one number. Showing a line chart instead."
    backend.result = {**REGIONS, "columns": ["month", "revenue"], "rows": [["2026-08", 570.0], ["2026-09", 810.0]],
                      "chart": {"type": "line", "options": ["line", "area", "bar"], "x": "month", "y": "revenue"},
                      "chart_note": note}
    at = signed_in_app()
    at.chat_input[0].set_value("Revenue by month as a pie chart").run()
    assert any(note in str(i.value) for i in at.info)


# ---- M29c: answers about the data and the Data catalog page ---------------------------------------------

CATALOG = {"source": "retail", "metrics": [{"name": "revenue", "definition": "SUM(order_items.line_total)",
                                             "description": "Money paid for completed orders."}],
           "tables": [
               {"name": "orders", "domain": "Sales", "description": "Customer orders.", "grain": "One row per order.",
                "caveats": ["Revenue counts completed orders only."], "primary_key": ["order_id"],
                "foreign_keys": [{"column": "customer_id", "table": "customers", "references": "customer_id"}],
                "referenced_by": [{"table": "order_items", "column": "order_id"}], "rows": 281682,
                "columns": [{"name": "order_id", "type": "integer", "nullable": False, "primary_key": True,
                             "references": None, "description": "Order key.", "values": [], "unit": "", "pii": False}]},
               {"name": "regions", "domain": "Geography", "description": "Sales regions.", "grain": "One row per region.",
                "caveats": [], "primary_key": ["region_id"], "foreign_keys": [], "referenced_by": [], "rows": 3,
                "columns": [{"name": "region_id", "type": "integer", "nullable": False, "primary_key": True,
                             "references": None, "description": "Region key.", "values": [], "unit": "", "pii": False}]},
           ]}
TABLE_LIST = {**REGIONS, "sql": "", "chart": None, "answer_source": "catalog",
              "columns": ["table", "business_area", "description", "rows"],
              "rows": [["regions", "Geography", "Sales regions.", 3], ["orders", "Sales", "Customer orders.", 281682]],
              "answer": "You can query 2 tables in 2 business areas."}


@pytest.fixture
def with_catalog(backend, monkeypatch):
    calls = []

    def get_json(path, timeout=5.0, token=None):
        calls.append((path, token))
        return CATALOG

    monkeypatch.setattr(client, "get_json", get_json)
    return calls


def test_a_catalog_answer_shows_the_table_and_no_sql_tab(backend):
    backend.result = TABLE_LIST
    at = signed_in_app()
    at.chat_input[0].set_value("Show me the list of tables").run()
    assert [t.label for t in at.tabs] == ["🧾 Table"]
    assert "You can query 2 tables" in all_text(at)


def test_an_answer_with_no_rows_and_no_sql_is_a_note(backend):
    backend.result = {**TABLE_LIST, "columns": [], "rows": [],
                      "answer": "There is no table called orders that you can access."}
    at = signed_in_app()
    at.chat_input[0].set_value("Describe the orders table").run()
    assert any("no table called orders" in str(i.value) for i in at.info) and len(at.tabs) == 0


def test_the_data_catalog_page_lists_the_tables(with_catalog):
    at = signed_in_app()
    at.sidebar.radio(key="view").set_value("Data catalog").run()
    assert not at.exception
    assert with_catalog == [("/catalog", "tok")]
    titles = [e.label for e in at.expander]
    assert any("orders" in t for t in titles) and any("regions" in t for t in titles)
    assert any("Customer orders." in t for t in titles)                 # the description is in the title
    assert "Revenue counts completed orders only." in all_text(at)


def test_the_catalog_can_be_searched_and_filtered(with_catalog):
    at = signed_in_app()
    at.sidebar.radio(key="view").set_value("Data catalog").run()
    tables = lambda: [e.label for e in at.expander if e.label != "Governed metrics"]
    at.text_input(key="catalog-search").input("region").run()
    assert len(tables()) == 1 and tables()[0].startswith("regions")
    at.text_input(key="catalog-search").input("").run()
    at.selectbox(key="catalog-area").set_value("Sales").run()
    assert len(tables()) == 1 and tables()[0].startswith("orders")


def test_ask_about_a_table_switches_to_the_chat(with_catalog, backend):
    backend.result = TABLE_LIST
    at = signed_in_app()
    at.sidebar.radio(key="view").set_value("Data catalog").run()
    at.button(key="ask-orders").click().run()
    assert at.session_state["view"] == "Chat"
    assert backend.calls[-1][1]["message"] == "Describe the orders table"


# ---- D3: sources and "How I answered" ------------------------------------------------------------------

TRACE = [{"agent": "Coordinator", "step": "route", "ms": 0.4}, {"agent": "Knowledge", "step": "find_knowledge", "ms": 61},
         {"agent": "SQL", "step": "write_sql", "ms": 18234}, {"agent": "SQL", "step": "check_sql", "ms": 3},
         {"agent": "SQL", "step": "execute", "ms": 412}, {"agent": "Analyst", "step": "explain", "ms": 9120},
         {"agent": "Analyst", "step": "ground", "ms": 0.2}, {"agent": "Chart", "step": "draw", "ms": 0.3}]
WITH_KNOWLEDGE = {**REGIONS, "route": "data", "trace": TRACE, "sources": [
    {"document_id": "sql-revenue-by-region", "title": "Revenue by region", "doc_type": "sql_example",
     "owner": "Sales Analytics", "version": 1, "score": 0.8}]}


def ask_with(backend, result, question="Revenue by region in September 2026?"):
    backend.result = result
    at = signed_in_app()
    return at.chat_input[0].set_value(question).run()


def test_an_answer_lists_its_sources(backend):
    at = ask_with(backend, WITH_KNOWLEDGE)
    assert not at.exception
    assert "Sources: Revenue by region (SQL example, v1)" in all_text(at)


def test_how_i_answered_shows_each_agent_step_and_the_time(backend):
    at = ask_with(backend, WITH_KNOWLEDGE)
    [panel] = [e for e in at.expander if e.label.startswith("How I answered")]
    assert "27.8 s" in panel.label
    text = " ".join(str(m.value) for m in panel.markdown)
    for agent in ("Coordinator", "Knowledge", "SQL", "Analyst", "Chart"):
        assert agent in text
    assert "Wrote the SQL query" in text and "18.2 s" in text


def test_a_declined_message_also_shows_how_it_was_handled(backend):
    trace = [{"agent": "Coordinator", "step": "route", "ms": 0.1}, {"agent": "Knowledge", "step": "find_knowledge", "ms": 1},
             {"agent": "SQL", "step": "write_sql", "ms": 900}, {"agent": "SQL", "step": "declined", "ms": 0.1}]
    at = ask_with(backend, {**DECLINED, "trace": trace, "sources": []}, "hello")
    assert any(e.label.startswith("How I answered") for e in at.expander)


def test_older_answers_without_sources_or_trace_show_neither(backend):
    at = ask_with(backend, REGIONS)
    assert not at.exception and "Sources:" not in all_text(at)
    assert not any(e.label.startswith("How I answered") for e in at.expander)
