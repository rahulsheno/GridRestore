-- Migration 002: vector paradigm for semantic repair search (pgvector).
-- Justification: relational tables enforce integrity; vector embeddings capture
-- unstructured repair-note semantics for similarity retrieval.
-- Requires: system-level pgvector install, then:
CREATE EXTENSION IF NOT EXISTS vector;

-- Deterministic 32-dim embedding carrier for repair narratives.
-- In production this would come from an embedding model; here a documented
-- hashing projection keeps the demo reproducible with zero extra services.
CREATE TABLE IF NOT EXISTS repair_embeddings (
  task_id TEXT PRIMARY KEY REFERENCES repair_tasks(task_id) ON DELETE CASCADE,
  narrative TEXT NOT NULL CHECK (length(trim(narrative)) > 0),
  embedding vector(32) NOT NULL,
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_repair_embeddings_vector
  ON repair_embeddings USING hnsw (embedding vector_cosine_ops);

-- Stored procedure: upsert one repair narrative + embedding (advanced feature).
CREATE OR REPLACE FUNCTION upsert_repair_embedding(
  p_task_id TEXT, p_narrative TEXT, p_embedding vector(32)
) RETURNS TEXT LANGUAGE plpgsql AS $$
BEGIN
  INSERT INTO repair_embeddings(task_id, narrative, embedding, updated_at)
  VALUES (p_task_id, p_narrative, p_embedding, now())
  ON CONFLICT (task_id) DO UPDATE SET
    narrative = EXCLUDED.narrative,
    embedding = EXCLUDED.embedding,
    updated_at = now();
  RETURN p_task_id;
END; $$;

-- Similarity search ordered by cosine distance (advanced feature).
CREATE OR REPLACE FUNCTION search_similar_repairs(
  p_embedding vector(32), p_limit INT DEFAULT 5
) RETURNS TABLE(task_id TEXT, narrative TEXT, distance DOUBLE PRECISION)
LANGUAGE sql STABLE AS $$
  SELECT e.task_id, e.narrative,
         (e.embedding <=> p_embedding)::DOUBLE PRECISION AS distance
  FROM repair_embeddings e
  ORDER BY e.embedding <=> p_embedding
  LIMIT p_limit;
$$;

-- Full-text search companion over narratives (advanced feature).
ALTER TABLE repair_embeddings
  ADD COLUMN IF NOT EXISTS narrative_tsv tsvector
  GENERATED ALWAYS AS (to_tsvector('english', narrative)) STORED;
CREATE INDEX IF NOT EXISTS idx_repair_embeddings_fts
  ON repair_embeddings USING gin (narrative_tsv);

-- ALTER + DROP proof for lab DDL coverage.
ALTER TABLE restoration_runs
  ADD COLUMN IF NOT EXISTS reviewed_by TEXT;
ALTER TABLE repair_embeddings ADD COLUMN IF NOT EXISTS legacy_note TEXT;
ALTER TABLE repair_embeddings DROP COLUMN IF EXISTS legacy_note;
