"""Demo gap D5: the token budget refills every hour and one user cannot spend everyone's share."""
import pytest
from fastapi.testclient import TestClient

from app import main
from app.appdb import User
from app.auth import current_user
from app.llm import get_llm
from app.llm.base import LLMBudgetError, LLMRateLimitError
from app.llm.budget import TokenBudget, from_env
from app.llm.fake import FakeLLM
from app.main import app


class Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


@pytest.fixture
def clock():
    return Clock()


def test_spending_stops_at_the_limit(clock):
    b = TokenBudget(100, clock=clock)
    b.record(100)
    with pytest.raises(LLMBudgetError):
        b.check()


def test_the_budget_refills_as_the_hour_rolls_on(clock):
    b = TokenBudget(100, window_seconds=3600, clock=clock)
    b.record(60)
    clock.now += 1800
    b.record(40)
    with pytest.raises(LLMBudgetError):
        b.check()
    clock.now += 1801                     # the first 60 tokens are now more than an hour old
    b.check()
    assert b.used() == 40


def test_one_user_cannot_spend_everyone_s_share(clock):
    b = TokenBudget(1000, per_user=100, clock=clock)
    b.record(100, user="alice")
    with pytest.raises(LLMBudgetError):
        b.check(user="alice")
    b.check(user="bob")                   # bob is unaffected


def test_the_overall_limit_still_applies_to_everyone(clock):
    b = TokenBudget(150, per_user=100, clock=clock)
    b.record(90, user="alice")
    b.record(60, user="bob")
    with pytest.raises(LLMBudgetError):
        b.check(user="carol")


def test_the_error_says_when_to_try_again(clock):
    b = TokenBudget(100, clock=clock)
    b.record(100)
    clock.now += 600
    with pytest.raises(LLMBudgetError, match="50 minutes"):
        b.check()


def test_a_budget_error_is_still_a_rate_limit():
    assert issubclass(LLMBudgetError, LLMRateLimitError)


def test_settings_come_from_the_environment(monkeypatch):
    monkeypatch.setenv("LLM_TOKEN_BUDGET", "1234")
    monkeypatch.setenv("LLM_USER_TOKEN_BUDGET", "567")
    monkeypatch.setenv("LLM_TOKEN_BUDGET_WINDOW_SECONDS", "60")
    b = from_env()
    assert (b.limit, b.per_user, b.window) == (1234, 567, 60)


def test_defaults_fit_a_demo_on_retail_data(monkeypatch):
    for name in ("LLM_TOKEN_BUDGET", "LLM_USER_TOKEN_BUDGET", "LLM_TOKEN_BUDGET_WINDOW_SECONDS"):
        monkeypatch.delenv(name, raising=False)
    b = from_env()
    assert b.window == 3600 and b.limit >= 400_000 and b.per_user >= 150_000   # 150k = about 20 retail questions


# ---- through the API ----------------------------------------------------------------------------------------

client = TestClient(app)


@pytest.fixture
def fake_model():
    app.dependency_overrides[get_llm] = lambda: FakeLLM()
    yield
    app.dependency_overrides.pop(get_llm, None)


def as_user(name):
    app.dependency_overrides[current_user] = lambda: User(username=name, role="analyst")


def test_the_budget_is_counted_per_signed_in_user(monkeypatch, fake_model):
    monkeypatch.setattr(main, "budget", TokenBudget(10_000, per_user=1))
    as_user("alice")
    assert client.post("/chat", json={"message": "hi"}).status_code == 200
    r = client.post("/chat", json={"message": "hi"})
    assert r.status_code == 429 and "limit for this hour" in r.json()["detail"]
    as_user("bob")
    assert client.post("/chat", json={"message": "hi"}).status_code == 200
