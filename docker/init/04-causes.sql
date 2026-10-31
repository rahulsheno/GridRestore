-- Migration 004: outage-cause texture column + scale-test support.
-- outage_cause gives GROUP BY/HAVING demo texture; scale_seed.py bulk-loads
-- deterministic synthetic volume for the performance story.
ALTER TABLE repair_tasks
  ADD COLUMN IF NOT EXISTS outage_cause TEXT NOT NULL DEFAULT 'unknown'
  CHECK (outage_cause IN ('storm','equipment_age','vehicle_impact','vegetation','unknown'));

-- Backfill existing demo rows sensibly (idempotent).
UPDATE repair_tasks SET outage_cause =
  CASE
    WHEN task_id IN ('T01','T02','T03') THEN 'storm'
    WHEN task_id IN ('T04','T08') THEN 'vegetation'
    WHEN task_id = 'T06' THEN 'equipment_age'
    WHEN task_id IN ('T05','T07') THEN 'vehicle_impact'
    ELSE 'unknown'
  END
WHERE outage_cause = 'unknown';

CREATE INDEX IF NOT EXISTS idx_tasks_cause ON repair_tasks(outage_cause);
