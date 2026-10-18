"""Deterministic text -> 32-dim embedding + pgvector persistence.

Lab justification: SQL tables enforce relational integrity; this vector layer
handles unstructured repair narratives for semantic similarity search.
Embeddings here use a documented, reproducible hashing projection (no external
model/service), so the demo is deterministic. Vector column type + HNSW index
+ cosine-distance function constitute the second (vector) database paradigm.
"""
import hashlib
import math
import numpy as np
from pgvector.psycopg import register_vector
from .db import connect

DIM = 32

def embed_text(text: str, dim: int = DIM) -> list:
    """Deterministic token-hash embedding: each token votes into hashed dims.

    Splits the 32 dims into 4 independent 8-dim sub-spaces (seeded by 4 hash
    prefixes) and averages them. This reduces single-hash collisions so
    semantically related narratives rank closer under cosine distance.
    L2-normalized; no external model required.
    """
    acc = [0.0] * dim
    tokens = [t.strip(".,;:()") for t in text.lower().split() if t.strip(".,;:()")]
    if not tokens:
        return acc
    for token in tokens:
        for subspace in range(4):
            digest = hashlib.sha256(f"{subspace}:{token}".encode()).digest()
            base = subspace * (dim // 4)
            for j in range(dim // 4):
                val = int.from_bytes(digest[2 * j:2 * j + 2], "big") / 65535.0 - 0.5
                acc[base + j] += val
    norm = math.sqrt(sum(v * v for v in acc)) or 1.0
    return [v / norm for v in acc]

NARRATIVES = {
    "T01": "North feeder E1 inspection and reconnection after storm damage",
    "T02": "Hospital branch E4 emergency repair, priority critical care load",
    "T03": "South line E3 rebuild with pole replacement and restringing",
    "T04": "Residential feeder E6 fuse replacement and testing",
    "T05": "Water facility branch E5 pump supply restoration",
    "T06": "Industrial feeder E8 transformer check and load balancing",
    "T07": "Central line E2 upstream repair feeding hospital branch",
    "T08": "Residential feeder E7 pole-top repair and safety check",
}

def seed_embeddings(narratives=None):
    """Upsert deterministic embeddings via stored procedure; returns count."""
    narratives = narratives or NARRATIVES
    count = 0
    with connect() as conn:
        register_vector(conn)
        with conn.cursor() as cur:
            for task_id, narrative in narratives.items():
                cur.execute("SELECT upsert_repair_embedding(%s,%s,%s)",
                            (task_id, narrative, np.array(embed_text(narrative))))
                count += 1
    return count

def find_similar_repairs(query_text: str, limit: int = 5):
    """Cosine-similarity search over repair narratives via stored function."""
    with connect() as conn:
        register_vector(conn)
        return conn.execute("SELECT * FROM search_similar_repairs(%s,%s)",
                            (np.array(embed_text(query_text)), limit)).fetchall()

def full_text_search_repairs(query_text: str, limit: int = 5):
    """Postgres full-text search companion over narratives."""
    with connect() as conn:
        return conn.execute(
            "SELECT task_id, narrative, "
            "ts_rank(narrative_tsv, plainto_tsquery('english', %s)) AS rank "
            "FROM repair_embeddings "
            "WHERE narrative_tsv @@ plainto_tsquery('english', %s) "
            "ORDER BY rank DESC LIMIT %s",
            (query_text, query_text, limit)).fetchall()

if __name__ == "__main__":
    print("Seeded embeddings:", seed_embeddings())
    for row in find_similar_repairs("hospital emergency power repair"):
        print(dict(row))
