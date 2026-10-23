"""GR-SQL-04: results are read in bounded batches, never loaded whole, and capped in bytes."""
import json

import pytest
from fastapi.testclient import TestClient

from app import limits
from app.bi import service
from app.db import ResultTooLargeError, TrustedSQL, run_readonly
from app.llm import get_llm
from app.main import app
from routed_llm import RoutedLLM

client = TestClient(app)

# Rows after the first 1,000 raise "division by zero". Loading the whole result fails;
# reading only the first rows never computes the failing ones. The divisor depends on the row:
# a constant 1 / 0 would be evaluated while Postgres plans the query and fail either way.
POISONED_AFTER_1000 = TrustedSQL(
    "SELECT CASE WHEN g > 1000 THEN 1 / (g - g) ELSE g END AS n FROM generate_series(1, 100000) AS g")


@pytest.fixture(autouse=True)
def clear_llm_override():
    yield
    app.dependency_overrides.pop(get_llm, None)


@pytest.mark.integration
def test_rows_beyond_the_cap_are_never_read():
    out = run_readonly(POISONED_AFTER_1000, max_rows=200)
    assert len(out["rows"]) == 200 and out["truncated"] is True
    assert out["rows"][0] == [1] and out["rows"][-1] == [200]


@pytest.mark.integration
def test_a_result_that_fits_is_not_truncated():
    out = run_readonly(TrustedSQL("SELECT g FROM generate_series(1, 200) AS g"), max_rows=200)
    assert len(out["rows"]) == 200 and out["truncated"] is False


@pytest.mark.integration
def test_results_are_cut_at_the_byte_limit():
    out = run_readonly(TrustedSQL("SELECT repeat('x', 1000) AS s FROM generate_series(1, 150)"),
                       max_rows=200, max_bytes=50_000)
    assert out["truncated"] is True
    assert 0 < len(out["rows"]) < 150
    assert len(json.dumps(out["rows"])) <= 50_000


@pytest.mark.integration
def test_a_single_row_over_the_byte_limit_is_refused():
    with pytest.raises(ResultTooLargeError):
        run_readonly(TrustedSQL("SELECT repeat('x', 200000) AS s"), max_bytes=100_000)


@pytest.mark.integration
def test_limits_come_from_the_environment(monkeypatch):
    monkeypatch.setenv("SQL_MAX_ROWS", "5")
    out = run_readonly(TrustedSQL("SELECT g FROM generate_series(1, 50) AS g"))
    assert len(out["rows"]) == 5 and out["truncated"] is True


def test_limit_defaults_and_bad_values(monkeypatch):
    for name in ("SQL_MAX_ROWS", "SQL_MAX_RESULT_BYTES", "SQL_TIMEOUT_MS"):
        monkeypatch.delenv(name, raising=False)
    assert (limits.sql_max_rows(), limits.sql_max_result_bytes(), limits.sql_timeout_ms()) == \
        (200, 1_000_000, 5000)
    monkeypatch.setenv("SQL_MAX_ROWS", "0")
    with pytest.raises(ValueError):
        limits.sql_max_rows()
    monkeypatch.setenv("SQL_MAX_ROWS", "lots")
    with pytest.raises(ValueError):
        limits.sql_max_rows()


def test_too_large_result_gets_a_clear_message(monkeypatch, audit_events):
    def too_large(sql, **kw):
        raise ResultTooLargeError("one row is over the byte limit")

    monkeypatch.setattr(service, "run_readonly", too_large)
    app.dependency_overrides[get_llm] = lambda: RoutedLLM("SELECT name FROM regions")
    r = client.post("/ask", json={"message": "list regions"})
    assert r.status_code == 422
    assert r.json() == {"detail": "The result is too large to show. Try a narrower question."}
    assert [e["event"] for e in audit_events] == ["result_too_large"]
