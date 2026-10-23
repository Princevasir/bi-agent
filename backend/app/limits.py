"""Guardrail limits: the policy file sets each one, and the environment may only lower it.

Read at call time. Bad environment values fail loudly rather than silently falling back.
"""
import os

from app import policy


def _limit(env_name, key, minimum=1):
    ceiling = policy.get().sql[key]
    raw = os.getenv(env_name)
    if raw is None:
        return ceiling
    try:
        value = int(raw)
    except ValueError:
        raise ValueError(f"{env_name} must be a whole number, got {raw!r}") from None
    if value < minimum:
        raise ValueError(f"{env_name} must be at least {minimum}, got {value}")
    return min(value, ceiling)   # tighten only (GR-POL-01)


def sql_max_rows():
    """Rows returned per query (GR-SQL-04)."""
    return _limit("SQL_MAX_ROWS", "max_rows")


def sql_max_result_bytes():
    """Approximate JSON size of the rows returned per query (GR-SQL-04)."""
    return _limit("SQL_MAX_RESULT_BYTES", "max_result_bytes")


def sql_timeout_ms():
    """Statement timeout per query."""
    return _limit("SQL_TIMEOUT_MS", "timeout_ms")


def sql_max_tables():
    """Table references per query, counting repeats (GR-SQL-02)."""
    return _limit("SQL_MAX_TABLES", "max_tables")


def sql_repair_attempts():
    """Retries after a fixable SQL failure; 0 switches repair off (GR-WF-01)."""
    return _limit("SQL_REPAIR_ATTEMPTS", "repair_attempts", minimum=0)


def sql_max_depth():
    """How deeply SELECTs may be nested inside other SELECTs (GR-SQL-02)."""
    return _limit("SQL_MAX_DEPTH", "max_depth")


def workflow_max_steps():
    """Steps one question may take through the workflow, whatever the other counters say (demo gap D1)."""
    return _limit("WORKFLOW_MAX_STEPS", "max_steps")


def decline_retries():
    """Second opinions when the model declines a question that clearly mentions the data."""
    return _limit("DECLINE_RETRIES", "decline_retries", minimum=0)
