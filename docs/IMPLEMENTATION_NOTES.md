# Implemented components and current gaps

## Present in the repository
- [x] Notebook experiment with synthetic scheduling strategies, Monte Carlo trials, plots, and a SQLite relational-database demonstration.
- [x] Dependency- and crew-skill-aware greedy scheduler in `backend/scheduler.py`.
- [x] PostgreSQL schema, seed script, and basic Streamlit database UI.
- [x] Separate FastAPI/Next.js prototype with a simpler baseline scheduler.
- [x] Unit tests for the standalone schedulers.

## Not yet integrated or verified
- [ ] Wire `backend/scheduler.py` into the Streamlit UI so users can run a schedule, validate it, and persist the run/actions.
- [ ] Verify the complete PostgreSQL workflow against a running database.
- [ ] Compare the heuristics with an exact optimization baseline on small synthetic instances.
- [ ] Run and record PostgreSQL `EXPLAIN ANALYZE` measurements on a meaningful dataset.

The FastAPI/Next.js scaffold and Streamlit prototype are separate code paths; do not describe them as a single integrated application.
