"""Ingesting the knowledge pack into the index (RAG R4).

    cd backend && .venv/bin/python -m app.knowledge.ingest [--rebuild]

Repeatable and incremental: a document whose fingerprint (metadata, text, chunker version and
embedding model) is unchanged is skipped; a changed one is re-chunked, and only chunks whose text is
new are embedded again; files that disappeared leave the index. Superseded documents are stored
without chunks, so they are never retrieved. If embedding fails for a document, its previous version
stays in the index and the run reports the failure.
"""
import argparse
import hashlib
import json
import logging
import os
import sys
from dataclasses import dataclass, field

from app.knowledge.chunking import chunk
from app.knowledge.documents import KNOWLEDGE_DIR, load
from app.knowledge.embeddings import EmbeddingError, get_embedder
from app.knowledge.store import Index, IndexError

CHUNKER_VERSION = "1"
DEFAULT_URL = "postgresql://knowledge_writer:knowledge_writer_dev_pw@localhost:5433/appdb"
logger = logging.getLogger(__name__)


@dataclass
class Report:
    added: int = 0
    changed: int = 0
    unchanged: int = 0
    removed: int = 0
    failed: int = 0
    errors: list = field(default_factory=list)


def fingerprint(doc, model):
    meta = {k: v for k, v in doc.__dict__.items() if k not in ("path", "body")}
    payload = json.dumps(meta, default=str, sort_keys=True) + doc.body + CHUNKER_VERSION + model
    return hashlib.sha256(payload.encode()).hexdigest()


def plan(current, indexed):
    """Which documents are new, changed, unchanged or gone, by fingerprint."""
    return {
        "added": sorted(set(current) - set(indexed)),
        "changed": sorted(d for d in set(current) & set(indexed) if current[d] != indexed[d]),
        "unchanged": sorted(d for d in set(current) & set(indexed) if current[d] == indexed[d]),
        "removed": sorted(set(indexed) - set(current)),
    }


def ingest(path, embedder, url=None, schema="knowledge", rebuild=False):
    docs = {d.id: d for d in load(path)}
    index = Index(url or os.getenv("KNOWLEDGE_DATABASE_URL", DEFAULT_URL), schema)
    models = index.models()
    if models and models != {embedder.model_id} and not rebuild:
        raise IndexError(f"The index holds vectors from {', '.join(sorted(models))}; run with --rebuild "
                         f"to re-embed everything with {embedder.model_id}.")
    current = {doc_id: fingerprint(d, embedder.model_id) for doc_id, d in docs.items()}
    steps = plan(current, index.fingerprints())
    reuse = index.vectors_by_content(embedder.model_id)
    report = Report(unchanged=len(steps["unchanged"]))
    run_id = index.start_run(embedder.model_id)
    for kind in ("added", "changed"):
        for doc_id in steps[kind]:
            doc = docs[doc_id]
            chunks = chunk(doc) if doc.status == "active" else []
            new = [c for c in chunks if c.content_hash not in reuse]
            try:
                vectors = dict(zip((c.content_hash for c in new), embedder.embed_documents([c.content for c in new])))
            except EmbeddingError as e:
                report.failed += 1
                report.errors.append(f"{doc_id}: {e}")
                logger.warning("knowledge_embedding_failed", extra={"document_id": doc_id, "error": str(e)})
                continue
            index.write_document(doc, current[doc_id], chunks, {**reuse, **vectors}, embedder.model_id)
            setattr(report, kind, getattr(report, kind) + 1)
    index.delete_documents(steps["removed"])
    report.removed = len(steps["removed"])
    index.finish_run(run_id, report)
    return report


def main(argv=None):
    p = argparse.ArgumentParser(description="Index the knowledge pack for retrieval.")
    p.add_argument("--dir", default=str(KNOWLEDGE_DIR))
    p.add_argument("--rebuild", action="store_true", help="re-embed everything (after changing the embedding model)")
    args = p.parse_args(argv)
    embedder = get_embedder()
    report = ingest(args.dir, embedder, rebuild=args.rebuild)
    print(f"model {embedder.model_id}: {report.added} added, {report.changed} changed, {report.unchanged} unchanged, "
          f"{report.removed} removed, {report.failed} failed")
    for error in report.errors:
        print(f"  failed: {error}", file=sys.stderr)
    return 1 if report.failed else 0


if __name__ == "__main__":
    sys.exit(main())
