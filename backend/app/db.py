import os
from datetime import date
from decimal import Decimal

import psycopg
from psycopg import errors

from app.access import db_env_for
from app.sqltypes import TrustedSQL, ValidatedSQL


class DBError(Exception):
    """Database failure."""


class DBTimeoutError(DBError):
    """Query exceeded the time limit."""


class UnvalidatedSQLError(TypeError):
    """SQL that came neither from validate_sql nor from TrustedSQL."""


def _json_safe(v):
    if isinstance(v, Decimal):
        return float(v)
    if isinstance(v, date):
        return v.isoformat()
    return v


def run_readonly(sql, params=None, max_rows=200, timeout_ms=5000, role="analyst"):
    if not isinstance(sql, (ValidatedSQL, TrustedSQL)):
        raise UnvalidatedSQLError("run_readonly needs SQL from validate_sql or a TrustedSQL constant.")
    url = os.getenv(db_env_for(role))
    if not url:
        raise DBError("DATABASE_URL is not set.")
    try:
        with psycopg.connect(
            url, connect_timeout=5,
            options=f"-c statement_timeout={timeout_ms} -c default_transaction_read_only=on",
        ) as conn:
            with conn.cursor() as cur:
                cur.execute(sql, params)
                if cur.description is None:
                    raise DBError("The statement returned no result set.")
                columns = [c.name for c in cur.description]
                rows = cur.fetchmany(max_rows + 1)
    except errors.QueryCanceled as e:
        raise DBTimeoutError("Query timed out.") from e
    except psycopg.Error as e:
        raise DBError("Database error.") from e
    truncated = len(rows) > max_rows
    return {
        "columns": columns,
        "rows": [[_json_safe(v) for v in r] for r in rows[:max_rows]],
        "truncated": truncated,
    }