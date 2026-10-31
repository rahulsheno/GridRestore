"""Shared test setup.

- Tests marked `db` need a running PostgreSQL server and a DATABASE_URL.
  They are skipped automatically when DATABASE_URL is not set, so the
  default `pytest -q` run works on any machine.
- SESSION_SECRET is set for tests only. The application itself reads the
  secret from the environment and must not fall back to a hardcoded value.
"""
import os
import pytest

os.environ.setdefault("SESSION_SECRET", "test-only-secret")
# Login/refresh rate limiting would otherwise trip across many test logins.
os.environ.setdefault("LOGIN_RATE_LIMIT", "1000")
os.environ.setdefault("REFRESH_RATE_LIMIT", "1000")
os.environ.setdefault("REGISTER_RATE_LIMIT", "1000")


def pytest_collection_modifyitems(config, items):
    if os.getenv("DATABASE_URL"):
        return
    skip = pytest.mark.skip(reason="needs PostgreSQL: set DATABASE_URL to run")
    for item in items:
        if "db" in item.keywords:
            item.add_marker(skip)
