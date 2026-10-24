"""GR-COST-01 (questions per minute and day), GR-COST-02 (tokens per user per day), GR-COST-03 (one question at a time)."""
import psycopg
import pytest
from fastapi.testclient import TestClient

from app import appdb, main
from app.appdb import User
from app.auth import current_user
from app.llm import get_llm
from app.llm.base import LLMBudgetError, LLMDailyQuotaError
from app.llm.budget import TokenBudget
from app.llm.fake import FakeLLM
from app.main import app
from app.request_limits import (Busy, MemoryRunning, RateLimited, RateLimiter, from_env as limits_from_env)

ADMIN = "postgresql://admin:admin_dev_pw@localhost:5433/appdb"


class Clock:
    def __init__(self):
        self.now = 2_000_000.0

    def __call__(self):
        return self.now


# ---- GR-COST-01: questions per minute and per day -----------------------------------------------------------

def test_the_eleventh_question_in_a_minute_is_refused_with_a_wait(monkeypatch):
    clock = Clock()
    limiter = RateLimiter(per_minute=10, per_day=200, clock=clock)
    for _ in range(10):
        limiter.hit("alice")
    with pytest.raises(RateLimited) as e:
        limiter.hit("alice")
    assert e.value.reason == "minute" and 1 <= e.value.retry_after <= 60
    limiter.hit("bob")                                  # another user is unaffected
    clock.now += 61
    limiter.hit("alice")


def test_the_daily_limit_holds_across_minutes():
    clock = Clock()
    limiter = RateLimiter(per_minute=10, per_day=12, clock=clock)
    for _ in range(12):
        limiter.hit("alice")
        clock.now += 30
    with pytest.raises(RateLimited) as e:
        limiter.hit("alice")
    assert e.value.reason == "day"


def test_a_refused_question_does_not_count():
    clock = Clock()
    limiter = RateLimiter(per_minute=1, per_day=200, clock=clock)
    limiter.hit("alice")
    for _ in range(5):
        with pytest.raises(RateLimited):
            limiter.hit("alice")
    clock.now += 61
    limiter.hit("alice")


# ---- GR-COST-02: tokens per user per day ----------------------------------------------------------------------

def test_a_user_over_the_daily_quota_is_refused_while_others_are_not():
    clock = Clock()
    b = TokenBudget(10**9, per_user=10**9, per_user_daily=1000, clock=clock)
    for _ in range(4):                                   # spread over the day: the hourly share never trips
        b.record(250, user="alice")
        clock.now += 3 * 3600
    with pytest.raises(LLMDailyQuotaError):
        b.check(user="alice")
    b.check(user="bob")
    clock.now += 24 * 3600
    b.check(user="alice")


def test_the_daily_quota_is_a_budget_error():
    assert issubclass(LLMDailyQuotaError, LLMBudgetError)


# ---- GR-COST-03: one question at a time -------------------------------------------------------------------------

def test_a_second_simultaneous_question_is_refused():
    running = MemoryRunning()
    with running.hold("alice"):
        with pytest.raises(Busy):
            with running.hold("alice"):
                pass
        with running.hold("bob"):                         # others are unaffected
            pass
    with running.hold("alice"):                           # released after the first finished
        pass


def test_the_hold_is_released_even_when_the_question_fails():
    running = MemoryRunning()
    with pytest.raises(ValueError):
        with running.hold("alice"):
            raise ValueError("boom")
    with running.hold("alice"):
        pass


# ---- through the API ---------------------------------------------------------------------------------------------

client = TestClient(app)


@pytest.fixture
def fake_model():
    app.dependency_overrides[get_llm] = lambda: FakeLLM()
    yield
    app.dependency_overrides.pop(get_llm, None)


def test_the_api_refuses_a_rate_limited_user_with_retry_after(monkeypatch, fake_model, audit_events):
    monkeypatch.setattr(main, "rate_limiter", RateLimiter(per_minute=1, per_day=200))
    assert client.post("/chat", json={"message": "hi"}).status_code == 200
    r = client.post("/chat", json={"message": "hi"})
    assert r.status_code == 429 and int(r.headers["Retry-After"]) >= 1
    assert "too many questions" in r.json()["detail"].lower()
    event = audit_events[-1]
    assert event["event"] == "rate_limited" and event["detail"]["guardrail"] == "GR-COST-01"
    assert event["detail"]["reason"] == "minute" and "latency_ms" in event["detail"]       # GR-OBS-01 fields too


def test_the_api_refuses_a_second_question_while_one_is_running(monkeypatch, fake_model, audit_events):
    running = MemoryRunning()
    monkeypatch.setattr(main, "running", running)
    with running.hold("test-analyst"):
        r = client.post("/ask", json={"message": "hello"})
    assert r.status_code == 429 and r.json()["detail"] == "Please wait for your previous question to finish."
    detail = audit_events[-1]["detail"]
    assert detail["guardrail"] == "GR-COST-03" and detail["reason"] == "concurrency" and "latency_ms" in detail


def test_the_api_explains_the_daily_quota(monkeypatch, fake_model):
    monkeypatch.setattr(main, "budget", TokenBudget(10**9, per_user=10**9, per_user_daily=1))
    assert client.post("/chat", json={"message": "hi"}).status_code == 200
    r = client.post("/chat", json={"message": "hi"})
    assert r.status_code == 429 and "daily limit" in r.json()["detail"]


def test_defaults(monkeypatch):
    for name in ("RATE_PER_MINUTE", "RATE_PER_DAY", "STATE_STORE"):
        monkeypatch.delenv(name, raising=False)
    limiter, running = limits_from_env()
    assert (limiter.per_minute, limiter.per_day) == (10, 200) and isinstance(running, MemoryRunning)


# ---- shared between instances (STATE_STORE=postgres) ----------------------------------------------------------------

@pytest.fixture
def clean():
    def wipe():
        with psycopg.connect(ADMIN, autocommit=True) as conn:
            conn.execute("DELETE FROM request_usage WHERE username LIKE 'cost-test%'")
            conn.execute("DELETE FROM running_questions WHERE username LIKE 'cost-test%'")
    wipe()
    yield
    wipe()


@pytest.mark.integration
def test_rate_limits_hold_across_instances(clean):
    clock = Clock()
    a = RateLimiter(per_minute=2, per_day=200, clock=clock, ledger=appdb.PgTokenLedger("request_usage"))
    b = RateLimiter(per_minute=2, per_day=200, clock=clock, ledger=appdb.PgTokenLedger("request_usage"))
    a.hit("cost-test-alice")
    b.hit("cost-test-alice")
    with pytest.raises(RateLimited):
        a.hit("cost-test-alice")


@pytest.mark.integration
def test_one_question_at_a_time_across_instances(clean):
    first, second = appdb.PgRunning(), appdb.PgRunning()
    with first.hold("cost-test-alice"):
        with pytest.raises(Busy):
            with second.hold("cost-test-alice"):
                pass
    with second.hold("cost-test-alice"):
        pass


@pytest.mark.integration
def test_a_stale_hold_from_a_crashed_instance_expires(clean):
    clock = Clock()
    crashed = appdb.PgRunning(clock=clock, stale_after=300)
    crashed.hold("cost-test-alice").__enter__()           # never released
    clock.now += 301
    with appdb.PgRunning(clock=clock, stale_after=300).hold("cost-test-alice"):
        pass


def test_unknown_ledger_tables_are_refused():
    with pytest.raises(ValueError):
        appdb.PgTokenLedger("users; DROP TABLE users")
