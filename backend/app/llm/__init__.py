import os
from functools import lru_cache

from app.llm.base import LLMService
from app.llm.base import LLMConfigError


def _timeout(provider, default):
    """GROQ_TIMEOUT_SECONDS and the like override LLM_TIMEOUT_SECONDS for one provider (demo gap D6)."""
    return float(os.getenv(f"{provider.upper()}_TIMEOUT_SECONDS") or os.getenv("LLM_TIMEOUT_SECONDS") or default)


def _provider(provider) -> LLMService:
    if provider == "fake":
        from app.llm.fake import FakeLLM
        return FakeLLM()

    if provider == "openrouter":
        from app.llm.openrouter import OpenRouterLLM
        api_key = os.getenv("OPENROUTER_API_KEY")
        if not api_key:
            raise LLMConfigError("OPENROUTER_API_KEY must be set.")
        return OpenRouterLLM(
            api_key=api_key,
            model=os.getenv("OPENROUTER_MODEL", "qwen/qwen-2.5-coder-32b-instruct"),
            max_tokens=int(os.getenv("LLM_MAX_OUTPUT_TOKENS", "512")),
            timeout=_timeout("openrouter", "20"),
        )
    if provider == "groq":
        from app.llm.openrouter import OpenRouterLLM
        api_key = os.getenv("GROQ_API_KEY")
        if not api_key:
            raise LLMConfigError("GROQ_API_KEY must be set.")
        return OpenRouterLLM(
            api_key=api_key,
            model=os.getenv("GROQ_MODEL", "qwen/qwen3.8-27b"),
            url="https://api.groq.com/openai/v1/chat/completions",
            max_tokens=int(os.getenv("LLM_MAX_OUTPUT_TOKENS", "512")),
            timeout=_timeout("groq", "30"),
        )
    if provider == "ollama":
        from app.llm.openrouter import OpenRouterLLM
        base = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434/v1").rstrip("/")
        return OpenRouterLLM(
            api_key=None,
            model=os.getenv("OLLAMA_MODEL", "qwen2.5-coder:7b"),
            url=f"{base}/chat/completions",
            max_tokens=int(os.getenv("LLM_MAX_OUTPUT_TOKENS", "512")),
            timeout=_timeout("ollama", "60"),   # a local model is slower
        )
    raise LLMConfigError(f"Unknown LLM provider: {provider}")


def _resilient(provider) -> LLMService:
    """Network providers get one retry and a circuit breaker (demo gap D9); the fake model does not."""
    llm = _provider(provider)
    if provider == "fake":
        return llm
    from app.llm.resilience import CircuitBreaker, RetryingLLM
    return CircuitBreaker(RetryingLLM(llm, attempts=int(os.getenv("LLM_RETRY_ATTEMPTS", "2"))), provider,
                          failures=int(os.getenv("LLM_BREAKER_FAILURES", "3")),
                          cooldown=float(os.getenv("LLM_BREAKER_COOLDOWN_SECONDS", "60")))


@lru_cache
def get_llm() -> LLMService:
    name = os.getenv("LLM_PROVIDER", "fake")
    primary = _resilient(name)
    fallback = os.getenv("LLM_FALLBACK_PROVIDER", "")
    if not fallback or fallback == name:
        return primary
    from app.llm.fallback import FallbackLLM
    return FallbackLLM(primary, _resilient(fallback), name, fallback)
