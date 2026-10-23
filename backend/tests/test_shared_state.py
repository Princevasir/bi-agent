"""Demo gap D11: conversations, the sign-in throttle and the token budget shared by every backend instance.

With STATE_STORE=postgres each piece of state lives in appdb, so two backend processes (here: two
objects) see the same conversations, lockouts and spending. The default stays in memory.
"""
import psycopg
import pytest

from app import appdb
from app.bi import conversation
from app.bi.conversation import ConversationStore, Turn
from app.llm import budget
from app.llm.base import LLMBudgetError
from app.llm.budget import TokenBudget
from app.throttle import LoginThrottle
from app import throttle as throttle_module

ADMIN = "postgresql://admin:admin_dev_pw@localhost:5433/appdb"
PREFIX = "d11test"


class Clock:
    def __init__(self):
        self.now = 1_000_000.0

    def __call__(self):
        return self.now


@pytest.fixture
def clean():
    def wipe():
        with psycopg.connect(ADMIN, autocommit=True) as conn:
            conn.execute("DELETE FROM conversations WHERE key LIKE %s", (PREFIX + "%",))
            conn.execute("DELETE FROM login_failures WHERE username LIKE %s", (PREFIX + "%",))
            conn.execute("DELETE FROM login_locks WHERE username LIKE %s", (PREFIX + "%",))
            conn.execute("DELETE FROM token_usage WHERE username LIKE %s", (PREFIX + "%",))
    wipe()
    yield
    wipe()


def turn(n):
    return Turn(question=f"q{n}", sql="SELECT 1", columns=["region", "revenue"], rows=[["North", 270.5]], answer=f"a{n}")


# ---- conversations -------------------------------------------------------------------------------------------

pytestmark = pytest.mark.integration


def test_a_conversation_written_by_one_instance_is_read_by_another(clean):
    first, second = appdb.PgConversationStore(), appdb.PgConversationStore()
    first.add(f"{PREFIX}:alice:c1", turn(1))
    assert second.get(f"{PREFIX}:alice:c1") == [turn(1)]


def test_an_unknown_conversation_is_none(clean):
    assert appdb.PgConversationStore().get(f"{PREFIX}:nobody:c9") is None


def test_only_the_last_turns_are_kept(clean):
    store = appdb.PgConversationStore(max_turns=3)
    for n in range(5):
        store.add(f"{PREFIX}:alice:c1", turn(n))
    assert [t.question for t in store.get(f"{PREFIX}:alice:c1")] == ["q2", "q3", "q4"]


def test_the_oldest_conversations_are_dropped_beyond_the_cap(clean):
    clock = Clock()
    store = appdb.PgConversationStore(max_conversations=2, clock=clock, key_prefix=PREFIX)
    for n in range(3):
        clock.now += 1
        store.add(f"{PREFIX}:alice:c{n}", turn(n))
    assert store.get(f"{PREFIX}:alice:c0") is None and store.get(f"{PREFIX}:alice:c2") == [turn(2)]


def test_conversations_never_touch_other_rows(clean):
    with psycopg.connect(ADMIN, autocommit=True) as conn:
        before = conn.execute("SELECT count(*) FROM conversations WHERE key NOT LIKE %s", (PREFIX + "%",)).fetchone()
    store = appdb.PgConversationStore(max_conversations=1, key_prefix=PREFIX)
    store.add(f"{PREFIX}:a:1", turn(1))
    store.add(f"{PREFIX}:a:2", turn(2))
    with psycopg.connect(ADMIN, autocommit=True) as conn:
        after = conn.execute("SELECT count(*) FROM conversations WHERE key NOT LIKE %s", (PREFIX + "%",)).fetchone()
    assert before == after


# ---- the sign-in throttle -----------------------------------------------------------------------------------

def test_a_lockout_is_seen_by_every_instance(clean):
    clock = Clock()
    first, second = appdb.PgLoginThrottle(clock=clock), appdb.PgLoginThrottle(clock=clock)
    name = f"{PREFIX}-mallory"
    for _ in range(5):
        first.record_failure(name)
    assert second.is_locked(name)
    clock.now += 15 * 60 + 1
    assert not second.is_locked(name)


def test_failures_outside_the_window_do_not_count(clean):
    clock = Clock()
    t = appdb.PgLoginThrottle(clock=clock)
    name = f"{PREFIX}-slow"
    for _ in range(4):
        t.record_failure(name)
    clock.now += 15 * 60 + 1
    t.record_failure(name)
    assert not t.is_locked(name)


def test_a_success_clears_the_failures(clean):
    t = appdb.PgLoginThrottle(clock=Clock())
    name = f"{PREFIX}-forgetful"
    for _ in range(4):
        t.record_failure(name)
    t.record_success(name)
    t.record_failure(name)
    assert not t.is_locked(name)


# ---- the token budget ---------------------------------------------------------------------------------------

def test_spending_is_shared_between_instances(clean):
    clock = Clock()
    a = TokenBudget(1000, per_user=100, clock=clock, ledger=appdb.PgTokenLedger())
    b = TokenBudget(1000, per_user=100, clock=clock, ledger=appdb.PgTokenLedger())
    a.record(100, user=f"{PREFIX}-alice")
    with pytest.raises(LLMBudgetError):
        b.check(user=f"{PREFIX}-alice")
    clock.now += 3601
    b.check(user=f"{PREFIX}-alice")


def test_the_memory_ledger_still_works_the_same():
    clock = Clock()
    b = TokenBudget(100, clock=clock)
    b.record(100)
    with pytest.raises(LLMBudgetError):
        b.check()


# ---- choosing the store -----------------------------------------------------------------------------------------

def test_memory_is_the_default(monkeypatch):
    monkeypatch.delenv("STATE_STORE", raising=False)
    assert type(conversation.from_env()) is ConversationStore
    assert type(throttle_module.from_env()) is LoginThrottle
    assert budget.from_env().ledger.__class__.__name__ == "MemoryLedger"


def test_postgres_is_chosen_by_state_store(monkeypatch):
    monkeypatch.setenv("STATE_STORE", "postgres")
    assert isinstance(conversation.from_env(), appdb.PgConversationStore)
    assert isinstance(throttle_module.from_env(), appdb.PgLoginThrottle)
    assert isinstance(budget.from_env().ledger, appdb.PgTokenLedger)


def test_an_unknown_store_is_refused(monkeypatch):
    monkeypatch.setenv("STATE_STORE", "redis")
    with pytest.raises(ValueError, match="STATE_STORE"):
        conversation.from_env()


def test_spending_recorded_after_now_is_not_counted(clean):
    # Another instance's clock may run ahead; only spending inside [now - window, now] counts.
    clock = Clock()
    ahead = TokenBudget(1000, clock=lambda: clock.now + 600, ledger=appdb.PgTokenLedger())
    ahead.record(5000, user=f"{PREFIX}-skewed")
    TokenBudget(1000, clock=clock, ledger=appdb.PgTokenLedger()).check(user=f"{PREFIX}-other")


def test_the_memory_ledger_also_ignores_the_future():
    clock = Clock()
    ledger = budget.MemoryLedger()
    TokenBudget(100, clock=lambda: clock.now + 600, ledger=ledger).record(500)
    TokenBudget(100, clock=clock, ledger=ledger).check()
