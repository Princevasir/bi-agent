-- RAG R2: the knowledge index in appdb (pgvector). Source documents live in backend/knowledge/;
-- these tables are derived from them by the ingestion command and can always be rebuilt.
CREATE ROLE knowledge_writer LOGIN PASSWORD 'knowledge_writer_dev_pw';
GRANT CONNECT ON DATABASE appdb TO knowledge_writer;

\connect appdb
CREATE EXTENSION IF NOT EXISTS vector;
CREATE SCHEMA knowledge AUTHORIZATION admin;

CREATE TABLE knowledge.documents (
  document_id    text PRIMARY KEY,
  doc_type       text NOT NULL CHECK (doc_type IN ('metric', 'rule', 'sql_example', 'dashboard', 'data_quality', 'document')),
  title          text NOT NULL,
  domain         text NOT NULL,
  owner          text NOT NULL,
  source         text NOT NULL,
  version        integer NOT NULL CHECK (version >= 1),
  effective_date date NOT NULL,
  status         text NOT NULL CHECK (status IN ('active', 'superseded')),
  access_groups  text[] NOT NULL CHECK (cardinality(access_groups) > 0),
  tables         text[] NOT NULL DEFAULT '{}',
  content_hash   char(64) NOT NULL,
  path           text NOT NULL,
  updated_at     timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE knowledge.chunks (
  chunk_id        text PRIMARY KEY,
  document_id     text NOT NULL REFERENCES knowledge.documents (document_id) ON DELETE CASCADE,
  position        integer NOT NULL CHECK (position >= 0),
  content         text NOT NULL,
  content_hash    char(64) NOT NULL,
  token_count     integer NOT NULL CHECK (token_count > 0),
  embedding       vector(768) NOT NULL,      -- nomic-embed-text; must match the embedder's dimensions
  embedding_model text NOT NULL,
  created_at      timestamptz NOT NULL DEFAULT now(),
  UNIQUE (document_id, position)
);
CREATE INDEX chunks_document_id_idx ON knowledge.chunks (document_id);
CREATE INDEX chunks_embedding_idx ON knowledge.chunks USING hnsw (embedding vector_cosine_ops);
CREATE INDEX documents_access_groups_idx ON knowledge.documents USING gin (access_groups);

CREATE TABLE knowledge.ingestion_runs (
  run_id          bigserial PRIMARY KEY,
  started_at      timestamptz NOT NULL DEFAULT now(),
  finished_at     timestamptz,
  embedding_model text NOT NULL,
  added           integer NOT NULL DEFAULT 0,
  changed         integer NOT NULL DEFAULT 0,
  unchanged       integer NOT NULL DEFAULT 0,
  removed         integer NOT NULL DEFAULT 0,
  failed          integer NOT NULL DEFAULT 0,
  error           text
);

-- Least privilege: the ingestion login writes the index and nothing else; the app only reads it.
GRANT USAGE ON SCHEMA knowledge TO knowledge_writer, app_rw;
GRANT SELECT, INSERT, UPDATE, DELETE ON knowledge.documents, knowledge.chunks, knowledge.ingestion_runs TO knowledge_writer;
GRANT USAGE, SELECT ON SEQUENCE knowledge.ingestion_runs_run_id_seq TO knowledge_writer;
GRANT SELECT ON knowledge.documents, knowledge.chunks TO app_rw;
