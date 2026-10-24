"""GR-PRIV-01 (no personal data to the model), GR-PRIV-02 (none in logs or audit), GR-PRIV-04 (provider data policy)."""
import json
import logging
from datetime import date

import httpx
import pytest
from fastapi.testclient import TestClient

from app import privacy
from app.agents import sql as sql_agent
from app.bi.service import answer_question
from app.db import DBQueryError
from app.llm import get_llm
from app.llm.base import LLMConfigError
from app.logging_setup import JsonFormatter
from app.main import app
from routed_llm import RoutedLLM

TODAY = date(2026, 10, 24)
CUSTOMERS = {"columns": ["customer_id", "email", "phone", "first_name", "contact", "revenue"],
             "rows": [[1, "grace.bernard.1@example.com", "+1-555-0000001", "Grace", "call (555) 123-4567", 1200.5],
                      [2, "leo.lopez.2@example.com", "+31-555-0000004", "Leo", "leo@corp.example.org", 800.0]],
             "truncated": False}


# ---- GR-PRIV-01: what the model may see ------------------------------------------------------------------

@pytest.mark.parametrize("text", ["grace.bernard.1@example.com", "write to a.b+c@mail.example.co.uk today",
                                  "+1-555-0000001", "+31 555 000 0004", "(555) 123-4567", "call 555-123-4567 now"])
def test_emails_and_phone_numbers_are_masked(text):
    masked, n = privacy.redact_text(text)
    assert n >= 1 and "[redacted]" in masked
    assert "@" not in masked and not any(ch.isdigit() for ch in masked)


@pytest.mark.parametrize("text", ["2025-01-01", "2025-01-01 10:00:00", "2025-01-01T10:00:00", "19767393.86", "FY2025",
                                  "TT-1001", "Q1 2026", "order 281682", "1,380"])
def test_dates_amounts_and_codes_are_left_alone(text):
    assert privacy.redact_text(text) == (text, 0)


def test_personal_columns_are_masked_whatever_their_values_and_numbers_stay():
    rows, n = privacy.redact_rows(CUSTOMERS["columns"], CUSTOMERS["rows"])
    assert rows[0][1] == rows[0][2] == rows[0][3] == "[redacted]"
    assert rows[0][4] == "call [redacted]" and rows[1][4] == "[redacted]"
    assert rows[0][0] == 1 and rows[0][5] == 1200.5 and n == 8


@pytest.mark.integration
def test_the_explain_prompt_never_contains_personal_data_but_the_answer_is_grounded(monkeypatch, caplog):
    monkeypatch.setattr(sql_agent, "run_readonly", lambda sql, **kw: CUSTOMERS)
    llm = RoutedLLM("SELECT * FROM orders", answer="The top customer spent 1200.5.")   # rows come from CUSTOMERS
    with caplog.at_level(logging.INFO):
        out = answer_question("Who spent the most last year?", lambda p: llm.generate(p).text, TODAY,
                              role="analyst")
    explain = [p for p in llm.prompts if p.startswith("Answer the question")]
    assert explain, [p[:60] for p in llm.prompts]
    for value in ("grace.bernard.1@example.com", "+1-555-0000001", "Grace", "555) 123-4567", "leo@corp"):
        assert value not in explain[0]
    assert out["answer_source"] == "llm" and out["rows"] == CUSTOMERS["rows"]       # the user still sees the table
    [record] = [r for r in caplog.records if r.message == "privacy_redacted"]
    assert record.count == 8 and "grace" not in json.dumps(vars(record), default=str).lower()


# ---- GR-PRIV-02: logs and audit ----------------------------------------------------------------------------

def test_json_logs_mask_personal_data_in_the_message_and_fields():
    record = logging.LogRecord("bi_agent", logging.INFO, "x", 1, "asked about grace@example.com", None, None)
    record.question = "orders for +1-555-0000001"
    record.nested = {"to": ["leo@example.com"]}
    line = JsonFormatter().format(record)
    assert "grace@example.com" not in line and "555-0000001" not in line and "leo@example.com" not in line
    assert line.count("[redacted]") == 3


def test_the_audit_trail_stores_questions_masked(audit_events):
    app.dependency_overrides[get_llm] = lambda: RoutedLLM("NO_QUERY")
    try:
        TestClient(app).post("/ask", json={"message": "hello, I am grace@example.com"})
    finally:
        app.dependency_overrides.pop(get_llm, None)
    assert "grace@example.com" not in json.dumps(audit_events)
    assert "hello, I am [redacted]" in json.dumps(audit_events)


@pytest.mark.integration
def test_database_errors_are_logged_by_class_only(monkeypatch, caplog):
    def fail(sql, **kw):
        raise DBQueryError("The query failed.", detail="x") from Exception("invalid input: 'secret-value-42'")

    monkeypatch.setattr(sql_agent, "run_readonly", fail)
    app.dependency_overrides[get_llm] = lambda: RoutedLLM("SELECT name FROM regions")
    try:
        with caplog.at_level(logging.WARNING):
            r = TestClient(app).post("/ask", json={"message": "regions"})
    finally:
        app.dependency_overrides.pop(get_llm, None)
    assert r.status_code == 422
    assert "secret-value-42" not in caplog.text
    [record] = [r for r in caplog.records if r.message == "db_error"]
    assert record.error == "DBQueryError" and "secret-value-42" not in json.dumps(vars(record), default=str)


# ---- GR-PRIV-04: what the model provider may do with prompts -----------------------------------------------

class Capture:
    def __init__(self):
        self.bodies = []

    def __call__(self, request):
        self.bodies.append(json.loads(request.content))
        return httpx.Response(200, json={"choices": [{"message": {"content": "ok"}}], "usage": {}})


@pytest.fixture
def fresh(monkeypatch):
    for name in ("LLM_PROVIDER", "LLM_FALLBACK_PROVIDER", "LLM_PROVIDER_DATA_POLICY", "GROQ_ZDR_CONFIRMED"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    monkeypatch.setenv("GROQ_API_KEY", "test-key")
    get_llm.cache_clear()
    yield
    get_llm.cache_clear()


def body_for(monkeypatch, provider, policy=None):
    monkeypatch.setenv("LLM_PROVIDER", provider)
    if policy:
        monkeypatch.setenv("LLM_PROVIDER_DATA_POLICY", policy)
    get_llm.cache_clear()
    llm, capture = get_llm(), Capture()
    inner = llm                                   # unwrap the circuit breaker and retry to the HTTP client
    while hasattr(inner, "llm"):
        inner = inner.llm
    inner.client = httpx.Client(transport=httpx.MockTransport(capture))
    llm.generate("q")
    return capture.bodies[-1]


def test_openrouter_requests_deny_data_collection_by_default(fresh, monkeypatch):
    assert body_for(monkeypatch, "openrouter")["provider"] == {"data_collection": "deny"}


def test_openrouter_can_require_zero_data_retention(fresh, monkeypatch):
    assert body_for(monkeypatch, "openrouter", "zdr")["provider"] == {"data_collection": "deny", "zdr": True}


def test_allow_sends_no_preference(fresh, monkeypatch):
    assert "provider" not in body_for(monkeypatch, "openrouter", "allow")


def test_local_and_groq_requests_carry_no_openrouter_fields(fresh, monkeypatch):
    assert "provider" not in body_for(monkeypatch, "ollama")
    assert "provider" not in body_for(monkeypatch, "groq")


def test_groq_with_zero_retention_needs_an_admin_confirmation(fresh, monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "groq")
    monkeypatch.setenv("LLM_PROVIDER_DATA_POLICY", "zdr")
    with pytest.raises(LLMConfigError, match="GROQ_ZDR_CONFIRMED"):
        get_llm()
    monkeypatch.setenv("GROQ_ZDR_CONFIRMED", "true")
    get_llm.cache_clear()
    assert get_llm()


def test_an_unknown_policy_is_refused(fresh, monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "openrouter")
    monkeypatch.setenv("LLM_PROVIDER_DATA_POLICY", "maybe")
    with pytest.raises(LLMConfigError, match="LLM_PROVIDER_DATA_POLICY"):
        get_llm()


def test_the_policy_in_force_is_logged_at_start_up(fresh, monkeypatch, caplog):
    monkeypatch.setenv("LLM_PROVIDER", "openrouter")
    with caplog.at_level(logging.INFO):
        get_llm()
    [record] = [r for r in caplog.records if r.message == "llm_data_policy"]
    assert record.provider == "openrouter" and record.policy == "deny"
