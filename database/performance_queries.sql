-- Run after creating representative data. EXPLAIN ANALYZE executes the query.
EXPLAIN (ANALYZE, BUFFERS)
SELECT scenario_id, status, COUNT(*)
FROM repair_tasks
WHERE scenario_id = 1
GROUP BY scenario_id, status;

EXPLAIN (ANALYZE, BUFFERS)
SELECT r.strategy_name, AVG(r.weighted_recovery_score)
FROM restoration_runs r
WHERE r.scenario_id = 1
GROUP BY r.strategy_name;

-- Inspect indexes and query plans; timings depend on data volume and hardware.
