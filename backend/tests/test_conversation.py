import uuid

import pytest
from fastapi.testclient import TestClient

from app.bi.conversation import ConversationStore, Turn
from app.llm import get_llm
from app.main import app
from routed_llm import RoutedLLM

client = TestClient(app)

SEPTEMBER = (
    "SELECT r.name AS region, SUM(o.amount) AS revenue FROM orders o "
    "JOIN regions r ON o.region_id = r.id WHERE o.status = 'completed' "
    "AND o.order_date >= '2026-09-01' AND o.order_date < '2026-10-01' GROUP BY r.name"
)

AUGUST = SEPTEMBER.replace("2026-09-01", "2026-08-01").replace("2026-10-01", "2026-09-01")


def turn(n):
    return Turn(question=f"q{n}", sql="SELECT 1", columns=["a"], rows=[[n]], answer=f"a{n}")


def test_add_and_get():
    store = ConversationStore()
    cid = store.new_id()
    store.add(cid, turn(1))
    assert [t.question for t in store.get(cid)] == ["q1"]


def test_unknown_id_returns_none():
    assert ConversationStore().get("nope") is None


def test_turns_are_capped():
    store = ConversationStore(max_turns=3)
    for n in range(5):
        store.add("c", turn(n))
    assert [t.question for t in store.get("c")] == ["q2", "q3", "q4"]


def test_oldest_conversation_is_evicted():
    store = ConversationStore(max_conversations=2)
    store.add("a", turn(1))
    store.add("b", turn(2))
    store.add("c", turn(3))
    assert store.get("a") is None
    assert store.get("b") and store.get("c")


@pytest.fixture(autouse=True)
def clear_overrides():
    yield
    app.dependency_overrides.clear()


def use(llm):
    app.dependency_overrides[get_llm] = lambda: llm


def ask(message, conversation_id=None):
    return client.post("/ask", json={"message": message, "conversation_id": conversation_id})


@pytest.mark.integration
def test_first_question_creates_a_conversation():
    use(RoutedLLM(SEPTEMBER))
    r = ask("Revenue by region in September 2026?")
    assert r.status_code == 200
    cid = r.json()["conversation_id"]
    uuid.UUID(cid)
    turns = client.get(f"/conversations/{cid}").json()["turns"]
    assert [t["question"] for t in turns] == ["Revenue by region in September 2026?"]


@pytest.mark.integration
def test_second_question_joins_the_same_conversation():
    use(RoutedLLM(SEPTEMBER))
    cid = ask("first question").json()["conversation_id"]
    second = ask("second question", cid)
    assert second.status_code == 200
    assert second.json()["conversation_id"] == cid
    assert len(client.get(f"/conversations/{cid}").json()["turns"]) == 2


@pytest.mark.integration
def test_unknown_conversation_is_404():
    use(RoutedLLM(SEPTEMBER))
    r = ask("hello", str(uuid.uuid4()))
    assert r.status_code == 404
    assert r.json() == {"detail": "Conversation not found."}


@pytest.mark.integration
def test_invalid_conversation_id_is_422():
    use(RoutedLLM(SEPTEMBER))
    assert ask("hello", "not-a-uuid").status_code == 422


@pytest.mark.integration
def test_get_unknown_conversation_is_404():
    assert client.get(f"/conversations/{uuid.uuid4()}").status_code == 404


@pytest.mark.integration
def test_first_turn_never_calls_rewrite():
    llm = RoutedLLM(SEPTEMBER)
    use(llm)
    ask("Revenue by region in September 2026?")
    assert not any(p.startswith("Rewrite") for p in llm.prompts)


@pytest.mark.integration
def test_follow_up_is_rewritten_and_answered():
    use(RoutedLLM(SEPTEMBER))
    cid = ask("What was revenue by region in September 2026?").json()["conversation_id"]
    standalone = "What was revenue by region in August 2026?"
    llm = RoutedLLM(AUGUST, rewrite=standalone)
    use(llm)
    r = ask("What about August?", cid)
    assert r.status_code == 200
    body = r.json()
    assert body["interpreted_as"] == standalone
    assert sorted(body["rows"]) == [["North", 250.0], ["South", 200.0], ["West", 120.0]]
    rewrite_prompts = [p for p in llm.prompts if p.startswith("Rewrite")]
    assert len(rewrite_prompts) == 1
    assert "September 2026" in rewrite_prompts[0]


@pytest.mark.integration
def test_ask_response_includes_a_bar_chart_spec():
    use(RoutedLLM(SEPTEMBER))
    r = ask("What was revenue by region in September 2026?")
    assert r.status_code == 200
    assert r.json()["chart"] == {"type": "bar", "x": "region", "y": "revenue"}


TOTAL = (
    "SELECT SUM(amount) AS revenue FROM orders WHERE status = 'completed' "
    "AND order_date >= '2026-09-01' AND order_date < '2026-10-01'"
)


@pytest.mark.integration
def test_single_value_result_has_no_chart():
    use(RoutedLLM(TOTAL, answer="September revenue was 810."))
    r = ask("What was revenue in September 2026?")
    assert r.status_code == 200
    assert r.json()["rows"] == [[810.0]]
    assert r.json()["chart"] is None