"""Normalising and chunking knowledge documents (RAG R4).

Each chunk starts with a context line (title, type, domain, owner, version) so it can be understood
and cited on its own. A SQL example is always one chunk, so the question, the query and the
explanation are never separated. Short documents are one chunk. Long ones are split at their "## "
headings: a section shorter than MIN_TOKENS is merged with the next one, and a section longer than
MAX_TOKENS is split at paragraph breaks, each part keeping its heading.
"""
import hashlib
import math
import re
from dataclasses import dataclass

MIN_TOKENS = 80
MAX_TOKENS = 600


@dataclass(frozen=True)
class Chunk:
    chunk_id: str
    document_id: str
    position: int
    content: str
    content_hash: str
    token_count: int


def normalise(text):
    text = text.replace("\r\n", "\n").replace("\r", "\n").replace(" ", " ")
    text = "\n".join(line.rstrip() for line in text.split("\n"))
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def tokens(text):
    """Approximate token count: about four tokens for every three words."""
    return math.ceil(len(text.split()) * 4 / 3)


def context_line(doc):
    return f"{doc.title} ({doc.type}, {doc.domain}, owner {doc.owner}, version {doc.version})"


def _sections(body):
    """The text before the first "## " heading, then one piece per heading."""
    parts, current = [], []
    for line in body.split("\n"):
        if line.startswith("## ") and current:
            parts.append("\n".join(current).strip())
            current = []
        current.append(line)
    parts.append("\n".join(current).strip())
    return [p for p in parts if p]


def _split_long(section, budget):
    """Split one long section at paragraph breaks, repeating its heading on each part."""
    lines = section.split("\n")
    heading = lines[0] if lines[0].startswith("## ") else ""
    paragraphs = [p for p in "\n".join(lines[1:] if heading else lines).split("\n\n") if p.strip()]
    pieces, current = [], []
    for para in paragraphs:
        if current and tokens("\n\n".join(current + [para])) > budget:
            pieces.append(current)
            current = []
        current.append(para)
    pieces.append(current)
    return [(heading + "\n\n" if heading else "") + "\n\n".join(p) for p in pieces if p]


def _make(doc, texts):
    out = []
    for position, text in enumerate(texts):
        content = f"{context_line(doc)}\n\n{text}"
        out.append(Chunk(f"{doc.id}#{position}", doc.id, position, content,
                         hashlib.sha256(content.encode()).hexdigest(), tokens(content)))
    return out


def chunk(doc):
    body = normalise(doc.body)
    if doc.type == "sql_example":
        parts = [f"Question: {doc.question}", f"SQL:\n```sql\n{normalise(doc.sql)}\n```"]
        if doc.assumptions:
            parts.append("Assumptions: " + "; ".join(doc.assumptions) + ".")
        return _make(doc, ["\n\n".join(parts + [body])])
    budget = MAX_TOKENS - tokens(context_line(doc)) - 8
    if doc.type != "document" and tokens(body) <= budget:
        return _make(doc, [body])
    pieces = []
    for section in _sections(body):
        pieces += _split_long(section, budget) if tokens(section) > budget else [section]
    merged, current = [], ""
    for piece in pieces:
        candidate = f"{current}\n\n{piece}" if current else piece
        if current and tokens(current) >= MIN_TOKENS:
            merged.append(current)
            candidate = piece
        elif current and tokens(candidate) > budget:
            merged.append(current)
            candidate = piece
        current = candidate
    if current:
        merged.append(current)
    return _make(doc, merged)
