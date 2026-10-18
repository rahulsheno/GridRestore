# GridRestore — restoration planning with SQL + pgvector + Next.js

Synthetic power-distribution restoration planner: schedule repairs under budget,
crew-skill and dependency constraints, persist runs to PostgreSQL, and search
similar past repairs via pgvector. Original work — inspired by the *idea* of
grid planning tools, not copied from any repository.

## Stack (lab-compliant)
- **SQL (mandatory):** PostgreSQL 18 — `database/schema.sql` + `database/migrations/003_auth.sql`
- **Vector (2nd paradigm):** pgvector 0.8.6 — `database/migrations/002_vectors.sql`, `backend/vectors.py`
- **Backend/API:** FastAPI — `backend/api.py` (auth, scenarios, schedule, runs, search)
- **Frontend:** Next.js 14 — `frontend/app/page.tsx` (login, scenarios, schedule, runs, search, critical incl. skill gaps + cause breakdown)
- **Auth:** bcrypt + signed tokens, roles `admin` (create + run) / `operator` (run + view)
- **Notebook:** `notebook/GridRestore_Lab.ipynb` (portable SQLite demo, runs standalone)

## Setup (Windows PowerShell, local PostgreSQL on 5432)
```powershell
python -m venv .venv; .\.venv\Scripts\Activate.ps1
pip install -r requirements.txt; pip install jupyter pytest
Copy-Item .env.example .env   # then set DATABASE_URL + SESSION_SECRET
$env:PATH += ';C:\Program Files\PostgreSQL\18\bin'
Get-Content database/schema.sql | psql -U gridrestore_user -h localhost -p 5432 -d gridrestore
Get-Content database/migrations/002_vectors.sql | psql -U gridrestore_user -h localhost -p 5432 -d gridrestore
Get-Content database/migrations/003_auth.sql | psql -U gridrestore_user -h localhost -p 5432 -d gridrestore
Get-Content database/migrations/004_causes.sql | psql -U gridrestore_user -h localhost -p 5432 -d gridrestore
python -m backend.seed_demo
python -m backend.vectors
python -m pytest -q
```
Seeded logins: `admin/admin123`, `operator/operator123` (bcrypt hashes, see `003_auth.sql`).
Optional scale dataset for the performance story: `python -m backend.scale_seed`
(deterministic seed 20261018; adds a separate 'Scale test 10k' scenario).

## Run
```powershell
# Terminal 1 — API (port 8000):
python -m uvicorn backend.api:app --host 127.0.0.1 --port 8000
# Terminal 2 — Next.js (port 3000):
cd frontend; npm install; npm run dev
# Notebook: jupyter notebook  ->  notebook/GridRestore_Lab.ipynb -> Run All
```

## Database choice and justification (lab: SQL + Vector)
- **SQL (PostgreSQL 18, mandatory):** relational integrity for the grid model —
`grid_nodes, grid_edges, outage_scenarios, repair_tasks, task_dependencies, crews,
restoration_runs, scheduled_actions, audit_log`. PKs, FKs, CHECKs, UNIQUEs, view
`v_restoration_run_summary`, trigger `trg_repair_task_audit`, HNSW/GIN/B-tree indexes,
transactions in `save_run`, stored procedures `upsert_repair_embedding` /
`search_similar_repairs`. See `database/schema.sql`, `database/migrations/002_vectors.sql`.
- **Vector (pgvector 0.8.6, second paradigm):** unstructured repair narratives embedded
into `repair_embeddings.embedding vector(32)` with HNSW cosine index for semantic
similarity (`<=>`), plus a `tsvector` GIN companion for full-text search. SQL cannot rank
"similar past fault" by meaning; vectors can. Embeddings here use a documented deterministic
hashing projection (`backend/vectors.py::embed_text`, L2-normalized, 32-dim), so the demo is
reproducible without an external model service. Swap in a real model later without schema change.
- Apply: schema first, then `database/migrations/002_vectors.sql`, then `python -m backend.vectors`
to seed 8 narratives. UI tab "Similar repairs" demos both vector and FTS modes.

## Main application (Next.js + FastAPI + PostgreSQL)
Lab walkthrough against local PostgreSQL 18 on default port 5432 (verified):
health check, login, scenario list/create, schedule + save, run actions, vector/FTS search.
Old Streamlit UI and the in-memory FastAPI/Next.js prototype were removed;
the Next.js app now talks to PostgreSQL through `backend/api.py`.

## Other code in this repository
- `database/schema.sql`: tables, constraints, view, audit trigger, indexes.
- `database/migrations/002_vectors.sql`: pgvector table, HNSW + FTS indexes, procedures, ALTER/DROP proof.
- `database/migrations/003_auth.sql`: `app_users` + bcrypt seeds for admin/operator.
- `database/lab_queries.sql`: JOIN / GROUP BY / HAVING / ORDER BY / aggregates / subqueries.
- `database/performance_queries.sql`: example PostgreSQL `EXPLAIN ANALYZE` queries.
- `docs/`: architecture, ERD, methodology, testing, and scope notes.

## Scope and integrity
All network, outage, cost, repair-duration, crew, and outcome data are synthetic. GridRestore is an academic demonstration, not an operational control system or validated power-flow model. No IEC/IEEE compliance is claimed. PostgreSQL integration is only verified when tested against a running, configured PostgreSQL server.
