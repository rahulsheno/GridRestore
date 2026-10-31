"""Text embedding back-ends.

Two back-ends share one interface:

- SentenceTransformerEmbedder: a real transformer model (default:
  all-MiniLM-L6-v2, 384-dim cosine-normalized vectors). Chosen by setting the
  EMBEDDING_MODEL environment variable. The heavy dependency is imported
  lazily; if the package or model files are unavailable the embedder raises
  EmbeddingUnavailable and callers fall back.
- HashEmbedder: the original deterministic 32-dim hashing projection
  (backend/vectors.py::embed_text). Always available, no external model.

The pgvector schema now carries both columns (embedding vector(32) legacy and
embedding_st vector(384) for the transformer), so which column is written and
searched depends only on which embedder is active at seed/query time.
"""
import os
from typing import Protocol

ST_DIM = 384
DEFAULT_MODEL = os.getenv("EMBEDDING_MODEL", "all-MiniLM-L6-v2")


class EmbeddingUnavailable(RuntimeError):
    pass


class Embedder(Protocol):
    dim: int
    def embed(self, text: str): ...


class HashEmbedder:
    """Legacy 32-dim deterministic embedder (see backend/vectors.py)."""
    dim = 32

    def embed(self, text: str):
        from .vectors import embed_text
        return embed_text(text, self.dim)


class SentenceTransformerEmbedder:
    """Real embedding model via the sentence-transformers package (lazy import)."""
    dim = ST_DIM

    def __init__(self, model_name: str | None = None):
        self.model_name = model_name or DEFAULT_MODEL
        self._model = None

    def _load(self):
        if self._model is None:
            try:
                from sentence_transformers import SentenceTransformer
            except Exception as exc:  # ImportError, OOM, ...
                raise EmbeddingUnavailable(
                    f"sentence-transformers not importable: {exc}") from exc
            try:
                self._model = SentenceTransformer(self.model_name)
            except Exception as exc:
                raise EmbeddingUnavailable(
                    f"model {self.model_name!r} unavailable: {exc}") from exc
        return self._model

    def embed(self, text: str):
        import numpy as np
        model = self._load()
        vec = model.encode(text, normalize_embeddings=True)
        return np.asarray(vec, dtype=float)


_active: Embedder | None = None


def get_embedder() -> Embedder:
    """Active embedder. EMBEDDING_BACKEND env var picks explicitly:
    'st' (transformer), 'hash' (legacy). Default: 'st' when the model can be
    loaded, else 'hash'."""
    global _active
    if _active is not None:
        return _active
    choice = os.getenv("EMBEDDING_BACKEND", "auto")
    if choice == "hash":
        _active = HashEmbedder()
        return _active
    try:
        e = SentenceTransformerEmbedder()
        e._load()
        _active = e
    except EmbeddingUnavailable:
        if choice == "st":
            raise
        _active = HashEmbedder()
    return _active


def reset_embedder():
    global _active
    _active = None
