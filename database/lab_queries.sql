-- Lab query pack: JOIN / GROUP BY / HAVING / ORDER BY / aggregates / subqueries.
-- 1. Run summary with task counts (JOIN + GROUP BY + ORDER BY).
SELECT r.run_id, s.scenario_name, r.strategy_name, r.total_cost,
       COUNT(a.action_id) AS scheduled_tasks
FROM restoration_runs r
JOIN outage_scenarios s USING (scenario_id)
LEFT JOIN scheduled_actions a USING (run_id)
GROUP BY r.run_id, s.scenario_name, r.strategy_name, r.total_cost
ORDER BY r.total_cost DESC;

-- 2. Strategies whose average score beats the global average (HAVING + subquery).
SELECT r.strategy_name, AVG(r.weighted_recovery_score) AS avg_score,
       COUNT(*) AS runs
FROM restoration_runs r
GROUP BY r.strategy_name
HAVING AVG(r.weighted_recovery_score) >
       (SELECT AVG(weighted_recovery_score) FROM restoration_runs)
ORDER BY avg_score DESC;

-- 3. Tasks with above-average service weight in their scenario (correlated subquery).
SELECT t.task_id, t.component_name, t.service_weight
FROM repair_tasks t
WHERE t.service_weight >
      (SELECT AVG(t2.service_weight) FROM repair_tasks t2
       WHERE t2.scenario_id = t.scenario_id)
ORDER BY t.service_weight DESC;

-- 4. Skill coverage per scenario (aggregate + GROUP BY).
SELECT t.scenario_id, t.required_skill, COUNT(*) AS task_count,
       MIN(t.estimated_cost) AS min_cost, MAX(t.estimated_cost) AS max_cost
FROM repair_tasks t
GROUP BY t.scenario_id, t.required_skill
ORDER BY t.scenario_id, task_count DESC;

-- 5. Vector similarity (second paradigm) + full-text companion.
-- SELECT * FROM search_similar_repairs('[0.1,...]'::vector(32), 5);
-- SELECT task_id, narrative FROM repair_embeddings
-- WHERE narrative_tsv @@ plainto_tsquery('english', 'hospital');

-- 6. Critical repairs: downstream unblock count via recursive CTE.
-- A repair is "critical" if many other tasks transitively depend on it.
-- Restorer framing: fix high unblock-count tasks first to free the schedule.
WITH RECURSIVE downstream(root_id, task_id) AS (
  SELECT prerequisite_task_id, task_id FROM task_dependencies
  UNION
  SELECT d.root_id, t.task_id
  FROM task_dependencies t JOIN downstream d ON d.task_id = t.prerequisite_task_id
)
SELECT t.task_id, t.component_name, t.service_weight, t.priority,
       COUNT(DISTINCT d.task_id) AS unblocks_count,
       COALESCE(SUM(dt.service_weight), 0) AS unblocked_service_weight
FROM repair_tasks t
LEFT JOIN downstream d ON d.root_id = t.task_id
LEFT JOIN repair_tasks dt ON dt.task_id = d.task_id
WHERE t.scenario_id = 1
GROUP BY t.task_id, t.component_name, t.service_weight, t.priority
ORDER BY unblocks_count DESC, unblocked_service_weight DESC;

-- 7. Critical path inputs: task durations + dependency edges per scenario.
-- SELECT task_id, estimated_hours FROM repair_tasks WHERE scenario_id = 1 ORDER BY task_id;
-- SELECT task_id, prerequisite_task_id FROM task_dependencies
-- WHERE task_id IN (SELECT task_id FROM repair_tasks WHERE scenario_id = 1);
