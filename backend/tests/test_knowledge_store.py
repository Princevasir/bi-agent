"""RAG R2: pgvector and the knowledge schema in appdb, with least-privilege logins."""
import psycopg
import pytest
from psycopg import errors

pytestmark = pytest.mark.integration

ADMIN = "postgresql://admin:admin_dev_pw@localhost:5433/appdb"
WRITER = "postgresql://knowledge_writer:knowledge_writer_dev_pw@localhost:5433/appdb"
APP = "postgresql://app_rw:app_dev_pw@localhost:5433/appdb"
DIMENSIONS = 768


def q(url, sql, params=None):
    with psycopg.connect(url, connect_timeout=5) as conn:
        cur = conn.execute(sql, params)
        return cur.fetchall() if cur.description else None


def vec(*values):
    return "[" + ",".join(str(v) for v in list(values) + [0.0] * (DIMENSIONS - len(values))) + "]"


@pytest.fixture
def clean():
    q(WRITER, "DELETE FROM knowledge.documents WHERE document_id LIKE 'test-%'")
    yield
    q(WRITER, "DELETE FROM knowledge.documents WHERE document_id LIKE 'test-%'")


def add(doc_id, *chunks, groups=("analyst",)):
    with psycopg.connect(WRITER) as conn:
        conn.execute("""INSERT INTO knowledge.documents (document_id, doc_type, title, domain, owner, source, version,
                        effective_date, status, access_groups, tables, content_hash, path)
                        VALUES (%s, 'metric', 't', 'Sales', 'o', 's', 1, '2025-01-01', 'active', %s, '{}', %s, 'p')""",
                     (doc_id, list(groups), doc_id.ljust(64, "0")[:64]))
        for i, (content, embedding) in enumerate(chunks):
            conn.execute("""INSERT INTO knowledge.chunks (chunk_id, document_id, position, content, content_hash,
                            token_count, embedding, embedding_model) VALUES (%s, %s, %s, %s, %s, 3, %s, 'test-model')""",
                         (f"{doc_id}#{i}", doc_id, i, content, f"{doc_id}{i}".ljust(64, "0")[:64], embedding))


def test_vector_extension_is_installed():
    assert q(ADMIN, "SELECT extname FROM pg_extension WHERE extname = 'vector'") == [("vector",)]


def test_tables_and_the_embedding_column():
    tables = {r[0] for r in q(ADMIN, "SELECT table_name FROM information_schema.tables WHERE table_schema = 'knowledge'")}
    assert tables == {"documents", "chunks", "ingestion_runs"}
    [(dtype,)] = q(ADMIN, """SELECT format_type(atttypid, atttypmod) FROM pg_attribute
                             WHERE attrelid = 'knowledge.chunks'::regclass AND attname = 'embedding'""")
    assert dtype == f"vector({DIMENSIONS})"


def test_there_is_a_cosine_index_on_the_embeddings():
    defs = [r[0] for r in q(ADMIN, "SELECT indexdef FROM pg_indexes WHERE schemaname = 'knowledge' AND tablename = 'chunks'")]
    assert any("hnsw" in d and "vector_cosine_ops" in d for d in defs)


def test_nearest_chunks_come_first(clean):
    add("test-a", ("about revenue", vec(1.0, 0.0)), ("about stock", vec(0.0, 1.0)))
    rows = q(APP, """SELECT chunk_id FROM knowledge.chunks WHERE document_id = 'test-a'
                     ORDER BY embedding <=> %s::vector LIMIT 1""", (vec(0.9, 0.1),))
    assert rows == [("test-a#0",)]


def test_deleting_a_document_deletes_its_chunks(clean):
    add("test-b", ("x", vec(1.0)))
    q(WRITER, "DELETE FROM knowledge.documents WHERE document_id = 'test-b'")
    assert q(ADMIN, "SELECT count(*) FROM knowledge.chunks WHERE document_id = 'test-b'") == [(0,)]


def test_a_wrong_dimension_is_refused(clean):
    with pytest.raises(errors.DataException):
        add("test-c", ("x", "[1,2,3]"))


def test_the_app_can_only_read_the_knowledge(clean):
    assert q(APP, "SELECT count(*) FROM knowledge.chunks") is not None
    with pytest.raises(errors.InsufficientPrivilege):
        q(APP, "DELETE FROM knowledge.chunks")
    with pytest.raises(errors.InsufficientPrivilege):
        q(APP, "INSERT INTO knowledge.ingestion_runs (embedding_model) VALUES ('x')")


def test_the_writer_cannot_touch_users_or_audit():
    for sql in ("SELECT * FROM users", "SELECT * FROM audit.events"):
        with pytest.raises(errors.InsufficientPrivilege):
            q(WRITER, sql)


@pytest.mark.parametrize("login", [
    "postgresql://bi_readonly:readonly_dev_pw@localhost:5433/appdb",
    "postgresql://retail_analyst:retail_analyst_dev_pw@localhost:5433/appdb",
])
def test_bi_logins_cannot_reach_the_knowledge(login):
    with pytest.raises(psycopg.OperationalError):
        q(login, "SELECT 1")
