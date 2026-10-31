"""In-memory sliding-window rate limiter for auth endpoints.

Single-process only: each uvicorn worker has its own counters. That is enough
for the lab deployment and for tests; a multi-worker deployment should move the
counters to Redis or PostgreSQL.
"""
from collections import defaultdict, deque
import time

DEFAULT_LIMIT = 5
DEFAULT_WINDOW_SECONDS = 60.0

_hits: "defaultdict[str, deque[float]]" = defaultdict(deque)


def check(key: str, limit: int = DEFAULT_LIMIT, window: float = DEFAULT_WINDOW_SECONDS):
    """Record an attempt and return (allowed, retry_after_seconds)."""
    now = time.monotonic()
    q = _hits[key]
    while q and now - q[0] > window:
        q.popleft()
    if len(q) >= limit:
        retry = max(1.0, window - (now - q[0]))
        return False, round(retry, 1)
    q.append(now)
    return True, 0.0


def reset(key: str):
    _hits.pop(key, None)


def clear_all():
    _hits.clear()
