-- Migration 009: real (transformer) embedding support.
-- Adds a 384-dim column next to the legacy 32-dim hash embedding so a
-- sentence-transformer model (all-MiniLM-L6-v2, 384 dims) can be used for
-- semantic search without touching the demo-legacy path.
ALTER TABLE repair_embeddings ADD COLUMN IF NOT EXISTS embedding_st vector(384);
CREATE INDEX IF NOT EXISTS idx_embeddings_st_hnsw ON repair_embeddings
  USING hnsw (embedding_st vector_cosine_ops);
