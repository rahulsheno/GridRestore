# Change log (this revision)

- Tests: database-dependent tests are marked `db` and skipped when `DATABASE_URL` is not set. The default `pytest -q` run is now green on a machine without PostgreSQL (10 passed, 9 skipped).
- Security: `SESSION_SECRET` is no longer defaulted to a hardcoded value. The application refuses to create tokens without it. Tests set a test-only value in `tests/conftest.py`.
- Docs: `docs/NOTES.md` rewritten to describe the current architecture and to state which tests were and were not re-run.

Not changed in this revision: vector embeddings, scheduler evaluation against an exact baseline, performance measurements, additional triggers, CI, frontend structure.
