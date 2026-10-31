# Query performance (EXPLAIN ANALYZE — PostgreSQL 18.6, scale scenario 4)

Scale dataset, deterministic seed 20261018 (`python -m backend.scale_seed`):
10,000 repair_tasks, 2,000 chain dependencies, 500 runs + 4,000 actions,
5,008 embeddings. Demo rows (T01..T08) untouched.

## Q1 — Tasks by status, 10k rows (B-tree idx_tasks_scenario_status)

GroupAggregate cost=0.29..301.29 actual 3.035ms rows=1. Index Only Scan,
10,000 rows, Heap Fetches 0, 1 index search, shared hit 13.
Planning 3.382ms, Execution 3.256ms.
Reading: covering index serves all 10k rows with zero heap fetches.

## Q2 — Avg score by strategy, 500 runs

HashAggregate actual 0.492..0.499ms rows=3. Seq Scan on restoration_runs,
500 rows qualify of 503, so the planner correctly skips the index — 500 index
probes would cost more than one sequential pass plus hash.
Planning 3.172ms, Execution 0.658ms.
Reading for viva: indexes win on selective predicates, not near-full scans.

## Q3 — Vector similarity, 5,008 embeddings (HNSW idx_repair_embeddings_vector)

Limit cost=120.74..122.66 actual 1.876..1.888ms rows=5. InitPlan via PK for the
query vector, then HNSW Index Scan serving ORDER BY embedding <=> query,
1 index search, shared hit 693. Planning 4.684ms, Execution 2.131ms.
Reading: top-5 cosine neighbours in ~2ms over 5k vectors, no brute force.

## Q4 — Outage-cause breakdown, 10k rows (GROUP BY + HAVING + sort)

Sort cost=524.19..524.20 actual 4.887..4.888ms rows=5. HashAggregate over 10k
rows, Filter count(*)>500, quicksort 25kB. Seq Scan 10k rows is correct here —
unselective aggregate; idx_tasks_cause serves selective per-cause lookups.
Planning 3.565ms, Execution 4.990ms.

---

# Benchmark dataset and measured choices (this revision)

Environment for these numbers: **PostgreSQL 16.15** (Ubuntu package) with pgvector 0.8, in a
container. The earlier sections of this file were measured on PostgreSQL 18.6 and are kept as
they were; the numbers below are not comparable with them.

Dataset (`python -m backend.bench_seed`, deterministic seed 20261018, built in about 14 s):
500 grid nodes and 499 edges (a spanning tree), 50 scenarios with 500 repair tasks each (25,000
tasks in total, a dependency every fifth task), and 150 runs produced by the real scheduler and
saved through `save_run`. The current database also holds 2 runs created by the API tests, so the
counts printed by `python -m backend.benchmark` are slightly higher (152 runs).

Reproduce: `python -m backend.benchmark` writes `docs/benchmark_results.json`. Medians of 30
runs, milliseconds. Each index is dropped inside a transaction that is rolled back.

| Measurement | With | Without | Notes |
| --- | ---: | ---: | --- |
| Pending tasks of one scenario (`idx_tasks_scenario_status`) | 0.46 | 2.52 | Bitmap heap scan vs sequential scan over 25k rows. About 5x. |
| Scheduled actions of one run (`idx_actions_run_time`) | 0.35 | 0.41 | No meaningful gain at 165 rows. Without the index the planner uses `UNIQUE(run_id, task_id)` and sorts. |
| Dashboard: run statistics | 17.07 (live) | 0.33 (materialized view) | About 50x. Live aggregates base tables with a join. |
| Materialized view refresh (`REFRESH ... CONCURRENTLY`) | 29.4 | n/a | Paid on demand; the API reports staleness when runs were added since the last refresh. |
| Bulk insert of 2,000 actions with the crew-overlap constraint | 180.3 | 98.7 | The exclusion constraint roughly doubles the cost of bulk inserts. That is the price of enforcing the rule in the database. |

What this says for the lab:

- Indexes matter on selective predicates. The composite index on `(scenario_id, status)` gives a
  consistent 5x here. The run-actions index does not, because the unique constraint already gives the planner a
  usable path. A reviewer who asks "is this index needed?" should be shown this table, not an assumption.
- The materialized view pays off for reads that aggregate many rows and happen often. Refresh
  costs about 30 ms here, so refreshing after each run would be wasteful; refreshing on demand is the
  right trade-off.
- The overlap constraint has a measurable write cost. It is still worth it: the rule cannot be
  expressed as a CHECK, and the application-level check alone would not stop a second writer.

Budget/crew sweep on the benchmark scenario (`python -m backend.analytics <scenario_id>`,
output in `docs/sweep_results.csv` and `docs/figures/sweep_budget_crews.png`): 10 budgets
from 5% to 60% of total repair cost, 1 to 6 crews, 3 strategies (180 runs). In the figure, the
`gridrestore_score` heuristic leads at every budget, and `priority_first` trails far behind.
Makespan falls with diminishing returns as crews are added; the largest gains are from one to three crews.
