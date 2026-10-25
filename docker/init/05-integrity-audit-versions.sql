-- Migration 005
--   1. Crew overlap prevention with an EXCLUDE constraint (a rule a plain CHECK cannot express:
--      it compares rows with each other).
--   2. Generic audit trigger, attached to repair_tasks, outage_scenarios and restoration_runs.
--      Stores old/new row images and the application user (set per transaction via app.username).
--   3. Scenario versioning: every edit to a scenario's tasks writes a full snapshot.
--   4. Materialized view for dashboards, refreshed on demand.
-- Idempotent: safe to re-run.

CREATE EXTENSION IF NOT EXISTS btree_gist;

-- ---------------------------------------------------------------------------
-- 1. Overlap prevention: one crew, one run, one time window at a time.
--    '[)' means touching intervals ([0,2) and [2,4)) do NOT overlap.
-- ---------------------------------------------------------------------------
ALTER TABLE scheduled_actions
  ADD COLUMN IF NOT EXISTS crew_span NUMRANGE
  GENERATED ALWAYS AS (numrange(start_hour, finish_hour, '[)')) STORED;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'excl_crew_overlap') THEN
    ALTER TABLE scheduled_actions
      ADD CONSTRAINT excl_crew_overlap
      EXCLUDE USING gist (run_id WITH =, crew_label WITH =, crew_span WITH &&);
  END IF;
END $$;

-- ---------------------------------------------------------------------------
-- 2. Generic audit trigger
-- ---------------------------------------------------------------------------
ALTER TABLE audit_log ADD COLUMN IF NOT EXISTS old_data JSONB;
ALTER TABLE audit_log ADD COLUMN IF NOT EXISTS new_data JSONB;
ALTER TABLE audit_log ADD COLUMN IF NOT EXISTS app_user TEXT;

CREATE INDEX IF NOT EXISTS idx_audit_table_time ON audit_log(table_name, changed_at);
CREATE INDEX IF NOT EXISTS idx_audit_row_key ON audit_log(row_key);

-- TG_ARGV[0] is the primary-key column name of the audited table.
CREATE OR REPLACE FUNCTION audit_generic_change() RETURNS TRIGGER LANGUAGE plpgsql AS $$
DECLARE
  key_col TEXT := TG_ARGV[0];
  row_key TEXT;
BEGIN
  IF TG_OP = 'DELETE' THEN
    row_key := to_jsonb(OLD) ->> key_col;
  ELSE
    row_key := to_jsonb(NEW) ->> key_col;
  END IF;
  INSERT INTO audit_log(table_name, operation, row_key, old_data, new_data, app_user)
  VALUES (
    TG_TABLE_NAME,
    TG_OP,
    row_key,
    CASE WHEN TG_OP <> 'INSERT' THEN to_jsonb(OLD) END,
    CASE WHEN TG_OP <> 'DELETE' THEN to_jsonb(NEW) END,
    NULLIF(current_setting('app.username', true), '')
  );
  IF TG_OP = 'DELETE' THEN
    RETURN OLD;
  END IF;
  RETURN NEW;
END $$;

DROP TRIGGER IF EXISTS trg_repair_task_audit ON repair_tasks;
CREATE TRIGGER trg_repair_task_audit
  AFTER INSERT OR UPDATE OR DELETE ON repair_tasks
  FOR EACH ROW EXECUTE FUNCTION audit_generic_change('task_id');

DROP TRIGGER IF EXISTS trg_scenario_audit ON outage_scenarios;
CREATE TRIGGER trg_scenario_audit
  AFTER INSERT OR UPDATE OR DELETE ON outage_scenarios
  FOR EACH ROW EXECUTE FUNCTION audit_generic_change('scenario_id');

DROP TRIGGER IF EXISTS trg_run_audit ON restoration_runs;
CREATE TRIGGER trg_run_audit
  AFTER INSERT OR UPDATE OR DELETE ON restoration_runs
  FOR EACH ROW EXECUTE FUNCTION audit_generic_change('run_id');

-- ---------------------------------------------------------------------------
-- 3. Scenario versioning: full snapshot per version (version_no is 1, 2, 3 ...).
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS scenario_versions (
  scenario_id BIGINT NOT NULL REFERENCES outage_scenarios(scenario_id) ON DELETE CASCADE,
  version_no INTEGER NOT NULL CHECK (version_no >= 1),
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  created_by TEXT NOT NULL,
  note TEXT NOT NULL DEFAULT '',
  snapshot JSONB NOT NULL CHECK (jsonb_typeof(snapshot) = 'object'),
  PRIMARY KEY (scenario_id, version_no)
);

-- ---------------------------------------------------------------------------
-- 4. Materialized view for the dashboard: per scenario + strategy run statistics.
--    Refresh with REFRESH MATERIALIZED VIEW CONCURRENTLY (needs the unique index).
-- ---------------------------------------------------------------------------
CREATE MATERIALIZED VIEW IF NOT EXISTS mv_scenario_run_stats AS
SELECT r.scenario_id,
       r.strategy_name,
       COUNT(DISTINCT r.run_id)::INT                 AS run_count,
       ROUND(AVG(r.total_cost), 2)                   AS avg_cost,
       ROUND(AVG(r.makespan_hours), 2)               AS avg_makespan_hours,
       MAX(r.weighted_recovery_score)                AS best_score,
       COUNT(a.action_id)::INT                       AS scheduled_actions,
       MAX(r.started_at)                             AS last_run_at
FROM restoration_runs r
LEFT JOIN scheduled_actions a ON a.run_id = r.run_id
GROUP BY r.scenario_id, r.strategy_name
WITH DATA;

CREATE UNIQUE INDEX IF NOT EXISTS ux_mv_scenario_run_stats
  ON mv_scenario_run_stats(scenario_id, strategy_name);
