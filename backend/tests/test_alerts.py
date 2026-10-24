"""GR-OBS-02: alerts from the audit trail (the local equivalent of the planned CloudWatch alarms)."""
from datetime import datetime, timedelta, timezone

import psycopg
import pytest
from fastapi.testclient import TestClient

from app import alerts, audit, main
from app.main import app

NOW = datetime(2026, 10, 24, 12, 0, tzinfo=timezone.utc)
READER = "postgresql://audit_reader:audit_reader_dev_pw@localhost:5433/appdb"


def ev(minutes_ago, event, username="alice", **detail):
    return {"ts": NOW - timedelta(minutes=minutes_ago), "username": username, "event": event, "detail": detail}


def kinds(found):
    return sorted(a["rule"] for a in found)


def test_quiet_means_no_alerts():
    assert alerts.evaluate([ev(1, "ask"), ev(2, "login_success")], tokens_last_day=1000, now=NOW) == []


def test_five_access_denials_by_one_user_in_ten_minutes():
    denials = [ev(1, "access_denied"), ev(2, "sql_rejected", category="table"),
               ev(3, "sql_rejected", category="personal_data"), ev(4, "export_denied"),
               ev(5, "db_error", error="DBAccessError")]
    found = alerts.evaluate(denials, tokens_last_day=0, now=NOW)
    assert kinds(found) == ["access_denials"] and "alice" in found[0]["message"]


def test_denials_spread_out_or_across_users_do_not_alert():
    spread = [ev(m, "access_denied") for m in (1, 8, 15, 22, 29)]
    users = [ev(1, "access_denied", username=f"u{i}") for i in range(5)]
    assert alerts.evaluate(spread + users, tokens_last_day=0, now=NOW) == []


def test_any_server_error_alerts():
    assert kinds(alerts.evaluate([ev(3, "server_error", error="RuntimeError")], 0, NOW)) == ["server_errors"]


def test_a_spike_of_cost_rejections_alerts():
    spike = [ev(m, "sql_rejected", guardrail="GR-SQL-03", username=f"u{m}") for m in range(0, 50, 5)]
    assert kinds(alerts.evaluate(spike, 0, NOW)) == ["cost_rejections"]
    assert alerts.evaluate(spike[:9], 0, NOW) == []


def test_token_spend_over_the_daily_limit_alerts():
    assert kinds(alerts.evaluate([], tokens_last_day=2_000_001, now=NOW)) == ["daily_tokens"]


def test_thresholds_come_from_the_environment(monkeypatch):
    monkeypatch.setenv("ALERT_DAILY_TOKENS", "100")
    assert kinds(alerts.evaluate([], tokens_last_day=101, now=NOW)) == ["daily_tokens"]


def test_the_command_prints_alerts_and_exits_1(monkeypatch, capsys):
    monkeypatch.setenv("ALERTS_DATABASE_URL", "postgresql://x/y")
    monkeypatch.setattr(audit, "recent_events", lambda url, since: [ev(1, "server_error", error="RuntimeError")])
    monkeypatch.setattr(audit, "tokens_since", lambda url, since: 0)
    assert alerts.main([]) == 1 and "server_errors" in capsys.readouterr().out
    monkeypatch.setattr(audit, "recent_events", lambda url, since: [])
    assert alerts.main([]) == 0 and "no alerts" in capsys.readouterr().out


def test_the_command_needs_its_own_login(monkeypatch):
    monkeypatch.delenv("ALERTS_DATABASE_URL", raising=False)
    with pytest.raises(SystemExit, match="ALERTS_DATABASE_URL"):
        alerts.main([])


# ---- unexpected errors are recorded, never shown -------------------------------------------------------------

def test_an_unexpected_error_is_a_plain_500_and_audited(monkeypatch, audit_events):
    def boom(*a, **kw):
        raise RuntimeError("secret internal detail")
    monkeypatch.setattr(main, "answer_question", boom)
    r = TestClient(app, raise_server_exceptions=False).post("/ask", json={"message": "anything"})
    assert r.status_code == 500 and r.json() == {"detail": "Something went wrong. Please try again."}
    assert audit_events[-1]["event"] == "server_error" and audit_events[-1]["detail"]["error"] == "RuntimeError"
    assert "secret internal detail" not in str(audit_events[-1])


# ---- the reader login ---------------------------------------------------------------------------------------------

@pytest.mark.integration
def test_the_reader_reads_the_audit_trail_and_nothing_else():
    since = datetime.now(timezone.utc) - timedelta(days=3650)
    assert isinstance(audit.recent_events(READER, since), list)
    assert audit.tokens_since(READER, since) >= 0
    with psycopg.connect(READER) as conn:
        for sql in ("SELECT * FROM users", "INSERT INTO audit.events (event) VALUES ('x')",
                    "DELETE FROM token_usage"):
            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                conn.execute(sql)
            conn.rollback()
