from fastapi.testclient import TestClient

from app import main
from app.main import app
from app.throttle import LoginThrottle

client = TestClient(app)


def make(clock):
    return LoginThrottle(max_failures=5, window=900, lockout=900, clock=lambda: clock[0])


def test_locks_after_five_failures():
    clock = [0.0]
    t = make(clock)
    for _ in range(4):
        t.record_failure("a")
    assert not t.is_locked("a")
    t.record_failure("a")
    assert t.is_locked("a")


def test_lock_expires():
    clock = [0.0]
    t = make(clock)
    for _ in range(5):
        t.record_failure("a")
    clock[0] = 901
    assert not t.is_locked("a")


def test_success_resets_the_count():
    clock = [0.0]
    t = make(clock)
    for _ in range(4):
        t.record_failure("a")
    t.record_success("a")
    for _ in range(4):
        t.record_failure("a")
    assert not t.is_locked("a")


def test_old_failures_fall_out_of_the_window():
    clock = [0.0]
    t = make(clock)
    for _ in range(4):
        t.record_failure("a")
    clock[0] = 1000
    t.record_failure("a")
    assert not t.is_locked("a")


def test_sixth_attempt_is_locked_and_audited(monkeypatch, audit_events):
    monkeypatch.setattr(main, "get_user", lambda name: None)
    for _ in range(5):
        assert client.post("/auth/login", json={"username": "bob", "password": "x"}).status_code == 401
    r = client.post("/auth/login", json={"username": "bob", "password": "x"})
    assert r.status_code == 429
    assert r.json() == {"detail": "Too many sign-in attempts. Try again later."}
    assert audit_events[-1]["event"] == "login_locked"
