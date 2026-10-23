"""RAG R3: turning text into vectors, locally (Ollama) or deterministically (tests)."""
import math

import httpx
import psycopg
import pytest

from app import policy
from app.knowledge.embeddings import EmbeddingError, FakeEmbedder, OllamaEmbedder, get_embedder

DIMS = 768


class Transport:
    """Records requests and answers with canned bodies (or raises)."""

    def __init__(self, *answers):
        self.answers, self.requests = list(answers), []

    def post(self, url, json=None, **kw):
        self.requests.append((url, json))
        answer = self.answers.pop(0)
        if isinstance(answer, Exception):
            raise answer
        status, body = answer
        req = httpx.Request("POST", url)
        return httpx.Response(status, json=body, request=req)


def vectors(n, dims=DIMS, value=0.1):
    return {"data": [{"index": i, "embedding": [value] * dims} for i in range(n)]}


def cosine(a, b):
    return sum(x * y for x, y in zip(a, b)) / (math.sqrt(sum(x * x for x in a)) * math.sqrt(sum(y * y for y in b)))


# ---- the fake embedder ---------------------------------------------------------------------------------

def test_fake_vectors_are_deterministic_normalised_and_sized():
    e = FakeEmbedder(DIMS)
    [a] = e.embed_documents(["Revenue counts completed orders only."])
    assert a == e.embed_documents(["Revenue counts completed orders only."])[0]
    assert len(a) == DIMS and abs(math.sqrt(sum(x * x for x in a)) - 1) < 1e-9


def test_fake_vectors_put_related_text_closer():
    e = FakeEmbedder(DIMS)
    q = e.embed_query("how is revenue defined for completed orders")
    revenue, supplier = e.embed_documents(["Revenue is money paid for completed orders.",
                                           "Summit Tentworks supplies tents and sleeping bags."])
    assert cosine(q, revenue) > cosine(q, supplier)


# ---- the Ollama embedder, against a stand-in transport ---------------------------------------------------

def test_requests_go_to_ollama_with_nomic_task_prefixes():
    t = Transport((200, vectors(2)), (200, vectors(1)))
    e = OllamaEmbedder("http://localhost:11434/v1", "nomic-embed-text", DIMS, client=t)
    e.embed_documents(["a", "b"])
    e.embed_query("c")
    (url, body), (_, query) = t.requests
    assert url == "http://localhost:11434/v1/embeddings" and body["model"] == "nomic-embed-text"
    assert body["input"] == ["search_document: a", "search_document: b"]
    assert query["input"] == ["search_query: c"]


def test_other_models_get_no_prefixes():
    t = Transport((200, vectors(1)))
    OllamaEmbedder("http://x/v1", "mxbai-embed-large", DIMS, client=t).embed_documents(["a"])
    assert t.requests[0][1]["input"] == ["a"]


def test_texts_are_sent_in_batches():
    t = Transport((200, vectors(32)), (200, vectors(32)), (200, vectors(6)))
    out = OllamaEmbedder("http://x/v1", "nomic-embed-text", DIMS, client=t).embed_documents(["t"] * 70)
    assert len(out) == 70 and [len(b["input"]) for _, b in t.requests] == [32, 32, 6]


def test_vectors_come_back_in_input_order():
    body = {"data": [{"index": 1, "embedding": [0.2] * DIMS}, {"index": 0, "embedding": [0.1] * DIMS}]}
    out = OllamaEmbedder("http://x/v1", "m", DIMS, client=Transport((200, body))).embed_documents(["a", "b"])
    assert out[0][0] == 0.1 and out[1][0] == 0.2


@pytest.mark.parametrize("answer,mentions", [
    ((200, vectors(1)), "expected 2"),                                          # too few vectors
    ((200, vectors(2, dims=384)), "384"),                                       # wrong size
    ((200, {"data": [{"index": 0, "embedding": ["x"] * DIMS},                # JSON cannot carry NaN
                     {"index": 1, "embedding": [0.1] * DIMS}]}), "finite"),
    ((200, {"oops": True}), "unexpected"),
    ((500, {"error": "boom"}), "HTTP 500"),
    ((404, {"error": "model not found"}), "HTTP 404"),
    (httpx.ConnectError("refused"), "reach"),
    (httpx.ReadTimeout("slow"), "timed out"),
])
def test_bad_answers_raise_embedding_errors(answer, mentions):
    e = OllamaEmbedder("http://x/v1", "nomic-embed-text", DIMS, client=Transport(answer))
    with pytest.raises(EmbeddingError, match=mentions):
        e.embed_documents(["a", "b"])


def test_the_model_is_named_for_the_index():
    assert OllamaEmbedder("http://x/v1", "nomic-embed-text", DIMS, client=Transport()).model_id == "ollama:nomic-embed-text"
    assert FakeEmbedder(DIMS).model_id == f"fake:{DIMS}"


# ---- configuration ----------------------------------------------------------------------------------------

def test_dimensions_come_from_the_policy():
    assert policy.get().knowledge["embedding_dimensions"] == DIMS


def test_choosing_the_embedder(monkeypatch):
    monkeypatch.setenv("EMBEDDING_PROVIDER", "fake")
    assert isinstance(get_embedder(), FakeEmbedder)
    monkeypatch.setenv("EMBEDDING_PROVIDER", "ollama")
    monkeypatch.setenv("OLLAMA_BASE_URL", "http://host.docker.internal:11434/v1/")
    e = get_embedder()
    assert isinstance(e, OllamaEmbedder) and e.url == "http://host.docker.internal:11434/v1/embeddings"
    assert e.model == "nomic-embed-text" and e.dimensions == DIMS
    monkeypatch.setenv("EMBEDDING_PROVIDER", "telepathy")
    with pytest.raises(EmbeddingError, match="EMBEDDING_PROVIDER"):
        get_embedder()


@pytest.mark.integration
def test_policy_dimensions_match_the_database_column():
    with psycopg.connect("postgresql://admin:admin_dev_pw@localhost:5433/appdb") as conn:
        [(dtype,)] = conn.execute("""SELECT format_type(atttypid, atttypmod) FROM pg_attribute
                                     WHERE attrelid = 'knowledge.chunks'::regclass AND attname = 'embedding'""").fetchall()
    assert dtype == f"vector({policy.get().knowledge['embedding_dimensions']})"


# ---- the real local model -------------------------------------------------------------------------------------

@pytest.mark.integration
def test_the_local_model_ranks_related_text_first():
    try:
        e = OllamaEmbedder("http://localhost:11434/v1", "nomic-embed-text", DIMS)
        q = e.embed_query("How is net revenue calculated after refunds?")
    except EmbeddingError as err:
        pytest.skip(f"local Ollama not available: {err}")
    docs = e.embed_documents(["Net revenue is revenue minus refunds paid for returned items.",
                              "Summit Tentworks supplies tents and sleeping bags.",
                              "Stores open at nine and close at seven."])
    scores = [cosine(q, d) for d in docs]
    assert len(q) == DIMS and scores[0] == max(scores)
