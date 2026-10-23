from dataclasses import dataclass
from typing import Protocol


class LLMError(Exception):
    """Base class for LLM failures."""


@dataclass(frozen=True)
class LLMResult:
    text: str
    input_tokens: int = 0
    output_tokens: int = 0


class LLMService(Protocol):
    def generate(self, prompt: str) -> LLMResult: ...

class LLMTimeoutError(LLMError):
    """The model did not answer in time."""

class LLMRateLimitError(LLMError):
    """Provider throttling or our own token budget."""

class LLMConfigError(LLMError):
    """Missing or invalid credentials, model, or settings."""

class LLMBudgetError(LLMRateLimitError):
    """Our own hourly token budget is used up (demo gap D5), as opposed to the provider throttling us."""


class LLMUnavailableError(LLMError):
    """A provider is skipped for a while after repeated failures (circuit breaker, demo gap D9)."""
