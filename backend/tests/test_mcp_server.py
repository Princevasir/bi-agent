"""Demo gap D10: the BI Agent as an MCP server with two tools, calling the backend's API as a signed-in user."""
import asyncio
import json

import httpx
import pytest

mcp = pytest.importorskip("mcp")
from mcp.server.mcpserver.exceptions import ToolError  # noqa: E402

from app import mcp_server  # noqa: E402

PASSWORD = "a-long-mcp-password"
ANSWER = {"route": "data", "answer": "Revenue was 39,905,806.83.", "sql": "SELECT 1", "columns": ["revenue"],
          "rows": [[float(i)] for i in range(30)], "truncated": False, "answer_source": "llm", "chart": None,
          "sources": [{"document_id": "rule-fiscal-calendar", "title": "Fiscal calendar"}], "trace": [],
          "conversation_id": "c-1", "interpreted_as": "x", "question": "x"}
HITS = {"hits": [{"document_id": "rule-fiscal-calendar", "title": "Fiscal calendar", "doc_type": "rule",
                  "version": 1, "score": 0.86, "content": "The fiscal year runs from 1 February."}]}


class FakeBackend:
    """Answers like the BI Agent API; records requests."""

    def __init__(self, ask_status=None, expire_once=False, down=False):
        self.requests, self.ask_status, self.expire_once, self.down, self.logins = [], ask_status, expire_once, down, 0

    def __call__(self, request):
        if self.down:
            raise httpx.ConnectError("refused", request=request)
        self.requests.append(request)
        if request.url.path == "/auth/login":
            body = json.loads(request.content)
            if body["password"] != PASSWORD:
                return httpx.Response(401, json={"detail": "Invalid username or password."})
            self.logins += 1
            return httpx.Response(200, json={"access_token": f"token-{self.logins}", "role": "analyst"})
        if request.headers.get("authorization") != f"Bearer token-{self.logins}":
            return httpx.Response(401, json={"detail": "Not authenticated."})
        if self.expire_once:
            self.expire_once = False
            return httpx.Response(401, json={"detail": "Token expired."})
        if request.url.path == "/ask":
            if self.ask_status:
                return httpx.Response(self.ask_status, json={"detail": "The generated query was rejected."})
            return httpx.Response(200, json=ANSWER)
        if request.url.path == "/knowledge/search":
            return httpx.Response(200, json=HITS)
        return httpx.Response(404, json={"detail": "Not found"})


def server(fake, username="demo-analyst", password=PASSWORD):
    client = mcp_server.BackendClient("http://bi-agent", username, password, transport=httpx.MockTransport(fake))
    return mcp_server.build_server(client)


def call(srv, tool, args):
    result = asyncio.run(srv.call_tool(tool, args))
    return json.loads(result.content[0].text)


# ---- the tools --------------------------------------------------------------------------------------------------

def test_there_are_exactly_two_tools_with_clear_descriptions():
    tools = asyncio.run(server(FakeBackend()).list_tools())
    assert sorted(t.name for t in tools) == ["ask_data", "search_knowledge"]
    for t in tools:
        assert len(t.description) > 40, t.name


def test_ask_data_signs_in_and_returns_a_compact_answer():
    fake = FakeBackend()
    out = call(server(fake), "ask_data", {"question": "What was revenue in fiscal year 2025?"})
    assert out["answer"] == "Revenue was 39,905,806.83." and out["sql"] == "SELECT 1"
    assert len(out["rows"]) == 20 and out["rows_shown"] == 20 and out["row_count"] == 30
    assert out["sources"] == ["rule-fiscal-calendar"] and out["conversation_id"] == "c-1"
    login, ask = fake.requests
    assert login.url.path == "/auth/login" and json.loads(ask.content)["message"].startswith("What was revenue")


def test_a_follow_up_passes_the_conversation_id():
    fake = FakeBackend()
    call(server(fake), "ask_data", {"question": "And the year before?", "conversation_id": "c-1"})
    assert json.loads(fake.requests[-1].content)["conversation_id"] == "c-1"


def test_an_expired_token_is_renewed_once():
    fake = FakeBackend(expire_once=True)
    assert call(server(fake), "ask_data", {"question": "q"})["answer"]
    assert fake.logins == 2


def test_search_knowledge_returns_documents():
    fake = FakeBackend()
    out = call(server(fake), "search_knowledge", {"query": "fiscal year"})["documents"]
    assert out[0]["document_id"] == "rule-fiscal-calendar" and "1 February" in out[0]["excerpt"]
    assert fake.requests[-1].url.params["q"] == "fiscal year"


# ---- errors come back as plain tool errors ------------------------------------------------------------------

def test_a_backend_that_is_down_is_a_plain_error():
    with pytest.raises(ToolError, match="not reachable at http://bi-agent"):
        call(server(FakeBackend(down=True)), "ask_data", {"question": "q"})


def test_the_backend_s_own_message_is_passed_on():
    with pytest.raises(ToolError, match="The generated query was rejected."):
        call(server(FakeBackend(ask_status=422)), "ask_data", {"question": "drop table orders"})


def test_wrong_credentials_never_show_the_password():
    with pytest.raises(ToolError) as e:
        call(server(FakeBackend(), password="wrong-password-123"), "ask_data", {"question": "q"})
    assert "Sign-in to the BI Agent failed for demo-analyst" in str(e.value) and "wrong-password" not in str(e.value)


def test_missing_credentials_are_a_clear_configuration_error(monkeypatch):
    monkeypatch.delenv("BI_AGENT_USERNAME", raising=False)
    monkeypatch.delenv("BI_AGENT_PASSWORD", raising=False)
    with pytest.raises(SystemExit, match="BI_AGENT_USERNAME"):
        mcp_server.client_from_env()
