import pytest

from app.db import DBError, DBTimeoutError, run_readonly


@pytest.mark.integration
def test_write_is_rejected_and_data_unchanged():
    with pytest.raises(DBError):
        run_readonly("INSERT INTO orders VALUES (99, '2026-10-01', 1, 'completed', 1.00)")
    assert run_readonly("SELECT count(*) FROM orders")["rows"] == [[12]]


@pytest.mark.integration
def test_forbidden_table_is_rejected():
    with pytest.raises(DBError):
        run_readonly("SELECT * FROM internal_notes")


@pytest.mark.integration
def test_slow_query_times_out():
    with pytest.raises(DBTimeoutError):
        run_readonly("SELECT pg_sleep(2)", timeout_ms=500)


@pytest.mark.integration
def test_row_cap_truncates():
    result = run_readonly("SELECT generate_series(1, 1000)", max_rows=5)
    assert len(result["rows"]) == 5
    assert result["truncated"] is True