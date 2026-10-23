"""Demo gap D6: a fast hosted model first, the local model when it fails (LLM_FALLBACK_PROVIDER)."""
import logging

import pytest

from app.llm import get_llm
from app.llm.base import LLMConfigError, LLMError, LLMResult, LLMTimeoutError, LLMRateLimitError
from app.llm.fallback import FallbackLLM


class Model:
    def __init__(self, name, error=None):
        self.name, self.error, self.calls = name, error, 0

    def generate(self, prompt):
        self.calls += 1
        if self.error:
            raise self.error
        return LLMResult(text=f"{self.name} says hi", input_tokens=1, output_tokens=1)


@pytest.fixture(autouse=True)
def fresh(monkeypatch):
    for name in ("LLM_PROVIDER", "LLM_FALLBACK_PROVIDER", "GROQ_API_KEY", "LLM_TIMEOUT_SECONDS",
                 "GROQ_TIMEOUT_SECONDS", "OLLAMA_TIMEOUT_SECONDS"):
        monkeypatch.delenv(name, raising=False)
    get_llm.cache_clear()
    yield
    get_llm.cache_clear()


# ---- the wrapper ----------------------------------------------------------------------------------------

def test_the_primary_answers_when_it_works():
    primary, backup = Model("groq"), Model("ollama")
    assert FallbackLLM(primary, backup).generate("q").text == "groq says hi"
    assert backup.calls == 0


@pytest.mark.parametrize("error", [LLMTimeoutError("slow"), LLMRateLimitError("429"), LLMError("500"),
                                   LLMConfigError("401 bad key")])
def test_the_fallback_answers_when_the_primary_fails(error, caplog):
    primary, backup = Model("groq", error), Model("ollama")
    with caplog.at_level(logging.WARNING):
        assert FallbackLLM(primary, backup).generate("q").text == "ollama says hi"
    [record] = [r for r in caplog.records if r.message == "llm_fallback"]
    assert record.error == type(error).__name__


def test_when_both_fail_the_fallback_error_is_raised():
    llm = FallbackLLM(Model("groq", LLMTimeoutError("slow")), Model("ollama", LLMError("down")))
    with pytest.raises(LLMError, match="down"):
        llm.generate("q")


# ---- configuration ----------------------------------------------------------------------------------------

def test_groq_first_and_ollama_as_fallback(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "groq")
    monkeypatch.setenv("GROQ_API_KEY", "test-key")
    monkeypatch.setenv("LLM_FALLBACK_PROVIDER", "ollama")
    llm = get_llm()
    assert isinstance(llm, FallbackLLM)
    assert llm.primary.url == "https://api.groq.com/openai/v1/chat/completions"
    assert llm.fallback.url.endswith("/v1/chat/completions") and llm.fallback.model == "qwen2.5-coder:7b"


def test_each_provider_has_its_own_timeout(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "groq")
    monkeypatch.setenv("GROQ_API_KEY", "test-key")
    monkeypatch.setenv("LLM_FALLBACK_PROVIDER", "ollama")
    monkeypatch.setenv("LLM_TIMEOUT_SECONDS", "45")
    monkeypatch.setenv("GROQ_TIMEOUT_SECONDS", "15")
    llm = get_llm()
    assert llm.primary.timeout == 15 and llm.fallback.timeout == 45
    monkeypatch.setenv("OLLAMA_TIMEOUT_SECONDS", "120")
    get_llm.cache_clear()
    assert get_llm().fallback.timeout == 120


def test_no_fallback_means_the_provider_alone(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "ollama")
    assert not isinstance(get_llm(), FallbackLLM)
    monkeypatch.setenv("LLM_FALLBACK_PROVIDER", "ollama")      # the same provider is not a fallback
    get_llm.cache_clear()
    assert not isinstance(get_llm(), FallbackLLM)


def test_configuration_mistakes_still_fail_loudly(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "groq")                  # no key
    monkeypatch.setenv("LLM_FALLBACK_PROVIDER", "ollama")
    with pytest.raises(LLMConfigError, match="GROQ_API_KEY"):
        get_llm()
    monkeypatch.setenv("GROQ_API_KEY", "test-key")
    monkeypatch.setenv("LLM_FALLBACK_PROVIDER", "telepathy")
    get_llm.cache_clear()
    with pytest.raises(LLMConfigError, match="telepathy"):
        get_llm()
