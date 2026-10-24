import logging
import os

import psycopg
from psycopg.types.json import Jsonb

from app.privacy import redact_value

logger = logging.getLogger("bi_agent.audit")

NEVER_RECORD = {"password", "token", "access_token", "authorization"}


def _write(entry):
    url = os.getenv("APP_DATABASE_URL")
    if not url:
        raise RuntimeError("APP_DATABASE_URL is not set.")
    with psycopg.connect(url, connect_timeout=3) as conn:
        conn.execute(
            "INSERT INTO audit.events "
            "(request_id, username, role, event, status_code, detail) "
            "VALUES (%(request_id)s, %(username)s, %(role)s, %(event)s, "
            "%(status_code)s, %(detail)s)",
            {**entry, "detail": Jsonb(entry["detail"])},
        )


def record(event, *, request_id=None, username=None, role=None,
           status_code=None, **detail):
    entry = {
        "request_id": request_id,
        "username": username,
        "role": role,
        "event": event,
        "status_code": status_code,
        "detail": redact_value({k: v for k, v in detail.items() if k.lower() not in NEVER_RECORD}),   # GR-PRIV-02
    }
    try:
        _write(entry)
    except Exception:
        # Fail open: an audit outage must not block users. The failure is logged.
        logger.exception("audit_write_failed event=%s request_id=%s", event, request_id)
