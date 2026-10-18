import os
from functools import lru_cache

from app.llm.base import LLMService
from app.llm.base import LLMConfigError


@lru_cache
def get_llm() -> LLMService:
    provider = os.getenv("LLM_PROVIDER", "fake")
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
            timeout=float(os.getenv("LLM_TIMEOUT_SECONDS", "20")),
        )
    raise LLMConfigError(f"Unknown LLM_PROVIDER: {provider}")

