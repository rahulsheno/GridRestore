# Project notes

The notebook is the primary executable experiment. It uses synthetic graph data, compares simplified scheduling heuristics, runs Monte Carlo repair-duration trials, demonstrates relational persistence with SQLite, and exports analysis artifacts.

The separate `backend/scheduler.py` module implements a greedy scheduler with task prerequisites and crew-skill constraints. It is covered by unit tests but is not yet connected to the Streamlit UI. The Streamlit/PostgreSQL prototype currently supports database health checks, scenario creation, and saved-run listing.

The repository also contains a separate FastAPI/Next.js scaffold under `backend/app/` and `frontend/app/`. Its scheduler is a simpler baseline; do not assume it has the same constraints as `backend/scheduler.py`.

All data and outcomes are synthetic. The project does not claim standards compliance or real-world grid-restoration validity. If external papers, datasets, standards, or code are added, record the specific source and how it was used; otherwise no external source attribution is implied.
