# GridRestore: project overview

GridRestore is a teaching and research project on power-grid restoration after an outage. It has two parts that
share a repository but not data: a **scheduling application** that orders repair work under a budget and a crew
limit, and a **physics study** that tests power networks against standard benchmarks. All data is synthetic or
from published benchmark networks. This is an academic demonstration, not an operational control system.

This document explains the project as a whole and points to the detailed documents. Start here; read the others
when you need the detail.

## 1. What the project asks

1. **Scheduling.** After an outage, which repairs should crews do first, given a budget, a number of crews, the
   skills each crew has, and the fact that some repairs must wait for others? Several heuristics are compared with an
   exact solver on small instances.
2. **Physics.** On standard test networks (IEEE cases), how close is a network to its thermal and voltage limits as
   load grows? Can a restoration decision be informed by an operating-state model? Can false data injected into the
   state estimator stay hidden from the bad-data test?

## 2. Two parts, one repository

| | Scheduling application | Physics study |
| --- | --- | --- |
| Data | Synthetic scenarios, repair tasks, grid nodes and edges, in PostgreSQL | IEEE benchmark networks from pandapower, in memory |
| Computation | Heuristic schedulers, criticality, versions, analytics, MILP baseline | Power flow, state estimation, attack experiments, MDP |
| Output | Runs, reports, dashboards, audit, CSV | CSV and PNG artifacts, one stored run in the database |
| Interface | REST API and Next.js web app | Read-only REST endpoints and a Physics tab |
| Main code | `backend/*.py`, `frontend/` | `backend/grid/`, `backend/physics_api.py` |

The two parts are linked only in the sense that they live together; their data is not connected. Connecting them
would need a mapping from repair tasks to physical network elements, which has not been decided. See section 6.

## 3. Architecture

- **Database (PostgreSQL 16 or 18, with pgvector and btree_gist).** Schema in `database/schema.sql`, then migrations
  002 to 007 (embeddings, users and roles, outage causes, integrity and audit, physics results, physics extensions).
  The crew-overlap rule is an exclusion constraint in the database, not only in the application.
- **API (FastAPI).** `backend/api.py` holds the scheduling endpoints; `backend/physics_api.py` the physics reads.
  Two roles: admin (changes data, sees the audit) and operator (views and runs schedules).
- **Frontend (Next.js).** Tabs for scenarios, scheduling, runs, similar-repair search, criticality, grid map, CSV
  data, audit (admin) and physics.
- **Physics layer (`backend/grid/`).** Models, solvers, attacks and the MDP, with a study driver that writes artifacts
  and stores one run.
- **Tests.** About 160 automated tests across scheduling, the database rules, the API, and the physics models.

For tables and relationships see `docs/ERD.md`; for the design see `docs/ARCHITECTURE.md`.

## 4. Scheduling: what it does and what it has shown

- Heuristics: priority-first, shortest-repair-first, and a score combining weight, priority and speed.
- Each run is saved with its actions, so runs can be compared task by task ("what changed"), reported in Markdown,
  and checked for robustness across seeded duration noise with confidence intervals.
- Scenario versions record every edit, and rollback restores an earlier state without deleting history.
- An exact mixed-integer baseline measures how far each heuristic is from the optimum on small instances. On 200
  random instances the score heuristic averaged about 15% below the optimum (`docs/METHODOLOGY.md`).
- Benchmark: 500 nodes, 50 scenarios of 500 repair tasks each. Measured effects: a composite index gives about a
  five-fold speed-up on the scenario query; the materialized dashboard view is about 50 times faster than the live
  aggregate; the crew-overlap constraint roughly doubles bulk-insert cost (`docs/PERFORMANCE.md`).

## 5. Physics: what it does and what it has shown

- **Models validated against pandapower.** DC power flow and PTDF; AC measurement model and state estimator; the
  analytic Jacobian (checked against a numerical reference); an own Newton power-flow solver that reproduces
  pandapower from a flat start to about 1e-11 rad.
- **Generator reactive limits are enforced.** This is the most important modelling correction: without them the
  loadability is overstated by up to about two times (case14 voltage limit 3.36 unlimited, 1.60 limited).
- **Load margins** (headline, reactive limits enforced): voltage limit reached at 1.60 (case14), 2.46 (case30),
  1.78 (case9), 1.78 (case118); nose (solver limit) at 1.78, 2.85, 2.47 and 2.14 respectively. The bisection and an
  independent tracer agree on case9, case14, case30 and case57; on case118 they do not (section 8).
- **Attacks.** Stealthy false-data injection, confined to compromised sensors and bounded to 15 % per measurement,
  leaves the bad-data residual unchanged on the linear model (exactly) and nearly unchanged on the AC model. At a
  calibrated 1 % false-alarm rate, neither the stealthy nor the targeted attack is detected by the largest-normalised
  residual test. Attacks shift estimated flows by at most about 0.13 pu in the targeted case.
- **Operating-state MDP.** Three actions (do nothing, isolate a node, shed 20 % of load) over four states. With the
  headline reward weights, load shedding is optimal in the thermal state (except on one contingency, where isolation
  is optimal). Under the plan's own weights, doing nothing is optimal everywhere. The action-cost weight is derived
  by a stated rule, not from costs (`docs/PHYSICS.md` section 5.2).
- Full method, corrections and limits: `docs/PHYSICS.md`.

## 6. Open decisions

These need a decision from the project owner before the work can go further:

1. **Connect or keep separate.** Keep the two analyses separate and label them (the current state), or design a
   mapping from repair tasks to network elements, which needs a meaning for the link and a source for the costs.
2. **Benchmark size.** The benchmark assumes 500 repair tasks per scenario (25,000 in total). If 500 in total was
   meant, the benchmark and its performance figures must be redone.
3. **case118 headline.** The physics bisection and the traced branch give different loadability on case118 (2.14 and
   2.11). The bisection follows a different solution branch from the one connected to the operating point. Choose
   which value is the headline and how it is labelled (`docs/PHYSICS.md` section 5.8).
4. **Headline action-cost weight.** The current value comes from a decision rule. Replacing it with a value derived
   from repair costs needs the cost scale and the link in decision 1.

## 7. Verification status

| Area | Status |
| --- | --- |
| Scheduling logic, rules, API, roles, CSV, versions | Automated tests; passed at the last full run |
| Physics models and solvers | Automated tests against pandapower; passed at the last full run |
| Physics study results | Re-checked against the artifacts; corrected values are recorded in `CHANGES.md` |
| Browser UI | Re-verified 2026-10-23 against a fresh `npm ci && npm run build` production build (`next start -p 3000`): page loads (HTTP 200) and its API round-trips succeed — login admin, scenario list (5), vector search top-2 for "hospital water supply down" returns T07 (hospital branch repair) and T05 (water facility pump). A scripted HTTP check replaces the earlier automated-browser run; a full click-through in a real browser is still worth doing before the demo |
| Docker stack | Run and verified: db healthy, seed loaded demo data and 8 embeddings, API `/health` ok (2026-10-23) |
| Full test suite on the final tree | Not re-run after the last documentation edits; run it before relying on it |

Instructions for running everything and for the checks by hand are in `docs/RUNNING.md`.

## 8. Known limits

- **Scope of physics.** IEEE test networks only, with line ratings set to a base loading of 60 %. Active-power
  limits are not enforced, and dispatch is proportional rather than optimal.
- **Assumed thresholds.** The 80 %, 100 %, 0.85 pu and 0.95 pu limits, the state representatives, and the collapse
  voltage scale are modelling assumptions, not regulatory values.
- **MDP.** One-step transitions with no multi-step load growth. Results depend on the voltage scale and the
  discount factor, which are swept but assumed.
- **Cyber model.** A stylised four-tier topology. It is not a vulnerability assessment.
- **Scheduling data.** Synthetic. The heuristics are greedy; their gaps to the optimum are measured only on small
  instances.
- **Demo security.** Demo passwords are for local use only.

## 9. Where to look next

| Question | Document |
| --- | --- |
| How do I install and run it? | `docs/RUNNING.md` |
| How is the database built? | `docs/ERD.md`, `database/` |
| How is the system designed? | `docs/ARCHITECTURE.md`, `docs/IMPLEMENTATION_NOTES.md` |
| How were the scheduling results measured? | `docs/METHODOLOGY.md`, `docs/PERFORMANCE.md` |
| How were the physics results obtained, and what was corrected? | `docs/PHYSICS.md`, `CHANGES.md` |
| What is tested, and how? | `docs/TESTING.md`, `docs/RUNNING.md` section 8 |
| Standards and conventions | `docs/STANDARDS.md` |
