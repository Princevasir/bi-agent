import httpx

from app.llm.base import (
    LLMConfigError, LLMError, LLMRateLimitError, LLMResult, LLMTimeoutError,
)

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"


class OpenRouterLLM:
    """Any OpenAI-compatible chat completions API: OpenRouter by default, or a local Ollama server."""

    def __init__(self, api_key, model, max_tokens=512, timeout=20.0, client=None, url=OPENROUTER_URL,
                 provider_options=None):
        self.model = model
        self.url = url
        self.max_tokens = max_tokens
        self.timeout = timeout
        self.provider_options = provider_options      # OpenRouter's data policy (GR-PRIV-04)
        self.client = client or httpx.Client(
            headers={"Authorization": f"Bearer {api_key}"} if api_key else {},
            timeout=httpx.Timeout(timeout, connect=5.0),
        )

    def generate(self, prompt: str) -> LLMResult:
        payload = {
            "model": self.model,
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": self.max_tokens,
            "temperature": 0,
        }
        if self.provider_options:
            payload["provider"] = self.provider_options
        try:
            resp = self.client.post(self.url, json=payload)
            resp.raise_for_status()
            data = resp.json()
        except httpx.TimeoutException as e:
            raise LLMTimeoutError("The model request timed out.") from e
        except httpx.HTTPStatusError as e:
            status = e.response.status_code
            if status == 408:
                raise LLMTimeoutError("The provider timed out.") from e
            if status == 429:
                raise LLMRateLimitError("The provider is rate-limiting requests.") from e
            if status in {400, 401, 402, 403, 404}:
                raise LLMConfigError(f"Provider rejected the request: HTTP {status}") from e
            raise LLMError(f"Provider error: HTTP {status}") from e
        except (httpx.HTTPError, ValueError) as e:
            raise LLMError("The model request failed.") from e
        if isinstance(data, dict) and "error" in data:
            raise LLMError("The provider returned an error response.")
        try:
            text = data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as e:
            raise LLMError("Unexpected response shape from the model.") from e
        if not isinstance(text, str):
            raise LLMError("The model returned no text.")
        usage = data.get("usage") or {}
        return LLMResult(
            text=text,
            input_tokens=usage.get("prompt_tokens", 0),
            output_tokens=usage.get("completion_tokens", 0),
        )