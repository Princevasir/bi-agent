import pytest
from fastapi.testclient import TestClient

from app.llm import get_llm
from app.llm.fake import FakeLLM
from app.llm.base import LLMError
from app.main import app
from app import main
from app.llm.budget import TokenBudget
from app.llm.base import LLMConfigError, LLMRateLimitError, LLMTimeoutError


client = TestClient(app)


@pytest.fixture(autouse=True)
def use_fake_llm():
    app.dependency_overrides[get_llm] = lambda: FakeLLM()
    yield
    app.dependency_overrides.clear()


def test_chat_returns_reply():
    r = client.post("/chat", json={"message": "hello"})
    assert r.status_code == 200
    assert r.json() == {"reply": "Echo: hello"}


def test_chat_rejects_blank_message():
    assert client.post("/chat", json={"message": "   "}).status_code == 422


def test_chat_rejects_too_long_message():
    assert client.post("/chat", json={"message": "x" * 2001}).status_code == 422


def test_chat_rejects_missing_field():
    assert client.post("/chat", json={}).status_code == 422

def test_chat_returns_502_on_llm_failure():
    class Failing:
        def generate(self, prompt):
            raise LLMError("boom")

    app.dependency_overrides[get_llm] = lambda: Failing()
    assert client.post("/chat", json={"message": "hi"}).status_code == 502

@pytest.mark.parametrize("exc, status", [
    (LLMTimeoutError("t"), 504),
    (LLMRateLimitError("r"), 429),
    (LLMConfigError("c"), 503),
    (LLMError("e"), 502),
])
def test_llm_errors_map_to_status(exc, status):
    class Failing:
        def generate(self, prompt):
            raise exc

    app.dependency_overrides[get_llm] = lambda: Failing()
    assert client.post("/chat", json={"message": "hi"}).status_code == status


def test_token_budget_exhausted_returns_429(monkeypatch):
    monkeypatch.setattr(main, "budget", TokenBudget(limit=1))
    assert client.post("/chat", json={"message": "hello"}).status_code == 200
    assert client.post("/chat", json={"message": "hello"}).status_code == 429


def test_missing_openrouter_key_is_config_error(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "openrouter")
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    get_llm.cache_clear()
    with pytest.raises(LLMConfigError):
        get_llm()
    get_llm.cache_clear()