import uuid
from collections import OrderedDict
from dataclasses import dataclass
from threading import Lock

MAX_CONVERSATIONS = 100
MAX_TURNS = 20
MAX_STORED_ROWS = 50


@dataclass
class Turn:
    question: str
    sql: str
    columns: list
    rows: list
    answer: str


class ConversationStore:
    def __init__(self, max_conversations=MAX_CONVERSATIONS, max_turns=MAX_TURNS):
        self.max_conversations = max_conversations
        self.max_turns = max_turns
        self._data = OrderedDict()
        self._lock = Lock()

    def new_id(self):
        return str(uuid.uuid4())

    def get(self, conversation_id):
        with self._lock:
            turns = self._data.get(conversation_id)
            if turns is None:
                return None
            self._data.move_to_end(conversation_id)
            return list(turns)

    def add(self, conversation_id, turn):
        with self._lock:
            turns = self._data.setdefault(conversation_id, [])
            turns.append(turn)
            del turns[:-self.max_turns]
            self._data.move_to_end(conversation_id)
            while len(self._data) > self.max_conversations:
                self._data.popitem(last=False)

def from_env():
    """In memory (one process) or in appdb (every instance, STATE_STORE=postgres; demo gap D11)."""
    from app.appdb import PgConversationStore, state_store
    return PgConversationStore() if state_store() == "postgres" else ConversationStore()
