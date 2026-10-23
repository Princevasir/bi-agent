"""RAG R4: normalising, chunking and incrementally indexing the knowledge pack."""
import shutil
from pathlib import Path

import psycopg
import pytest

from app.knowledge import chunking, store
from app.knowledge.documents import KNOWLEDGE_DIR, load
from app.knowledge.embeddings import EmbeddingError, FakeEmbedder
from app.knowledge.ingest import ingest, plan

ADMIN = "postgresql://admin:admin_dev_pw@localhost:5433/appdb"
WRITER = "postgresql://knowledge_writer:knowledge_writer_dev_pw@localhost:5433/appdb"
SCHEMA = "knowledge_test"
DIMS = 768


# ---- normalising and chunking (no database) ---------------------------------------------------------------

def test_normalise_line_endings_spaces_and_blank_lines():
    text = "# Title\r\n\r\n\r\n\r\nSome  text here.   \r\nNext line\t\n\n\n"
    assert chunking.normalise(text) == "# Title\n\nSome  text here.\nNext line"


def docs_by_id():
    return {d.id: d for d in load(KNOWLEDGE_DIR)}


def test_a_metric_is_one_chunk_with_a_context_line():
    [c] = chunking.chunk(docs_by_id()["metric-revenue"])
    assert c.content.startswith("Revenue (metric, Sales, owner Sales Analytics, version 2)")
    assert "SUM(order_items.line_total)" in c.content and c.position == 0 and c.token_count > 0


def test_a_sql_example_is_never_split():
    [c] = chunking.chunk(docs_by_id()["sql-revenue-by-region"])
    assert "What was revenue by region in 2025?" in c.content
    assert "LEFT JOIN regions r ON r.region_id = c.region_id" in c.content and "Guest online orders" in c.content


def test_a_handbook_is_split_at_its_headings_with_context():
    d = docs_by_id()["doc-company-overview"]
    chunks = chunking.chunk(d)
    assert len(chunks) >= 3
    assert all(c.content.startswith("Trailhead Outfitters: company overview") for c in chunks)
    assert any("Where we sell" in c.content and "Boulder Basecamp" in c.content for c in chunks)
    assert [c.position for c in chunks] == list(range(len(chunks)))


def test_small_sections_are_merged_and_nothing_is_lost():
    d = docs_by_id()["doc-shipping-and-fulfilment-policy"]
    chunks = chunking.chunk(d)
    words = set(chunking.normalise(d.body).split())
    assert words <= set(" ".join(c.content for c in chunks).split())
    assert all(c.token_count >= chunking.MIN_TOKENS or len(chunks) == 1 for c in chunks[:-1])


def test_oversized_sections_are_split_by_paragraph():
    d = docs_by_id()["doc-company-overview"]
    long_body = "## Huge\n\n" + "\n\n".join(f"Paragraph {i} " + "word " * 120 for i in range(12))
    chunks = chunking.chunk(d.__class__(**{**d.__dict__, "body": long_body}))
    assert len(chunks) > 1 and all(c.token_count <= chunking.MAX_TOKENS for c in chunks)


def test_every_chunk_of_the_pack_is_within_limits_and_ids_are_stable():
    for d in load(KNOWLEDGE_DIR):
        for c in chunking.chunk(d):
            assert c.chunk_id == f"{d.id}#{c.position}"
            assert d.type == "sql_example" or c.token_count <= chunking.MAX_TOKENS, (d.id, c.token_count)


def test_planning_sorts_documents_into_added_changed_unchanged_and_removed():
    current = {"a": "1", "b": "2", "c": "3"}
    indexed = {"b": "2", "c": "old", "z": "9"}
    assert plan(current, indexed) == {"added": ["a"], "changed": ["c"], "unchanged": ["b"], "removed": ["z"]}


# ---- indexing, against a throwaway copy of the knowledge schema ---------------------------------------------

class CountingEmbedder(FakeEmbedder):
    def __init__(self, fail_on=None):
        super().__init__(DIMS)
        self.texts, self.fail_on = [], fail_on

    def embed_documents(self, texts):
        if self.fail_on and any(self.fail_on in t for t in texts):
            raise EmbeddingError("The embedding model timed out.")
        self.texts += texts
        return super().embed_documents(texts)


@pytest.fixture
def test_schema():
    with psycopg.connect(ADMIN, autocommit=True) as conn:
        conn.execute(f"DROP SCHEMA IF EXISTS {SCHEMA} CASCADE")
        conn.execute(f"CREATE SCHEMA {SCHEMA} AUTHORIZATION admin")
        for table in ("documents", "chunks", "ingestion_runs"):
            conn.execute(f"CREATE TABLE {SCHEMA}.{table} (LIKE knowledge.{table} INCLUDING ALL)")
        conn.execute(f"""ALTER TABLE {SCHEMA}.chunks ADD FOREIGN KEY (document_id)
                         REFERENCES {SCHEMA}.documents (document_id) ON DELETE CASCADE""")
        conn.execute(f"CREATE SEQUENCE {SCHEMA}.runs_seq OWNED BY {SCHEMA}.ingestion_runs.run_id")
        conn.execute(f"ALTER TABLE {SCHEMA}.ingestion_runs ALTER run_id SET DEFAULT nextval('{SCHEMA}.runs_seq')")
        conn.execute(f"GRANT USAGE ON SCHEMA {SCHEMA} TO knowledge_writer")
        conn.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA {SCHEMA} TO knowledge_writer")
        conn.execute(f"GRANT USAGE ON ALL SEQUENCES IN SCHEMA {SCHEMA} TO knowledge_writer")
    yield SCHEMA
    with psycopg.connect(ADMIN, autocommit=True) as conn:
        conn.execute(f"DROP SCHEMA IF EXISTS {SCHEMA} CASCADE")


def count(sql):
    with psycopg.connect(ADMIN) as conn:
        return conn.execute(sql).fetchone()[0]


@pytest.fixture
def pack(tmp_path):
    target = tmp_path / "knowledge"
    shutil.copytree(KNOWLEDGE_DIR, target)
    return target


def run(pack, schema, embedder, **kw):
    return ingest(pack, embedder, url=WRITER, schema=schema, **kw)


@pytest.mark.integration
def test_first_run_indexes_every_document(pack, test_schema):
    docs = load(pack)
    report = run(pack, test_schema, CountingEmbedder())
    assert report.added == len(docs) and report.failed == 0
    assert count(f"SELECT count(*) FROM {SCHEMA}.documents") == len(docs)
    active = [d for d in docs if d.status == "active"]
    expected_chunks = sum(len(chunking.chunk(d)) for d in active)
    assert count(f"SELECT count(*) FROM {SCHEMA}.chunks") == expected_chunks
    assert count(f"""SELECT count(*) FROM {SCHEMA}.chunks c JOIN {SCHEMA}.documents d USING (document_id)
                     WHERE d.status = 'superseded'""") == 0
    assert count(f"SELECT count(*) FROM {SCHEMA}.chunks WHERE embedding_model = 'fake:{DIMS}'") == expected_chunks
    assert count(f"SELECT added FROM {SCHEMA}.ingestion_runs ORDER BY run_id DESC LIMIT 1") == len(docs)


@pytest.mark.integration
def test_a_second_run_changes_nothing_and_embeds_nothing(pack, test_schema):
    run(pack, test_schema, CountingEmbedder())
    again = CountingEmbedder()
    report = run(pack, test_schema, again)
    assert (report.added, report.changed, report.removed) == (0, 0, 0) and report.unchanged > 0
    assert again.texts == []


@pytest.mark.integration
def test_an_edited_document_is_replaced_and_unchanged_chunks_are_reused(pack, test_schema):
    run(pack, test_schema, CountingEmbedder())
    f = next(pack.rglob("doc-company-overview.md"))
    f.write_text(f.read_text().replace("December is our biggest month.", "December is our biggest month by far."))
    e = CountingEmbedder()
    report = run(pack, test_schema, e)
    assert report.changed == 1 and report.added == 0
    assert len(e.texts) == 1 and "by far" in e.texts[0]          # only the edited section was embedded again
    assert count(f"SELECT count(*) FROM {SCHEMA}.chunks WHERE content LIKE '%by far%'") == 1


@pytest.mark.integration
def test_a_metadata_change_updates_the_document(pack, test_schema):
    run(pack, test_schema, CountingEmbedder())
    f = next(pack.rglob("dq-dataset-ownership.md"))
    f.write_text(f.read_text().replace('access_groups = ["analyst", "limited"]', 'access_groups = ["analyst"]'))
    assert run(pack, test_schema, CountingEmbedder()).changed == 1
    assert count(f"SELECT array_length(access_groups, 1) FROM {SCHEMA}.documents WHERE document_id = 'dq-dataset-ownership'") == 1


@pytest.mark.integration
def test_a_deleted_file_leaves_the_index(pack, test_schema):
    run(pack, test_schema, CountingEmbedder())
    next(pack.rglob("doc-qbr-2026-q2.md")).unlink()
    assert run(pack, test_schema, CountingEmbedder()).removed == 1
    assert count(f"SELECT count(*) FROM {SCHEMA}.documents WHERE document_id = 'doc-qbr-2026-q2'") == 0
    assert count(f"SELECT count(*) FROM {SCHEMA}.chunks WHERE document_id = 'doc-qbr-2026-q2'") == 0


@pytest.mark.integration
def test_an_embedding_failure_keeps_the_old_index_for_that_document(pack, test_schema):
    run(pack, test_schema, CountingEmbedder())
    f = next(pack.rglob("metric-revenue.md"))
    f.write_text(f.read_text().replace("When someone says", "POISON When someone says"))
    report = run(pack, test_schema, CountingEmbedder(fail_on="POISON"))
    assert report.failed == 1 and "metric-revenue" in report.errors[0]
    assert count(f"SELECT count(*) FROM {SCHEMA}.chunks WHERE document_id = 'metric-revenue' AND content LIKE '%POISON%'") == 0
    assert count(f"SELECT count(*) FROM {SCHEMA}.chunks WHERE document_id = 'metric-revenue'") == 1
    assert count(f"SELECT failed FROM {SCHEMA}.ingestion_runs ORDER BY run_id DESC LIMIT 1") == 1


@pytest.mark.integration
def test_mixing_embedding_models_is_refused_unless_rebuilding(pack, test_schema):
    run(pack, test_schema, CountingEmbedder())

    class Other(CountingEmbedder):
        def __init__(self):
            super().__init__()
            self.model_id = "other:768"          # FakeEmbedder sets model_id per instance

    with pytest.raises(store.IndexError, match="fake:768"):
        run(pack, test_schema, Other())
    report = run(pack, test_schema, Other(), rebuild=True)
    assert report.changed + report.added > 0
    assert count(f"SELECT count(DISTINCT embedding_model) FROM {SCHEMA}.chunks") == 1


def test_schema_names_are_checked():
    with pytest.raises(store.IndexError):
        store.Index("postgresql://x/y", schema="knowledge; DROP TABLE users")
