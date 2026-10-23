"""The knowledge pack (RAG R1): business documents with a TOML header, checked strictly.

Each file in backend/knowledge/ starts with a header between two "+++" lines, followed by Markdown.
The files are the source of truth and are reviewed in git; the vector index is derived from them.
A malformed pack raises KnowledgeError, naming the file and the problem.
"""
import hashlib
import re
import tomllib
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from app import catalog, policy

KNOWLEDGE_DIR = Path(__file__).resolve().parents[2] / "knowledge"
TYPES = ("metric", "rule", "sql_example", "dashboard", "data_quality", "document")
STATUSES = ("active", "superseded")
DOMAINS = tuple(catalog.DOMAINS) + ("Finance", "Company")
REQUIRED = ("id", "type", "title", "domain", "owner", "source", "version", "effective_date", "status", "access_groups")
OPTIONAL = ("tables", "superseded_by", "supersedes")
BY_TYPE = {
    "metric": (("metric", "authoritative"), ()),
    "sql_example": (("question", "sql", "result_columns"), ("assumptions",)),
}
NEEDS_TABLES = ("metric", "rule", "sql_example", "dashboard")
HEADER = re.compile(r"\A\+\+\+\n(.*?)\n\+\+\+\n(.*)\Z", re.DOTALL)


class KnowledgeError(Exception):
    """A knowledge document is missing, unreadable or inconsistent with the others."""


@dataclass(frozen=True)
class Document:
    id: str
    type: str
    title: str
    domain: str
    owner: str
    source: str
    version: int
    effective_date: date
    status: str
    access_groups: tuple
    tables: tuple
    body: str
    path: Path
    superseded_by: str = ""
    supersedes: str = ""
    metric: str = ""
    authoritative: bool = False
    question: str = ""
    sql: str = ""
    result_columns: tuple = ()
    assumptions: tuple = ()

    @property
    def content_hash(self):
        return hashlib.sha256(self.body.strip().encode()).hexdigest()


def _strings(value, where, allow_empty=False):
    if not isinstance(value, list) or (not value and not allow_empty) or \
            not all(isinstance(v, str) and v.strip() for v in value):
        raise KnowledgeError(f"{where} must be a {'' if allow_empty else 'non-empty '}list of text.")
    return tuple(value)


def _text(value, where):
    if not isinstance(value, str) or not value.strip():
        raise KnowledgeError(f"{where} must be non-empty text.")
    return value.strip()


def _parse(path, groups, tables):
    m = HEADER.match(path.read_text())
    if not m:
        raise KnowledgeError(f"{path.name}: no header between +++ lines at the top of the file.")
    try:
        h = tomllib.loads(m.group(1))
    except tomllib.TOMLDecodeError as e:
        raise KnowledgeError(f"{path.name}: the header could not be read: {e}") from e
    where = path.name
    kind = h.get("type")
    if kind not in TYPES:
        raise KnowledgeError(f"{where}: type must be one of {', '.join(TYPES)}.")
    required, optional = BY_TYPE.get(kind, ((), ()))
    allowed = set(REQUIRED) | set(OPTIONAL) | set(required) | set(optional)
    unknown = sorted(set(h) - allowed)
    if unknown:
        raise KnowledgeError(f"{where}: unknown key {', '.join(unknown)}.")
    missing = [k for k in REQUIRED + required if k not in h]
    if kind in NEEDS_TABLES and "tables" not in h:
        missing.append("tables")
    if missing:
        raise KnowledgeError(f"{where}: missing {', '.join(missing)}.")
    if h["id"] != path.stem:
        raise KnowledgeError(f"{where}: id {h['id']!r} must equal the file name {path.stem!r}.")
    if h["domain"] not in DOMAINS:
        raise KnowledgeError(f"{where}: domain must be one of {', '.join(DOMAINS)}.")
    if h["status"] not in STATUSES:
        raise KnowledgeError(f"{where}: status must be active or superseded.")
    if isinstance(h["version"], bool) or not isinstance(h["version"], int) or h["version"] < 1:
        raise KnowledgeError(f"{where}: version must be a whole number of at least 1.")
    if not isinstance(h["effective_date"], date):
        raise KnowledgeError(f"{where}: effective_date must be a date such as 2025-02-01.")
    access = _strings(h["access_groups"], f"{where} access_groups")
    unknown_groups = sorted(set(access) - set(groups))
    if unknown_groups:
        raise KnowledgeError(f"{where}: unknown access group {', '.join(unknown_groups)}.")
    named = _strings(h.get("tables", []), f"{where} tables", allow_empty=True)
    unknown_tables = sorted(set(named) - set(tables))
    if unknown_tables:
        raise KnowledgeError(f"{where}: unknown table {', '.join(unknown_tables)}.")
    for group in access:                          # knowledge access must match data access
        hidden = sorted(set(named) - set(groups[group]))
        if hidden:
            raise KnowledgeError(f"{where}: shared with {group}, who cannot read {', '.join(hidden)}.")
    if h["status"] == "superseded" and not h.get("superseded_by"):
        raise KnowledgeError(f"{where}: a superseded document needs superseded_by.")
    body = m.group(2).strip()
    if not body:
        raise KnowledgeError(f"{where}: the body is empty.")
    extra = {}
    if kind == "metric":
        extra = {"metric": _text(h["metric"], f"{where} metric"), "authoritative": h["authoritative"]}
        if not isinstance(h["authoritative"], bool):
            raise KnowledgeError(f"{where}: authoritative must be true or false.")
    if kind == "sql_example":
        extra = {"question": _text(h["question"], f"{where} question"), "sql": _text(h["sql"], f"{where} sql"),
                 "result_columns": _strings(h["result_columns"], f"{where} result_columns"),
                 "assumptions": _strings(h.get("assumptions", []), f"{where} assumptions", allow_empty=True)}
    return Document(id=h["id"], type=kind, title=_text(h["title"], f"{where} title"), domain=h["domain"],
                    owner=_text(h["owner"], f"{where} owner"), source=_text(h["source"], f"{where} source"),
                    version=h["version"], effective_date=h["effective_date"], status=h["status"],
                    access_groups=access, tables=named, body=body, path=path,
                    superseded_by=h.get("superseded_by", ""), supersedes=h.get("supersedes", ""), **extra)


def _check_pack(docs):
    by_id = {}
    for d in docs:
        if d.id in by_id:
            raise KnowledgeError(f"{d.path.name}: id {d.id} is used twice.")
        by_id[d.id] = d
    hashes = {}
    for d in docs:
        if d.content_hash in hashes:
            raise KnowledgeError(f"{d.path.name} has the same content as {hashes[d.content_hash]}.")
        hashes[d.content_hash] = d.path.name
    for d in docs:
        if d.superseded_by:
            new = by_id.get(d.superseded_by)
            if new is None or new.status != "active" or new.type != d.type or new.version <= d.version:
                raise KnowledgeError(f"{d.path.name}: superseded_by {d.superseded_by!r} must be an active "
                                     "document of the same type with a higher version.")
        if d.supersedes:
            old = by_id.get(d.supersedes)
            if old is None or old.superseded_by != d.id:
                raise KnowledgeError(f"{d.path.name}: supersedes {d.supersedes!r}, which does not point back.")
    metrics = {}
    for d in docs:
        if d.type == "metric" and d.status == "active":
            metrics.setdefault(d.metric, []).append(d)
    for name, ds in metrics.items():
        count = sum(x.authoritative for x in ds)
        if count != 1:
            raise KnowledgeError(f"metric {name}: {count} active authoritative definitions; exactly one is required.")


def load(path=None):
    """Every document in the knowledge folder, checked individually and as a pack."""
    root = Path(path or KNOWLEDGE_DIR)
    files = sorted(root.rglob("*.md"))
    if not files:
        raise KnowledgeError(f"No knowledge documents in {root}.")
    p = policy.get()
    roles = p.sources["retail"].roles
    groups = {name: role.tables for name, role in roles.items()}
    tables = set(catalog.get().tables)
    docs = [_parse(f, groups, tables) for f in files]
    _check_pack(docs)
    return docs
