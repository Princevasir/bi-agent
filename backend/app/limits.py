"""Guardrail limits, read from the environment at call time so one place controls them.

Bad values fail loudly rather than silently falling back to a default.
"""
import os


def _positive_int(name, default):
    raw = os.getenv(name, str(default))
    try:
        value = int(raw)
    except ValueError:
        raise ValueError(f"{name} must be a whole number, got {raw!r}") from None
    if value <= 0:
        raise ValueError(f"{name} must be greater than 0, got {value}")
    return value


def sql_max_rows():
    """Rows returned per query (GR-SQL-04)."""
    return _positive_int("SQL_MAX_ROWS", 200)


def sql_max_result_bytes():
    """Approximate JSON size of the rows returned per query (GR-SQL-04)."""
    return _positive_int("SQL_MAX_RESULT_BYTES", 1_000_000)


def sql_timeout_ms():
    """Statement timeout per query."""
    return _positive_int("SQL_TIMEOUT_MS", 5000)
