import json
import os
from datetime import date
from decimal import Decimal

import psycopg
from psycopg import errors

from app import limits
from app.access import db_env_for
from app.sqltypes import TrustedSQL, ValidatedSQL


class DBError(Exception):
    """Database failure."""


class DBTimeoutError(DBError):
    """Query exceeded the time limit."""


class ResultTooLargeError(DBError):
    """A single result row is over the byte limit."""


class UnvalidatedSQLError(TypeError):
    """SQL that came neither from validate_sql nor from TrustedSQL."""


def _json_safe(v):
    if isinstance(v, Decimal):
        return float(v)
    if isinstance(v, date):
        return v.isoformat()
    return v


FETCH_BATCH = 50


def run_readonly(sql, params=None, max_rows=None, timeout_ms=None, role="analyst", max_bytes=None):
    """Run read-only SQL as the role's login and return at most max_rows rows and about max_bytes of JSON.

    A server-side cursor is read in small batches, so rows past the limits are never sent by
    Postgres, and often never computed (GR-SQL-04).
    """
    if not isinstance(sql, (ValidatedSQL, TrustedSQL)):
        raise UnvalidatedSQLError("run_readonly needs SQL from validate_sql or a TrustedSQL constant.")
    max_rows = max_rows or limits.sql_max_rows()
    max_bytes = max_bytes or limits.sql_max_result_bytes()
    timeout_ms = timeout_ms or limits.sql_timeout_ms()
    url = os.getenv(db_env_for(role))
    if not url:
        raise DBError("DATABASE_URL is not set.")
    rows, size, truncated = [], 2, False   # 2: the brackets of the JSON list
    try:
        with psycopg.connect(
            url, connect_timeout=5,
            options=f"-c statement_timeout={timeout_ms} -c default_transaction_read_only=on",
        ) as conn:
            with conn.cursor(name="bi_result") as cur:
                cur.execute(sql, params)
                if cur.description is None:
                    raise DBError("The statement returned no result set.")
                columns = [c.name for c in cur.description]
                while not truncated:
                    batch = cur.fetchmany(min(FETCH_BATCH, max_rows + 1 - len(rows)))
                    if not batch:
                        break
                    for raw in batch:
                        row = [_json_safe(v) for v in raw]
                        row_size = len(json.dumps(row, default=str)) + (2 if rows else 0)
                        if len(rows) == max_rows or size + row_size > max_bytes:
                            if not rows:
                                raise ResultTooLargeError("A single row is over the byte limit.")
                            truncated = True
                            break
                        rows.append(row)
                        size += row_size
    except errors.QueryCanceled as e:
        raise DBTimeoutError("Query timed out.") from e
    except psycopg.Error as e:
        raise DBError("Database error.") from e
    return {"columns": columns, "rows": rows, "truncated": truncated}
