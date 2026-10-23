from datetime import date

import pytest
from fastapi.testclient import TestClient

from app.bi.text_to_sql import build_prompt, extract_sql
from app.db import TrustedSQL, run_readonly
from app.llm import get_llm
from app.llm.base import LLMResult
from app.main import app

client = TestClient(app)


class ScriptedLLM:
    def __init__(self, text):
        self.text = text
        self.prompts = []

    def generate(self, prompt):
        self.prompts.append(prompt)
        return LLMResult(text=self.text, input_tokens=1, output_tokens=1)


@pytest.fixture(autouse=True)
def clear_overrides():
    yield
    app.dependency_overrides.clear()


def test_extract_sql_from_fenced_block():
    assert extract_sql("Here you go:\n```sql\nSELECT 1\n```\nDone") == "SELECT 1"


def test_extract_sql_plain_text_is_trimmed():
    assert extract_sql("  SELECT 1  \n") == "SELECT 1"


@pytest.mark.integration
def test_prompt_contains_schema_metrics_and_date():
    prompt = build_prompt("How many orders?", date(2026, 10, 19))
    for expected in ("orders", "regions", "revenue", "order_count", "2026-10-19", "How many orders?"):
        assert expected in prompt
    assert "internal_notes" not in prompt


@pytest.mark.integration
def test_ask_sql_rejects_unsafe_sql_without_executing_it():
    llm = ScriptedLLM("```sql\nDROP TABLE orders\n```")
    app.dependency_overrides[get_llm] = lambda: llm
    r = client.post("/ask/sql", json={"message": "drop everything"})
    assert r.status_code == 422  # GR-SQL-06: /ask/sql validates like /ask
    assert r.json() == {"detail": "The generated query was rejected."}
    assert len(llm.prompts) == 1
    assert run_readonly(TrustedSQL("SELECT count(*) FROM orders"))["rows"] == [[12]]

def test_prompt_says_chart_requests_are_data_questions():
    from datetime import date as _date
    from app.bi.text_to_sql import build_prompt as _build
    import app.bi.text_to_sql as t2s
    original = t2s.schema_text
    t2s.schema_text = lambda role="analyst": "orders(id integer)"
    try:
        prompt = _build("revenue by quarter", _date(2026, 10, 15))
    finally:
        t2s.schema_text = original
    assert "Requests to draw, chart or plot data are questions about this data" in prompt


def test_answer_prompt_says_the_chart_is_drawn_automatically():
    from app.bi.grounding import answer_prompt
    p = answer_prompt("pie chart of revenue by quarter", "SELECT 1", {"columns": ["q"], "rows": [[1]], "truncated": False})
    assert "drawn automatically" in p
