# Running and testing GridRestore

This guide takes you from a clean machine to a running application, the physics study, and the test suite.
Commands assume you are in the project root unless a step says otherwise.

## 1. Prerequisites

| Tool | Version | Notes |
| --- | --- | --- |
| Python | 3.12 | Use a virtual environment. |
| Node.js | 20 or later | Needed for the frontend only. |
| PostgreSQL | 16 or 18 | With the `pgvector` and `btree_gist` extensions available. |
| `psql` | matching PostgreSQL | Used by the setup script. |

Check the database server is running before any step that touches it:

```bash
psql -h localhost -U <user> -d postgres -c "select version();"
```

If the connection is refused, start the server (for example `sudo service postgresql start` on Ubuntu, or
start it from the PostgreSQL app on macOS or Windows).

## 2. Python environment

```bash
python3 -m venv .venv
source .venv/bin/activate            # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

## 3. Database

Create an empty database and a login role, for example:

```sql
CREATE USER gridrestore_user WITH PASSWORD '<choose-a-password>';
CREATE DATABASE gridrestore OWNER gridrestore_user;
```

Set the connection string and a session secret in your shell:

```bash
export DATABASE_URL=postgresql://gridrestore_user:<choose-a-password>@localhost:5432/gridrestore
export SESSION_SECRET=$(openssl rand -hex 32)
```

Build the schema, migrations 002 to 007, and the demo data:

```bash
./scripts/setup_db.sh --reset
```

`--reset` drops and recreates the `public` schema, so it removes everything in that database. Run it only on
a database you intend to rebuild. Without `--reset`, the script expects an empty schema.

To check the result:

```bash
psql "$DATABASE_URL" -c "select count(*) from outage_scenarios;"   # at least 1 (the demo scenario)
```

## 4. Optional: benchmark dataset

This adds 50 benchmark scenarios with 500 repair tasks each, and 150 saved runs. It takes about 15 seconds.

```bash
python -m backend.bench_seed
python -m backend.benchmark          # index and materialized-view measurements, written to docs/benchmark_results.json
```

The benchmark rebuild replaces only the rows it created (names beginning with `Bench`).

## 5. Run the API

```bash
python -m uvicorn backend.api:app --port 8000
```

- Interactive documentation: http://127.0.0.1:8000/docs
- Health check: http://127.0.0.1:8000/health (should return `{"status":"ok", ...}`)

Demo accounts (change the passwords before any real use):

| User | Password | Can |
| --- | --- | --- |
| `admin` | `admin123` | everything, including audit, import, versions and rollback |
| `operator` | `operator123` | view, run schedules, run analytics; not change data |

## 6. Run the frontend

In a second terminal:

```bash
cd frontend
npm ci
npm run build
npm run start -- -p 3000
```

Open http://localhost:3000 and sign in. The API must be running on port 8000. The frontend expects the API at
http://127.0.0.1:8000 and allows requests from http://localhost:3000 only.

## 7. Physics study (optional, about 6 minutes)

```bash
python -m backend.grid.physics_study                   # writes docs/physics/ and stores one run in the database
python -m backend.grid.physics_study --quick           # 40 Monte Carlo trials; a fast check
python -m backend.grid.physics_study --no-db           # files only
python -m backend.grid.physics_study --keep-runs 1     # after storing, delete all but the newest stored run
```

Then open the **physics** tab in the app. The tab shows the newest stored run; use the run selector to pick
another.

Two standalone calibrations produce the numbers used in `docs/PHYSICS.md`:

```bash
python -m backend.grid.calibrate_lnr      # docs/physics/lnr_calibration.csv
python -m backend.grid.calibrate_w3       # docs/physics/w3_threshold_by_stress.csv and w3_choice.csv
```

## 8. Automated tests

Run from the project root with `DATABASE_URL` and `SESSION_SECRET` set, and the database running.

Full suite (about 5 minutes):

```bash
python -m pytest -q
```

With coverage:

```bash
python -m pytest -q --cov=backend --cov-report=term
```

Subsets, from fastest to slowest:

| Command | What it covers | Needs database |
| --- | --- | --- |
| `pytest -q tests/test_scheduler.py` | scheduling heuristics and rules | no |
| `pytest -q tests/test_features_pure.py` | exact solver, CSV validation, run diffs, tokens | no |
| `pytest -q tests/test_features_db.py` | crew-overlap rule, audit, versions, CSV import, API roles | yes |
| `pytest -q tests/test_api_endpoints.py` | remaining API endpoints | yes |
| `pytest -q tests/test_physics_store.py` | physics storage, pruning and API round trip | yes |
| `pytest -q tests/test_physics_driver.py` | study driver helpers and the weight-rule check | no |
| `pytest -q tests/test_grid_physics.py` | physics models checked against pandapower | no |
| `pytest -q tests/test_physics_solvers.py` | analytic Jacobian, Newton solver, continuation | no |
| `pytest -q tests/test_physics_extras.py` | LNR, targeted attack, policy simulation, cyber file | partly |

Expected result on the current code: all tests pass, with one case118 tracer test that states a known finding.
The last full run was before the final documentation edits, so run the suite once yourself to confirm.

## 9. Checks by hand

These confirm the behaviour the tests cannot see directly. Sign in as the stated user.

1. **Roles.** As `operator`, open the **audit** and **data** tabs: each shows a "Not allowed" message. Scenario
   creation is hidden.
2. **Crew overlap.** Schedule a run where one crew would be double-booked: the API refuses it with a clear message.
3. **Versions.** Edit a task's hours, then compare the two versions and roll back. Both versions remain in history.
4. **CSV import.** Import a file with several bad rows. Every error is listed and nothing is imported.
5. **Physics tab.** The continuation chart shows the voltage-limit and nose markers. The caption says generator
   reactive limits are enforced.
6. **Grid map.** Open the **grid** tab and draw the grid. Blocked tasks are listed under the map.

## 10. Docker (not yet verified)

`docker-compose.yml` and `Dockerfile.api` are written, and the compose file has been checked as YAML, but the
stack has not been started. On a machine with Docker:

```bash
SESSION_SECRET=$(openssl rand -hex 32) docker compose up --build
```

Then check http://127.0.0.1:8000/health. If the database container fails on start, check the init scripts in
`docker/init/` run in order (01 to 07).

## 11. Troubleshooting

| Symptom | Likely cause | Fix |
| --- | --- | --- |
| `connection refused` on port 5432 | PostgreSQL not running | start the server |
| `permission denied` during setup | the role cannot create extensions | grant the role rights, or create the extensions as a superuser |
| `Invalid credentials` | wrong demo password or wrong database | check `DATABASE_URL`; the demo users are created by migration 003 |
| API returns 401 on every call | `SESSION_SECRET` changed after login | sign in again |
| Physics tab says no study stored | no physics run yet | run `python -m backend.grid.physics_study` |
| Frontend loads but shows no data | API not on port 8000, or CORS | start the API and use `http://localhost:3000` |
| Numba messages in the physics output | optional speed-up library not installed | harmless; the code runs without it |

## 12. Known limits

- The physics results and the scheduling data are separate; see `docs/PHYSICS.md` and the project notes.
- case118 has two solution branches. The headline there is an open decision; see `docs/PHYSICS.md` section 5.8.
- Demo passwords are for local use only.
