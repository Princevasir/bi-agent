"""The BI Agent as an MCP server (demo gap D10): two tools for MCP clients such as Claude Desktop.

ask_data asks a question in plain English and returns the grounded answer, SQL, rows and sources;
search_knowledge finds the business documents (definitions, rules, reports) behind the answers.
The server calls the BI Agent's own API as a signed-in user (BI_AGENT_USERNAME and
BI_AGENT_PASSWORD), so every guardrail, role check and audit entry still applies: the MCP client
never reaches the database or the model directly. Errors come back as plain tool errors.

Run it from an MCP client (stdio):
    command: backend/.venv/bin/python   args: ["-m", "app.mcp_server"]   cwd: backend
    env: BI_AGENT_URL (default http://localhost:8000), BI_AGENT_USERNAME, BI_AGENT_PASSWORD
"""
import os
import sys

import httpx
from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError

MAX_ROWS = 20
EXCERPT_CHARS = 600


class BackendClient:
    """Signs in lazily, renews an expired token once, and turns every failure into a plain ToolError."""

    def __init__(self, url, username, password, transport=None, timeout=180.0):
        self.url, self.username, self._password, self._token = url.rstrip("/"), username, password, None
        self._http = httpx.Client(base_url=self.url, transport=transport, timeout=timeout)

    def _send(self, method, path, **kw):
        try:
            return self._http.request(method, path, **kw)
        except httpx.TimeoutException:
            raise ToolError("The BI Agent took too long to answer. Try a simpler question.") from None
        except httpx.HTTPError:
            raise ToolError(f"The BI Agent backend is not reachable at {self.url}. "
                            "Start it with: docker compose up -d") from None

    def _sign_in(self):
        r = self._send("POST", "/auth/login", json={"username": self.username, "password": self._password})
        if r.status_code != 200:
            raise ToolError(f"Sign-in to the BI Agent failed for {self.username}: {_detail(r)}")
        self._token = r.json()["access_token"]

    def call(self, method, path, **kw):
        for attempt in (1, 2):
            if self._token is None:
                self._sign_in()
            r = self._send(method, path, headers={"Authorization": f"Bearer {self._token}"}, **kw)
            if r.status_code == 401 and attempt == 1:          # expired: sign in again, once
                self._token = None
                continue
            if r.status_code != 200:
                raise ToolError(_detail(r))
            return r.json()


def _detail(response):
    try:
        return str(response.json().get("detail", f"HTTP {response.status_code}"))
    except ValueError:
        return f"HTTP {response.status_code}"


def build_server(client):
    server = MCPServer("bi-agent", instructions=(
        "Ask questions about the company's sales, orders, products, customers and stock in plain English. "
        "Every answer is computed by a validated, read-only SQL query and grounded in its rows."))

    @server.tool(description=(
        "Answer a business question from the retail data in plain English, for example "
        "'What was revenue by region in 2025?'. Returns the answer, the SQL that was run, up to 20 result rows "
        "and the business documents used. Pass conversation_id from a previous answer to ask a follow-up."))
    def ask_data(question: str, conversation_id: str | None = None) -> dict:
        payload = {"message": question}
        if conversation_id:
            payload["conversation_id"] = conversation_id
        out = client.call("POST", "/ask", json=payload)
        return {"answer": out["answer"], "interpreted_as": out.get("interpreted_as"), "sql": out.get("sql", ""),
                "columns": out.get("columns", []), "rows": out.get("rows", [])[:MAX_ROWS],
                "rows_shown": min(len(out.get("rows", [])), MAX_ROWS), "row_count": len(out.get("rows", [])),
                "truncated": out.get("truncated", False),
                "sources": [s["document_id"] for s in out.get("sources") or []],
                "conversation_id": out.get("conversation_id")}

    @server.tool(description=(
        "Search the company's business documents: metric definitions, business rules such as the fiscal "
        "calendar, policies, validated example queries and incident reports. Returns the closest documents "
        "the signed-in user may read, with an excerpt of each."))
    def search_knowledge(query: str) -> dict:
        out = client.call("GET", "/knowledge/search", params={"q": query})
        return {"documents": [{"document_id": h["document_id"], "title": h["title"], "type": h["doc_type"],
                               "version": h["version"], "score": h["score"],
                               "excerpt": h["content"][:EXCERPT_CHARS]} for h in out["hits"]]}

    return server


def client_from_env():
    username, password = os.getenv("BI_AGENT_USERNAME"), os.getenv("BI_AGENT_PASSWORD")
    if not username or not password:
        raise SystemExit("Set BI_AGENT_USERNAME and BI_AGENT_PASSWORD for the BI Agent user this server signs in as.")
    return BackendClient(os.getenv("BI_AGENT_URL", "http://localhost:8000"), username, password)


if __name__ == "__main__":
    build_server(client_from_env()).run("stdio")
    sys.exit(0)
