"""Groq through the same OpenAI-compatible client; the evaluation runner waits out rate limits."""
import pytest

from app.llm import get_llm
from app.llm.base import LLMConfigError, LLMError, LLMRateLimitError
from evals import run as runner


@pytest.fixture(autouse=True)
def fresh(monkeypatch):
    for name in ("GROQ_API_KEY", "GROQ_MODEL", "LLM_TIMEOUT_SECONDS"):
        monkeypatch.delenv(name, raising=False)
    get_llm.cache_clear()
    yield
    get_llm.cache_clear()


def test_groq_uses_its_address_key_and_default_model(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "groq")
    monkeypatch.setenv("GROQ_API_KEY", "test-key")
    llm = get_llm()
    assert llm.url == "https://api.groq.com/openai/v1/chat/completions"
    assert llm.model == "qwen/qwen3.8-27b"
    assert llm.client.headers["authorization"] == "Bearer test-key"


def test_groq_model_is_configurable(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "groq")
    monkeypatch.setenv("GROQ_API_KEY", "test-key")
    monkeypatch.setenv("GROQ_MODEL", "openai/gpt-oss-120b")
    assert get_llm().model == "openai/gpt-oss-120b"


def test_groq_needs_a_key(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "groq")
    with pytest.raises(LLMConfigError, match="GROQ_API_KEY"):
        get_llm()


# ---- the runner waits out the provider's rate limits ----------------------------------------------------

def test_rate_limits_are_waited_out():
    calls, waits = [], []

    def flaky():
        calls.append(1)
        if len(calls) < 3:
            raise LLMRateLimitError("The provider is rate-limiting requests.")
        return "ok"

    assert runner.with_backoff(flaky, sleep=waits.append) == "ok"
    assert len(calls) == 3 and waits == [10, 20]


def test_backoff_gives_up_after_its_attempts():
    waits = []

    def always_limited():
        raise LLMRateLimitError("The provider is rate-limiting requests.")

    with pytest.raises(LLMRateLimitError):
        runner.with_backoff(always_limited, sleep=waits.append, attempts=4)
    assert len(waits) == 3


def test_other_errors_are_not_retried():
    calls = []

    def broken():
        calls.append(1)
        raise LLMError("boom")

    with pytest.raises(LLMError):
        runner.with_backoff(broken, sleep=lambda s: None)
    assert len(calls) == 1
