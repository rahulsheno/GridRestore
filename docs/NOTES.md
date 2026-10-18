# Project notes

## Current state (keep this section up to date)
- **Main application:** Next.js frontend (`frontend/app/`) talking to a FastAPI backend (`backend/api.py`) that reads and writes PostgreSQL.
- **Database:** PostgreSQL schema in `database/schema.sql`, migrations in `database/migrations/` (vectors, auth, causes).
- **Notebook:** `notebook/GridRestore_Lab.ipynb` is a standalone SQLite demonstration that runs without a server.
- **Scheduler:** `backend/scheduler.py` is the only scheduler. It supports prerequisites, crew skills and a budget.
- **Removed:** the Streamlit UI and an earlier in-memory FastAPI/Next.js prototype. Neither is in the repository.

## Test status
- `python -m pytest -q` runs without a database. Tests marked `db` are skipped unless `DATABASE_URL` is set.
- Database tests were written against a local PostgreSQL 18 server. They have not been re-run in this change set.

## Limitations
All data and outcomes are synthetic. The project does not claim standards compliance or real-world restoration validity. External sources must be recorded where they are used.
