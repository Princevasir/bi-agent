import json
import logging

import pytest
from fastapi.testclient import TestClient

from app import main
from app.db import DBError
from app.logging_setup import JsonFormatter
from app.main import app

client = TestClient(app)


def test_json_formatter_writes_extras_as_keys():
    record = logging.LogRecord("bi_agent", logging.INFO, __file__, 1, "request", None, None)
    record.request_id, record.status = "abc", 200
    entry = json.loads(JsonFormatter().format(record))
    assert entry["msg"] == "request" and entry["request_id"] == "abc" and entry["status"] == 200


def test_request_log_carries_request_id(caplog):
    with caplog.at_level(logging.INFO, logger="bi_agent"):
        client.get("/health", headers={"X-Request-ID": "abc-123"})
    [rec] = [r for r in caplog.records if r.getMessage() == "request"]
    assert rec.request_id == "abc-123" and rec.status == 200 and rec.username is None


def test_not_ready_when_a_database_is_down(monkeypatch):
    def down():
        raise DBError("down")

    monkeypatch.setattr(main, "run_readonly", lambda sql: {"rows": [[1]]})
    monkeypatch.setattr(main, "appdb_ping", down)
    r = client.get("/ready")
    assert r.status_code == 503
    assert r.json()["checks"] == {"analytics": "ok", "appdb": "unavailable"}


@pytest.mark.integration
def test_ready_when_both_databases_answer():
    r = client.get("/ready")
    assert r.status_code == 200 and r.json()["status"] == "ready"
