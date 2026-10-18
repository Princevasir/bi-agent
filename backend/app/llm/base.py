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