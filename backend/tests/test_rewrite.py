from datetime import date

from app.bi.conversation import Turn
from app.bi.rewrite import rewrite_prompt


def t(n):
    return Turn(question=f"question {n}", sql=f"SELECT {n}", columns=["a"],
                rows=[[n]], answer=f"SECRET answer {n}")


def test_rewrite_prompt_contains_context():
    p = rewrite_prompt("What about August?", [t(1)], date(2026, 10, 19))
    assert p.startswith("Rewrite")
    for expected in ("question 1", "SELECT 1", "What about August?", "2026-10-19"):
        assert expected in p


def test_rewrite_prompt_uses_last_three_turns_and_no_answers():
    p = rewrite_prompt("next", [t(1), t(2), t(3), t(4)], date(2026, 10, 19))
    assert "question 1" not in p
    assert "question 4" in p
    assert "SECRET" not in p