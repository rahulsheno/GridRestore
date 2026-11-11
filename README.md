# GridRestore

**A power-distribution restoration planning and grid-physics research platform**

GridRestore is an academic project for exploring how power-distribution restoration work can be prioritised after an outage. It combines a web application for dependency-constrained repair scheduling with a separate physics study built around standard IEEE test networks.

The scheduling application models outage scenarios, repair tasks, dependencies, crew skills and budgets. It compares scheduling heuristics, persists runs in PostgreSQL, and supports audit history, scenario versioning and semantic search over repair narratives. The physics study evaluates power-flow behaviour, state estimation, false-data injection and operating-state decisions on IEEE benchmark networks.

> **Scope:** The scheduling application and the IEEE physics study currently use separate data workflows and data models. They are not an integrated operational restoration controller. Project data is synthetic or drawn from published benchmark networks. GridRestore is intended for academic demonstration and research, not real utility operations.

---

## Contents

- [Highlights](#highlights)
- [Application screenshots](#application-screenshots)
- [System architecture](#system-architecture)
- [Entity relationship diagram](#entity-relationship-diagram)
- [Technology stack](#technology-stack)
- [Repository structure](#repository-structure)
- [Getting started](#getting-started)
- [Running the application](#running-the-application)
- [Physics study](#physics-study)
- [Testing](#testing)
- [Documentation](#documentation)
- [Security and limitations](#security-and-limitations)

## Highlights

### Restoration planning

- Model synthetic grid nodes, network connections, outage scenarios, repair tasks and repair prerequisites.
- Schedule work against a budget, crew availability, crew skill and task-dependency constraints.
- Compare three scheduling strategies: `priority_first`, `shortest_repair_first` and `gridrestore_score`.
- Compare heuristic outcomes with an exact mixed-integer optimisation baseline on small instances.
- Save restoration runs with task assignments, start/finish times, total cost, makespan and weighted recovery score.
- Inspect critical repairs, downstream unblock counts and critical paths.
- Compare saved runs and export Markdown reports.
- Import and export task data through CSV with row-level validation.

### Database and data integrity

- PostgreSQL relational schema for grid assets, scenarios, tasks, crews, runs and scheduled actions.
- Database constraints for valid references, task values and crew scheduling integrity.
- Crew-overlap prevention using a PostgreSQL exclusion constraint with `btree_gist`.
- Scenario edit history with version comparison and rollback.
- Audit events for changes to important records.
- Run-statistics dashboard backed by a materialized view.

### Similar-repair search

- Store repair narratives alongside vector embeddings using **pgvector**.
- Rank similar repair narratives using cosine distance and an HNSW index.
- Offer PostgreSQL full-text search as a complementary keyword-based mode.
- Support a deterministic hash-based embedder and an optional Sentence Transformers embedding backend.

### Grid-physics research

The separate physics module includes:

- DC power-flow and PTDF calculations.
- AC measurement models and state estimation.
- Newton power-flow and loadability/continuation studies.
- Generator reactive-power-limit handling.
- False-data injection (FDIA) experiments and bad-data detection analysis.
- Cyber-topology modelling and operating-state Markov decision process (MDP) experiments.
- Sensitivity and convergence studies with CSV and PNG outputs.

## Application screenshots

The screenshots below are maintained in `docs/figures/`.

| Application view | Screenshot |
|---|---|
| Main application overview | ![GridRestore application overview](docs/figures/ui-overview.png) |
| Login | ![GridRestore login screen](docs/figures/ui-login.png) |
| Scheduling | ![Repair scheduling interface](docs/figures/ui-scheduling.png) |
| Saved runs | ![Saved restoration runs](docs/figures/ui-saved%20runs.png) |
| Repair search | ![Similar repair search](docs/figures/ui-repair%20search.png) |
| Critical path | ![Critical repair path](docs/figures/ui-critical%20path.png) |
| Grid map | ![Grid map view](docs/figures/ui%20grid%20map.png) |
| Task data | ![Task data view](docs/figures/ui%20task%20data.png) |
| Audit trail | ![Audit trail](docs/figures/ui%20audit%20trail.png) |
| Physics study | ![Physics study results](docs/figures/physics%20study.png) |

## Design decisions and evaluation notes

### Why PostgreSQL and pgvector?

The project uses two data paradigms because the stored information has two different shapes:

- **Relational data belongs in PostgreSQL.** Grid nodes, edges, scenarios, repair tasks, task dependencies, crews, runs and scheduled actions need primary/foreign keys, transactions and database-enforced constraints. The schema also demonstrates triggers, views, materialized views, stored functions and B-tree/GiST indexes.
- **Repair narratives benefit from vector retrieval.** Free-text descriptions of faults are embedded and searched by cosine distance through pgvector. PostgreSQL full-text search is also available for keyword-oriented matching.

The default deterministic hash embedding keeps the demonstration reproducible without requiring a hosted model. An optional Sentence Transformers backend can use `all-MiniLM-L6-v2` when the optional ML dependencies and model are available.

### Measurements documented by the project

The accompanying methodology and performance documents report these results for the project's benchmark setup:

- The `gridrestore_score` heuristic averaged approximately **15% below the exact optimum** across 200 small random instances.
- A composite database index improved the measured scenario query by approximately **5×**.
- The materialized run-statistics view was approximately **50× faster** than the corresponding live aggregate in the reported benchmark.
- Enforcing the crew-overlap exclusion constraint roughly **doubled bulk-insert cost** in that benchmark.

These are measurements from the documented synthetic benchmark, not general performance guarantees. See [docs/METHODOLOGY.md](docs/METHODOLOGY.md) and [docs/PERFORMANCE.md](docs/PERFORMANCE.md) for setup and context.

## System architecture

The scheduling application follows a three-layer architecture:

1. **Frontend:** Next.js application for authentication, scenario management, scheduling, saved runs, search, criticality, grid visualisation, audit and physics results.
2. **Backend:** FastAPI REST service for authentication, business logic, scheduling, analytics, vector search and read-only physics endpoints.
3. **Database:** PostgreSQL for relational data, audit/version history and pgvector-backed repair embeddings.

```mermaid
flowchart TD
    UI["Next.js frontend"] --> API["FastAPI REST API"]
    API --> DB[("PostgreSQL + pgvector")]
    API --> SCHED["Scheduling and optimisation"]
    API --> SEARCH["Vector and full-text search"]
    API --> CRIT["Criticality and dependency analysis"]
    PHY["IEEE physics study"] --> PHYAPI["Physics result storage and read API"]
    PHYAPI --> DB
    NOTEBOOK["Jupyter notebook / SQLite demo"] --> EXP["Learning workflow and plots"]
```

The physics study is exposed to the frontend through read-only API routes. It remains a distinct analytical workflow; the project does not claim a fully validated mapping from each repair task to a physical network element.

## Entity relationship diagrams

The database diagrams are split into smaller views so that each part of GridRestore can be read independently. All images are stored in [`docs/figures/ER Diagram/`](docs/figures/ER%20Diagram/).

### 1. Core restoration planning

Shows the grid assets and the main restoration workflow: scenarios, repair tasks, task dependencies, crews, runs and scheduled actions.

![Core restoration planning ER diagram](docs/figures/ER%20Diagram/01_core_restoration.png)

### 2. Authentication, audit and scenario versioning

Shows application users, refresh tokens, audit records and scenario snapshots used for version history and rollback.

![Authentication, audit and versioning ER diagram](docs/figures/ER%20Diagram/02_auth_audit_versions.png)

### 3. Semantic repair search

Shows the relationship between repair tasks and their search records, including the legacy 32-dimensional hash embedding, optional 384-dimensional transformer embedding and generated full-text search vector.

![Semantic repair search ER diagram](docs/figures/ER%20Diagram/03_semantic_repair_search.png)

### 4. Physics-study result storage

The physics result schema is divided into three diagrams to avoid a single crowded image.

**4A. Validation and continuation results**

![Physics validation and continuation ER diagram](docs/figures/ER%20Diagram/04a_physics_validation.png)

**4B. FDIA experiments and MDP results**

![Physics FDIA and MDP ER diagram](docs/figures/ER%20Diagram/04b_physics_fdia_mdp.png)

**4C. Sensitivity, convergence and figure outputs**

![Physics sensitivity and output ER diagram](docs/figures/ER%20Diagram/04c_physics_sensitivity_outputs.png)

### 5. Grid-to-physics mapping

Shows how a synthetic grid edge is associated with an IEEE benchmark case and a line or bus element for the physics-derived risk mapping.

![Grid-to-physics mapping ER diagram](docs/figures/ER%20Diagram/05_grid_to_physics_mapping.png)

**Relationship notes:** `scheduled_actions.crew_label` is stored as text; it is not a foreign key to `crews`. `audit_log` records changes across multiple tables and therefore uses table/row identifiers rather than a conventional foreign key to each audited table. The diagrams follow the relationships declared in the SQL schema and migrations. For the detailed column data dictionary and constraints, see [docs/ERD.md](docs/ERD.md) and [docs/PROJECT_REPORT.md](docs/PROJECT_REPORT.md).

## Technology stack

| Layer | Technologies |
|---|---|
| Frontend | Next.js, React, TypeScript |
| Backend API | Python, FastAPI, Uvicorn, Pydantic |
| Relational database | PostgreSQL |
| Vector search | pgvector, HNSW cosine similarity, PostgreSQL full-text search |
| Authentication | bcrypt password hashing, signed access tokens, refresh-token handling, role checks |
| Scheduling and analytics | NumPy, pandas, SciPy, PuLP, NetworkX |
| Power-system analysis | pandapower and project power-flow/state-estimation modules |
| Visualisation and research | Matplotlib, Jupyter Notebook |
| Tests | pytest, pytest-cov |
| Containerisation | Docker Compose |

Optional transformer embeddings can be installed separately using `requirements-ml.txt`. PostgreSQL itself and its required extensions must be installed or provided by the database service.

## Repository structure

The tree below highlights the main source files and supporting project artefacts. Individual test modules and generated result files are grouped to keep the overview readable.

```text
GridRestore/
├── backend/
│   ├── api.py                    # FastAPI application and REST endpoints
│   ├── auth.py                   # Authentication, roles and token handling
│   ├── db.py                     # PostgreSQL access and persistence
│   ├── scheduler.py              # Budget/skill/dependency-aware heuristics
│   ├── exact.py                  # Exact optimisation baseline
│   ├── criticality.py            # Critical repairs and critical-path analysis
│   ├── analytics.py              # Sweeps, robustness and performance analytics
│   ├── audit_dashboard.py        # Audit and dashboard data
│   ├── diffing.py                # Compare saved restoration runs
│   ├── report.py                 # Markdown run reports
│   ├── tasks_io.py               # CSV import/export and validation
│   ├── versions.py               # Scenario version history and rollback
│   ├── vectors.py                # Embeddings, pgvector and full-text search
│   ├── embeddings.py             # Hash and Sentence Transformers backends
│   ├── physics_api.py            # Read-only physics result endpoints
│   ├── physics_map.py            # Physics-to-planning weighting support
│   ├── seed_demo.py              # Demo scenario seed
│   ├── seed_users.py             # Demo user seed
│   └── grid/
│       ├── ac_se.py              # AC measurement model and state estimation
│       ├── dc_model.py           # DC network model and PTDF
│       ├── pflow.py              # Power-flow solver and branch tracing
│       ├── operating_point.py    # Load continuation and operating points
│       ├── fdia.py               # False-data injection experiments
│       ├── cyber.py              # Cyber topology model
│       ├── mdp.py                # Operating-state MDP
│       ├── dispatch.py            # Dispatch calculations
│       ├── study.py               # Physics study calculations
│       ├── store.py               # Physics study persistence
│       └── physics_study.py       # Study driver and artifact generation
├── database/
│   ├── schema.sql                 # Core relational schema
│   ├── lab_queries.sql            # SQL learning and demonstration queries
│   ├── performance_queries.sql    # EXPLAIN ANALYZE examples
│   └── migrations/
│       ├── 002_vectors.sql
│       ├── 003_auth.sql
│       ├── 004_causes.sql
│       ├── 005_integrity_audit_versions.sql
│       ├── 006_physics.sql
│       ├── 007_physics_extensions.sql
│       ├── 008_auth_hardening.sql
│       ├── 009_embeddings_st.sql
│       └── 010_element_physics_map.sql
├── docker/
│   └── init/                      # Ordered PostgreSQL initialisation scripts
├── docs/
│   ├── figures/                   # Application screenshots and split ER diagrams
│   ├── physics/                   # Physics CSV results and plots
│   ├── ARCHITECTURE.md
│   ├── ERD.md
│   ├── IMPLEMENTATION_NOTES.md
│   ├── METHODOLOGY.md
│   ├── PERFORMANCE.md
│   ├── PHYSICS.md
│   ├── PROJECT_OVERVIEW.md
│   ├── PROJECT_REPORT.md
│   ├── RUNNING.md
│   ├── STANDARDS.md
│   └── TESTING.md
├── frontend/
│   ├── app/
│   │   ├── page.tsx               # Main application interface
│   │   ├── layout.tsx
│   │   └── globals.css
│   ├── components/
│   │   ├── AuditPanel.tsx
│   │   ├── GridPanel.tsx
│   │   ├── GridScene.tsx
│   │   ├── PhysicsPanel.tsx
│   │   ├── TaskDataPanel.tsx
│   │   ├── ThemeToggle.tsx
│   │   ├── icons.tsx
│   │   └── ui.tsx
│   └── lib/
│       ├── api-client.ts
│       └── api-types.ts
├── notebook/
│   └── GridRestore_Lab.ipynb       # Standalone learning/demo notebook
├── scripts/
│   ├── setup_db.sh
│   └── sync_docker_init.sh
├── tests/                          # Automated API, DB, scheduler and physics tests
├── .env.example
├── docker-compose.yml
├── Dockerfile.api
├── pytest.ini
├── requirements.txt
├── requirements-ml.txt
└── README.md
```

## Getting started

### Prerequisites

- Python 3.12 recommended.
- Node.js 20 or later for the frontend.
- PostgreSQL 16 or 18 with the `pgvector` and `btree_gist` extensions available.
- PostgreSQL command-line tools (`psql`).
- Git.

### 1. Clone the repository

```bash
git clone https://github.com/rahulsheno/GridRestore.git
cd GridRestore
```

### 2. Create and activate a Python environment

**Windows PowerShell**

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

**Linux/macOS**

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 3. Configure environment variables

Copy the example file:

**PowerShell**
```powershell
Copy-Item .env.example .env
```

**Linux/macOS**
```bash
cp .env.example .env
```

Set the database connection string and a long, random session secret in your local environment or `.env` file:

```env
DATABASE_URL=postgresql://gridrestore_user:YOUR_PASSWORD@localhost:5432/gridrestore
SESSION_SECRET=replace-with-a-long-random-secret
```

Do not commit your real `.env` file or credentials.

### 4. Create the PostgreSQL database

Connect as a PostgreSQL administrator and create a database role and database:

```sql
CREATE USER gridrestore_user WITH PASSWORD 'YOUR_PASSWORD';
CREATE DATABASE gridrestore OWNER gridrestore_user;
```

Then set `DATABASE_URL` to use this role and database.

### 5. Initialise the schema and demo data

From the repository root, run the setup script in a Bash-compatible shell (Linux, macOS, WSL or Git Bash):

```bash
./scripts/setup_db.sh
```

The script applies the database schema and migrations and loads demo data. Use `--reset` only when you intentionally want to rebuild the target schema; it is destructive to existing objects in that schema. For Windows-specific PostgreSQL setup details, see [docs/RUNNING.md](docs/RUNNING.md).

## Running the application

Start the services in separate terminals.

### Terminal 1 — FastAPI backend

From the repository root:

```bash
python -m uvicorn backend.api:app --host 127.0.0.1 --port 8000
```

- API base: `http://127.0.0.1:8000`
- Interactive API documentation: `http://127.0.0.1:8000/docs`
- Health check: `http://127.0.0.1:8000/health`

### Terminal 2 — Next.js frontend

```bash
cd frontend
npm ci
npm run dev
```

Open [http://localhost:3000](http://localhost:3000).

For a production build:

```bash
npm run build
npm run start
```

### Demo accounts

The local demo seed uses the accounts below by default. Change their passwords before using the application outside a local demonstration.

| Role | Username | Password | Permissions |
|---|---|---|---|
| Administrator | `admin` | `admin123` | Manage data, scenarios, versions and audit functions |
| Operator | `operator` | `operator123` | View data, run schedules and analytics |

### Docker Compose

The repository includes a Docker Compose stack for PostgreSQL/pgvector and the API, plus a one-shot seed service. The compose database is mapped to host port **5433** to avoid conflicting with a local PostgreSQL service on port 5432.

```bash
SESSION_SECRET="$(openssl rand -hex 32)" docker compose up --build
```

The frontend can be run separately using the steps above. Review `docker-compose.yml` and [docs/RUNNING.md](docs/RUNNING.md) for configuration details before starting the stack.

## Physics study

The physics study uses IEEE benchmark networks bundled with pandapower: case9, case14, case30, case57 and case118.

Run the full study from the repository root:

```bash
python -m backend.grid.physics_study
```

Useful variants:

```bash
python -m backend.grid.physics_study --quick     # reduced Monte Carlo trials
python -m backend.grid.physics_study --no-db     # write files without storing a DB run
python -m backend.grid.physics_study --keep-runs 1
```

Results are written under `docs/physics/` and, unless `--no-db` is supplied, stored in PostgreSQL for display in the application's Physics tab. See [docs/PHYSICS.md](docs/PHYSICS.md) for the assumptions, validation approach, corrections and known limitations.

## Testing

Run tests from the repository root. Database-dependent tests require a configured PostgreSQL database and the environment variables above.

```bash
python -m pytest -q
```

With coverage:

```bash
python -m pytest -q --cov=backend --cov-report=term
```

For focused tests and troubleshooting, see [docs/RUNNING.md](docs/RUNNING.md) and [docs/TESTING.md](docs/TESTING.md).

## Documentation

| Document | Description |
|---|---|
| [Project overview](docs/PROJECT_OVERVIEW.md) | Problem, scope, application/physics split and project status |
| [Project report](docs/PROJECT_REPORT.md) | Objectives, requirements, schema, architecture, results and future work |
| [Architecture](docs/ARCHITECTURE.md) | Application components and data flow |
| [ER diagram and data dictionary](docs/ERD.md) | Entity relationships, tables, keys and constraints |
| [Running guide](docs/RUNNING.md) | Detailed setup, execution, testing and troubleshooting |
| [Methodology](docs/METHODOLOGY.md) | Scheduling methodology and comparison with the exact baseline |
| [Performance](docs/PERFORMANCE.md) | Database indexes, materialized-view and benchmark results |
| [Physics study](docs/PHYSICS.md) | IEEE models, validation, FDIA, MDP and assumptions |
| [Testing](docs/TESTING.md) | Test organisation, coverage and verification notes |
| [Standards and scope](docs/STANDARDS.md) | Standards context and explicit non-compliance claims |

## Security and limitations

- All application outage, network, repair, crew, cost and outcome data is synthetic. Physics experiments use published IEEE benchmark networks.
- GridRestore is not connected to utility infrastructure and must not be used to operate or control electrical equipment.
- The scheduling heuristics are approximations. The exact optimisation baseline is intended for small-instance comparison.
- The power-system models and thresholds are research assumptions; they do not establish regulatory or standards compliance.
- The scheduling application and physics study currently have distinct data workflows and should not be interpreted as a single validated end-to-end grid-restoration model.
- Demo credentials are for local evaluation only. Use unique passwords and a securely generated `SESSION_SECRET` for any non-demo deployment.

---

## Contributors

| Contributor | Role | Key Areas |
|---|---|---|
| [**Rahul Shenoy**](https://github.com/rahulsheno) | Backend & Data Engineering | Backend API, database schema & migrations, grid physics engine, scheduling algorithms, test suite, documentation |
| [**Samvit Nandakishore Atur**](https://github.com/samvitOK) | Frontend Development | Next.js frontend, UI components, grid visualization, physics panel, audit trail dashboard, README & screenshots |

---

For implementation details and project notes, start with [docs/PROJECT_OVERVIEW.md](docs/PROJECT_OVERVIEW.md).
