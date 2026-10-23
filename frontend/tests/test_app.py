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
    "chart": {"type": "bar", "x": "region_name", "y": "revenue"}, "conversation_id": "c-1",
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
