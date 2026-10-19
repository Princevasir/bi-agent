RECENT_TURNS = 3


def rewrite_prompt(question, history, today):
    recent = history[-RECENT_TURNS:]
    context = "\n".join(f"Q: {t.question}\nSQL: {t.sql}" for t in recent)
    return (
        "Rewrite the latest question as ONE standalone question that makes sense "
        "without the conversation. If it is already standalone, return it unchanged. "
        "Resolve references such as 'that', 'the same', 'by month' or 'what about August'. "
        "Keep every explicit date and number from the latest question. "
        "Return only the question.\n\n"
        f"Today's date: {today.isoformat()}\n\n"
        f"Conversation so far:\n{context}\n\n"
        f"Latest question: {question}\nStandalone question:"
    )