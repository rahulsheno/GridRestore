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
