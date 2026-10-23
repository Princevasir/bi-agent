"""A local model through Ollama's OpenAI-compatible API, using the same client as OpenRouter."""
import pytest

from app.llm import get_llm
from app.llm.openrouter import OPENROUTER_URL, OpenRouterLLM
from test_openrouter import OK, FakeClient, FakeResponse


@pytest.fixture(autouse=True)
def fresh_llm(monkeypatch):
    for name in ("OLLAMA_BASE_URL", "OLLAMA_MODEL", "LLM_TIMEOUT_SECONDS", "OPENROUTER_API_KEY"):
        monkeypatch.delenv(name, raising=False)
    get_llm.cache_clear()
    yield
    get_llm.cache_clear()


def test_ollama_needs_no_api_key_and_has_local_defaults(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "ollama")
    llm = get_llm()
    assert llm.url == "http://localhost:11434/v1/chat/completions"
    assert llm.model == "qwen2.5-coder:7b"
    assert "authorization" not in {k.lower() for k in llm.client.headers}
    assert llm.client.timeout.read == 60


def test_ollama_address_model_and_timeout_are_configurable(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "ollama")
    monkeypatch.setenv("OLLAMA_BASE_URL", "http://host.docker.internal:11434/v1/")
    monkeypatch.setenv("OLLAMA_MODEL", "qwen2.5-coder:14b")
    monkeypatch.setenv("LLM_TIMEOUT_SECONDS", "90")
    llm = get_llm()
    assert llm.url == "http://host.docker.internal:11434/v1/chat/completions"
    assert llm.model == "qwen2.5-coder:14b"
    assert llm.client.timeout.read == 90


def test_requests_go_to_the_configured_address():
    client = FakeClient(FakeResponse(OK))
    llm = OpenRouterLLM(api_key=None, model="m", url="http://localhost:11434/v1/chat/completions", client=client)
    assert llm.generate("hi").text == "Hi there"
    assert client.url == "http://localhost:11434/v1/chat/completions"
    assert client.kwargs["json"]["model"] == "m"


def test_openrouter_keeps_its_address(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "openrouter")
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    llm = get_llm()
    assert llm.url == OPENROUTER_URL
    assert llm.client.headers["authorization"] == "Bearer test-key"
