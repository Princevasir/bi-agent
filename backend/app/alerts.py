"""Alerts from the audit trail (GR-OBS-02): the local stand-in for the planned CloudWatch alarms (M26).

Rules, each with a threshold an operator can change through the environment:
  access_denials   ALERT_DENIALS (5) denials by one user within 10 minutes
  server_errors    any unexpected server error within the last 10 minutes
  cost_rejections  ALERT_COST_REJECTIONS (10) GR-SQL-03 rejections within an hour
  daily_tokens     more than ALERT_DAILY_TOKENS (2,000,000) model tokens in 24 hours
Prints each alert and exits 1 if any fired, so a scheduler (cron, a CI job) can act on it. Reads with
the read-only audit_reader login (ALERTS_DATABASE_URL, db/init/11_audit_reader.sql).

    ALERTS_DATABASE_URL=postgresql://audit_reader:...@localhost:5433/appdb python -m app.alerts
"""
import os
import sys
from collections import defaultdict
from datetime import datetime, timedelta, timezone

from app import audit

TEN_MINUTES, HOUR, DAY = timedelta(minutes=10), timedelta(hours=1), timedelta(days=1)


def _setting(name, default):
    return int(os.getenv(name, default))


def _is_denial(e):
    d = e["detail"]
    return (e["event"] in ("access_denied", "export_denied")
            or (e["event"] == "sql_rejected" and d.get("category") in ("table", "personal_data"))
            or (e["event"] == "db_error" and d.get("error") == "DBAccessError"))


def evaluate(events, tokens_last_day, now):
    """The alerts that fire for these events (any order) and the last day's token spend."""
    found = []
    denials = _setting("ALERT_DENIALS", 5)
    by_user = defaultdict(list)
    for e in events:
        if _is_denial(e):
            by_user[e["username"]].append(e["ts"])
    for user, times in by_user.items():
        times.sort()
        if any(times[i + denials - 1] - times[i] <= TEN_MINUTES for i in range(len(times) - denials + 1)):
            found.append({"rule": "access_denials", "message": f"{user}: {len(times)} access denials, "
                                                                f"{denials} or more within 10 minutes"})
    errors = [e for e in events if e["event"] == "server_error" and now - e["ts"] <= TEN_MINUTES]
    if errors:
        found.append({"rule": "server_errors", "message": f"{len(errors)} unexpected server errors in 10 minutes"})
    cost = [e for e in events if e["detail"].get("guardrail") == "GR-SQL-03" and now - e["ts"] <= HOUR]
    if len(cost) >= _setting("ALERT_COST_REJECTIONS", 10):
        found.append({"rule": "cost_rejections", "message": f"{len(cost)} cost rejections in the last hour"})
    limit = _setting("ALERT_DAILY_TOKENS", 2_000_000)
    if tokens_last_day > limit:
        found.append({"rule": "daily_tokens", "message": f"{tokens_last_day:,} tokens in 24 hours (limit {limit:,})"})
    return found


def main(argv=None):
    url = os.getenv("ALERTS_DATABASE_URL")
    if not url:
        raise SystemExit("Set ALERTS_DATABASE_URL to the audit_reader login (db/init/11_audit_reader.sql).")
    now = datetime.now(timezone.utc)
    found = evaluate(audit.recent_events(url, now - DAY), audit.tokens_since(url, now - DAY), now)
    for a in found:
        print(f"ALERT {a['rule']}: {a['message']}")
    if not found:
        print("no alerts")
    return 1 if found else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
