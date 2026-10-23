"""A fast primary model with a dependable fallback (demo gap D6).

If the primary (for example Groq) times out, is rate-limited, rejects the request or fails, the
same prompt goes to the fallback (for example the local Ollama model), and a warning is logged.
If the fallback fails too, its error stands and the API maps it to a plain message.
"""
import logging

from app.llm.base import LLMError

logger = logging.getLogger("bi_agent")


class FallbackLLM:
    def __init__(self, primary, fallback, primary_name="primary", fallback_name="fallback"):
        self.primary, self.fallback = primary, fallback
        self.primary_name, self.fallback_name = primary_name, fallback_name

    def generate(self, prompt):
        try:
            return self.primary.generate(prompt)
        except LLMError as e:
            logger.warning("llm_fallback", extra={"error": type(e).__name__, "primary": self.primary_name,
                                                  "fallback": self.fallback_name})
            return self.fallback.generate(prompt)
