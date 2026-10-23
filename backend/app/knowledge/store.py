"""The knowledge index in Postgres (RAG R4): the only module that writes it.

Uses its own login (knowledge_writer), which can write the knowledge tables and nothing else.
Each document is written in one transaction, so a failure leaves the previous version in place.
"""
import re

import psycopg

SCHEMA_NAME = re.compile(r"^[a-z_][a-z0-9_]*$")


class IndexError(Exception):
    """The index cannot be used as asked (bad schema name, mixed embedding models)."""


def vector_literal(values):
    return "[" + ",".join(repr(float(v)) for v in values) + "]"


def parse_vector(text):
    return [float(x) for x in text.strip("[]").split(",")]


class Index:
    def __init__(self, url, schema="knowledge"):
        if not SCHEMA_NAME.match(schema):
            raise IndexError(f"Not a valid schema name: {schema!r}")
        self.url, self.schema = url, schema

    def _connect(self):
        return psycopg.connect(self.url, connect_timeout=5)

    def fingerprints(self):
        with self._connect() as conn:
            return dict(conn.execute(f"SELECT document_id, content_hash FROM {self.schema}.documents").fetchall())

    def models(self):
        with self._connect() as conn:
            return {r[0] for r in conn.execute(f"SELECT DISTINCT embedding_model FROM {self.schema}.chunks")}

    def vectors_by_content(self, model):
        """Embeddings already in the index for this model, keyed by chunk content hash."""
        with self._connect() as conn:
            rows = conn.execute(f"SELECT content_hash, embedding::text FROM {self.schema}.chunks "
                                "WHERE embedding_model = %s", (model,)).fetchall()
        return {h.strip(): parse_vector(v) for h, v in rows}

    def write_document(self, doc, fingerprint, chunks, vectors, model):
        with self._connect() as conn:
            conn.execute(f"""
                INSERT INTO {self.schema}.documents (document_id, doc_type, title, domain, owner, source, version,
                    effective_date, status, access_groups, tables, content_hash, path, updated_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, now())
                ON CONFLICT (document_id) DO UPDATE SET doc_type = EXCLUDED.doc_type, title = EXCLUDED.title,
                    domain = EXCLUDED.domain, owner = EXCLUDED.owner, source = EXCLUDED.source,
                    version = EXCLUDED.version, effective_date = EXCLUDED.effective_date, status = EXCLUDED.status,
                    access_groups = EXCLUDED.access_groups, tables = EXCLUDED.tables,
                    content_hash = EXCLUDED.content_hash, path = EXCLUDED.path, updated_at = now()""",
                         (doc.id, doc.type, doc.title, doc.domain, doc.owner, doc.source, doc.version,
                          doc.effective_date, doc.status, list(doc.access_groups), list(doc.tables), fingerprint,
                          str(doc.path.name)))
            conn.execute(f"DELETE FROM {self.schema}.chunks WHERE document_id = %s", (doc.id,))
            for c in chunks:
                conn.execute(f"""INSERT INTO {self.schema}.chunks (chunk_id, document_id, position, content,
                                 content_hash, token_count, embedding, embedding_model)
                                 VALUES (%s, %s, %s, %s, %s, %s, %s::vector, %s)""",
                             (c.chunk_id, c.document_id, c.position, c.content, c.content_hash, c.token_count,
                              vector_literal(vectors[c.content_hash]), model))

    def delete_documents(self, ids):
        if ids:
            with self._connect() as conn:
                conn.execute(f"DELETE FROM {self.schema}.documents WHERE document_id = ANY(%s)", (list(ids),))

    def start_run(self, model):
        with self._connect() as conn:
            return conn.execute(f"INSERT INTO {self.schema}.ingestion_runs (embedding_model) VALUES (%s) "
                                "RETURNING run_id", (model,)).fetchone()[0]

    def finish_run(self, run_id, report):
        with self._connect() as conn:
            conn.execute(f"""UPDATE {self.schema}.ingestion_runs SET finished_at = now(), added = %s, changed = %s,
                             unchanged = %s, removed = %s, failed = %s, error = %s WHERE run_id = %s""",
                         (report.added, report.changed, report.unchanged, report.removed, report.failed,
                          "; ".join(report.errors) or None, run_id))
