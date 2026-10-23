"""Demo gap D9: one retry with backoff for transient model failures, and a circuit breaker per provider."""
import logging

import pytest

from app.llm import get_llm
from app.llm.base import (LLMBudgetError, LLMConfigError, LLMError, LLMRateLimitError, LLMResult, LLMTimeoutError,
                          LLMUnavailableError)
from app.llm.fallback import FallbackLLM
from app.llm.resilience import CircuitBreaker, RetryingLLM


class Script:
    """Fails with the given errors in order, then answers."""

    def __init__(self, *errors, url="http://model"):
        self.errors, self.calls, self.url = list(errors), 0, url

    def generate(self, prompt):
        self.calls += 1
        if self.errors:
            raise self.errors.pop(0)
        return LLMResult(text="ok", input_tokens=1, output_tokens=1)


class Clock:
    def __init__(self):
        self.now = 100.0

    def __call__(self):
        return self.now


# ---- retry -----------------------------------------------------------------------------------------------

@pytest.mark.parametrize("error", [LLMError("502 from the provider"), LLMRateLimitError("429 from the provider")])
def test_a_transient_failure_is_retried_once_after_a_pause(error):
    pauses, model = [], Script(error)
    assert RetryingLLM(model, sleep=pauses.append).generate("q").text == "ok"
    assert model.calls == 2 and pauses == [1.0]


def test_a_second_failure_stands():
    model = Script(LLMError("down"), LLMError("still down"))
    with pytest.raises(LLMError, match="still down"):
        RetryingLLM(model, sleep=lambda s: None).generate("q")
    assert model.calls == 2


@pytest.mark.parametrize("error", [LLMConfigError("401"), LLMBudgetError("ours"), LLMTimeoutError("slow")])
def test_some_failures_are_never_retried(error):
    model = Script(error)
    with pytest.raises(type(error)):
        RetryingLLM(model, sleep=lambda s: None).generate("q")
    assert model.calls == 1


def test_retries_can_be_switched_off():
    model = Script(LLMError("down"))
    with pytest.raises(LLMError):
        RetryingLLM(model, attempts=1, sleep=lambda s: None).generate("q")
    assert model.calls == 1


# ---- circuit breaker ---------------------------------------------------------------------------------------

def test_the_breaker_opens_after_repeated_failures_and_stops_calling(caplog):
    clock, model = Clock(), Script(*[LLMError("down")] * 3)
    breaker = CircuitBreaker(model, "groq", failures=3, cooldown=60, clock=clock)
    for _ in range(3):
        with pytest.raises(LLMError):
            breaker.generate("q")
    with caplog.at_level(logging.WARNING), pytest.raises(LLMUnavailableError, match="groq"):
        breaker.generate("q")
    assert model.calls == 3                                   # the fourth call never reached the model
    assert any(r.message == "llm_circuit_open" for r in caplog.records)


def test_after_the_cooldown_one_trial_call_closes_it_again():
    clock, model = Clock(), Script(*[LLMError("down")] * 3)
    breaker = CircuitBreaker(model, "groq", failures=3, cooldown=60, clock=clock)
    for _ in range(3):
        with pytest.raises(LLMError):
            breaker.generate("q")
    clock.now += 61
    assert breaker.generate("q").text == "ok" and breaker.state == "closed"


def test_a_failed_trial_call_opens_it_for_another_cooldown():
    clock, model = Clock(), Script(*[LLMError("down")] * 4)
    breaker = CircuitBreaker(model, "groq", failures=3, cooldown=60, clock=clock)
    for _ in range(3):
        with pytest.raises(LLMError):
            breaker.generate("q")
    clock.now += 61
    with pytest.raises(LLMError, match="down"):
        breaker.generate("q")
    with pytest.raises(LLMUnavailableError):
        breaker.generate("q")


def test_a_success_resets_the_count():
    clock, model = Clock(), Script(LLMError("a"), LLMError("b"))
    breaker = CircuitBreaker(model, "groq", failures=3, cooldown=60, clock=clock)
    for _ in range(2):
        with pytest.raises(LLMError):
            breaker.generate("q")
    breaker.generate("q")
    assert breaker.failures_in_a_row == 0 and breaker.state == "closed"


def test_our_own_budget_never_trips_the_breaker():
    clock, model = Clock(), Script(*[LLMBudgetError("ours")] * 5)
    breaker = CircuitBreaker(model, "groq", failures=3, cooldown=60, clock=clock)
    for _ in range(5):
        with pytest.raises(LLMBudgetError):
            breaker.generate("q")
    assert breaker.state == "closed"


def test_an_open_breaker_sends_the_fallback_in_at_once():
    clock = Clock()
    primary = CircuitBreaker(Script(*[LLMRateLimitError("429")] * 9), "groq", failures=1, cooldown=60, clock=clock)
    backup = Script()
    llm = FallbackLLM(primary, backup)
    llm.generate("q")                                         # the 429 opens the breaker; ollama answers
    llm.generate("q")                                         # groq is skipped without a call
    assert primary.llm.calls == 1 and backup.calls == 2


# ---- wiring ----------------------------------------------------------------------------------------------------

@pytest.fixture
def fresh(monkeypatch):
    for name in ("LLM_PROVIDER", "LLM_FALLBACK_PROVIDER", "LLM_RETRY_ATTEMPTS", "LLM_BREAKER_FAILURES",
                 "LLM_BREAKER_COOLDOWN_SECONDS"):
        monkeypatch.delenv(name, raising=False)
    get_llm.cache_clear()
    yield
    get_llm.cache_clear()


def test_network_providers_get_a_breaker_and_a_retry(fresh, monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "ollama")
    llm = get_llm()
    assert isinstance(llm, CircuitBreaker) and isinstance(llm.llm, RetryingLLM)
    assert llm.url.endswith("/v1/chat/completions")           # attributes still reach the client


def test_settings_come_from_the_environment(fresh, monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "ollama")
    monkeypatch.setenv("LLM_RETRY_ATTEMPTS", "1")
    monkeypatch.setenv("LLM_BREAKER_FAILURES", "5")
    monkeypatch.setenv("LLM_BREAKER_COOLDOWN_SECONDS", "30")
    llm = get_llm()
    assert (llm.threshold, llm.cooldown, llm.llm.attempts) == (5, 30, 1)


def test_the_fake_model_stays_unwrapped(fresh, monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "fake")
    assert not isinstance(get_llm(), CircuitBreaker)


def test_an_open_breaker_is_a_clear_503(monkeypatch):
    from fastapi.testclient import TestClient
    from app.main import app

    class Open:
        def generate(self, prompt):
            raise LLMUnavailableError("groq is cooling down")

    app.dependency_overrides[get_llm] = lambda: Open()
    try:
        r = TestClient(app).post("/chat", json={"message": "hi"})
    finally:
        app.dependency_overrides.pop(get_llm, None)
    assert r.status_code == 503 and r.json()["detail"] == "The language model is temporarily unavailable. Please try again in a minute."
