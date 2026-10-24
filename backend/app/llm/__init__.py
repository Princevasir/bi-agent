import logging
import os
from functools import lru_cache

from app.llm.base import LLMService
from app.llm.base import LLMConfigError


def _timeout(provider, default):
    """GROQ_TIMEOUT_SECONDS and the like override LLM_TIMEOUT_SECONDS for one provider (demo gap D6)."""
    return float(os.getenv(f"{provider.upper()}_TIMEOUT_SECONDS") or os.getenv("LLM_TIMEOUT_SECONDS") or default)


logger = logging.getLogger("bi_agent")
DATA_POLICIES = ("deny", "zdr", "allow")


def _data_policy():
    """GR-PRIV-04: what a hosted provider may do with prompts. deny: no data collection; zdr: zero retention."""
    policy = os.getenv("LLM_PROVIDER_DATA_POLICY", "deny")
    if policy not in DATA_POLICIES:
        raise LLMConfigError(f"LLM_PROVIDER_DATA_POLICY must be one of {', '.join(DATA_POLICIES)}, not {policy!r}.")
    return policy


def _openrouter_options(policy):
    if policy == "allow":
        return None
    return {"data_collection": "deny", **({"zdr": True} if policy == "zdr" else {})}


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
            provider_options=_openrouter_options(_data_policy()),
        )
    if provider == "groq":
        from app.llm.openrouter import OpenRouterLLM
        api_key = os.getenv("GROQ_API_KEY")
        if not api_key:
            raise LLMConfigError("GROQ_API_KEY must be set.")
        # Groq has no per-request retention switch: zero retention is an organisation setting in its console.
        if _data_policy() == "zdr" and os.getenv("GROQ_ZDR_CONFIRMED") != "true":
            raise LLMConfigError("LLM_PROVIDER_DATA_POLICY=zdr with Groq needs zero data retention turned on in the "
                                 "Groq console and GROQ_ZDR_CONFIRMED=true.")
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
    logger.info("llm_data_policy", extra={"provider": provider, "policy": _data_policy()})
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
