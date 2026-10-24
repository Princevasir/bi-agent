"""GR-PRIV-05: table exports are allowed per role and every export is recorded before the file is offered."""
import pytest
from fastapi.testclient import TestClient

from app import access, policy
from app.appdb import User
from app.auth import current_user
from app.main import app

client = TestClient(app)
EXPORT = {"question": "Revenue by region", "columns": ["region", "revenue"], "row_count": 3, "conversation_id": None}


def test_the_policy_says_which_roles_may_export():
    for source in policy.get().sources.values():
        for name, role in source.roles.items():
            assert role.export is True, name                # the owner's decision: allowed and recorded


def test_a_role_without_the_setting_may_not_export():
    assert policy.Role(tables=("regions",), database_url_env="X").export is False


def test_an_export_is_recorded_in_the_audit_trail(audit_events):
    r = client.post("/exports", json=EXPORT)
    assert r.status_code == 200 and r.json() == {"recorded": True}
    event = audit_events[-1]
    assert event["event"] == "export" and event["detail"]["guardrail"] == "GR-PRIV-05"
    assert event["detail"]["row_count"] == 3 and event["detail"]["columns"] == ["region", "revenue"]


def test_a_role_that_may_not_export_is_refused(monkeypatch, audit_events):
    monkeypatch.setattr(access, "may_export", lambda role: False)
    r = client.post("/exports", json=EXPORT)
    assert r.status_code == 403 and r.json() == {"detail": "Your role may not export data."}
    assert audit_events[-1]["event"] == "export_denied"


def test_exports_need_sign_in():
    app.dependency_overrides.pop(current_user, None)
    try:
        assert client.post("/exports", json=EXPORT).status_code == 401
    finally:
        app.dependency_overrides[current_user] = lambda: User(username="test-analyst", role="analyst")


@pytest.mark.parametrize("bad", [{**EXPORT, "row_count": -1}, {**EXPORT, "question": "x" * 2001}, {"columns": []}])
def test_nonsense_export_records_are_refused(bad):
    assert client.post("/exports", json=bad).status_code == 422
