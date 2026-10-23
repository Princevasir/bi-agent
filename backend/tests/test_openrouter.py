import httpx
import pytest

from app.llm.base import LLMError, LLMConfigError, LLMRateLimitError, LLMTimeoutError 
from app.llm.openrouter import OpenRouterLLM

OK = {
    "choices": [{"message": {"content": "Hi there"}}],
    "usage": {"prompt_tokens": 5, "completion_tokens": 3},
}


class FakeResponse:
    def __init__(self, data=None, status=200):
        self.data, self.status = data, status

    def raise_for_status(self):
        if self.status >= 400:
            req = httpx.Request("POST", "https://example.test")
            raise httpx.HTTPStatusError(
                "error", request=req, response=httpx.Response(self.status, request=req)
            )

    def json(self):
        return self.data


class FakeClient:
    def __init__(self, response):
        self.response = response

    def post(self, url, **kwargs):
        self.url, self.kwargs = url, kwargs
        return self.response


def test_generate_parses_response():
    fake = FakeClient(FakeResponse(OK))
    result = OpenRouterLLM(api_key="k", model="test-model", client=fake).generate("hello")
    assert result.text == "Hi there"
    assert (result.input_tokens, result.output_tokens) == (5, 3)
    assert fake.kwargs["json"]["model"] == "test-model"
    assert fake.kwargs["json"]["max_tokens"] == 512


def test_http_error_becomes_llm_error():
    llm = OpenRouterLLM(api_key="k", model="m", client=FakeClient(FakeResponse(status=401)))
    with pytest.raises(LLMError):
        llm.generate("hi")

class TimeoutClient:
    def post(self, url, **kwargs):
        raise httpx.ReadTimeout("slow")


@pytest.mark.parametrize("client, expected", [
    (TimeoutClient(), LLMTimeoutError),
    (FakeClient(FakeResponse(status=429)), LLMRateLimitError),
    (FakeClient(FakeResponse(status=401)), LLMConfigError),
    (FakeClient(FakeResponse(status=503)), LLMError),
])
def test_openrouter_errors_are_mapped(client, expected):
    with pytest.raises(expected):
        OpenRouterLLM(api_key="k", model="m", client=client).generate("hi")