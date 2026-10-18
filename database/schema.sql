CREATE TABLE IF NOT EXISTS grid_nodes (
 node_id TEXT PRIMARY KEY, node_name TEXT NOT NULL, node_type TEXT NOT NULL,
 criticality NUMERIC(5,2) NOT NULL CHECK(criticality BETWEEN 0 AND 10), region_code TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS grid_edges (
 edge_id TEXT PRIMARY KEY, from_node_id TEXT NOT NULL REFERENCES grid_nodes(node_id),
 to_node_id TEXT NOT NULL REFERENCES grid_nodes(node_id), component_type TEXT NOT NULL,
 nominal_capacity_kw NUMERIC(12,2) NOT NULL CHECK(nominal_capacity_kw>0),
 UNIQUE(from_node_id,to_node_id)
);
CREATE TABLE IF NOT EXISTS outage_scenarios (
 scenario_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
 scenario_name TEXT NOT NULL CHECK(length(trim(scenario_name))>0),
 created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
 budget NUMERIC(12,2) NOT NULL CHECK(budget>0),
 crew_count INTEGER NOT NULL CHECK(crew_count>0)
);
CREATE TABLE IF NOT EXISTS repair_tasks (
 task_id TEXT PRIMARY KEY, scenario_id BIGINT NOT NULL REFERENCES outage_scenarios(scenario_id) ON DELETE CASCADE,
 edge_id TEXT NOT NULL REFERENCES grid_edges(edge_id), component_name TEXT NOT NULL,
 estimated_hours NUMERIC(8,2) NOT NULL CHECK(estimated_hours>0),
 estimated_cost NUMERIC(12,2) NOT NULL CHECK(estimated_cost>=0),
 service_weight NUMERIC(8,2) NOT NULL CHECK(service_weight>=0),
 priority SMALLINT NOT NULL CHECK(priority BETWEEN 1 AND 5),
 region_code TEXT NOT NULL DEFAULT 'Unassigned',
 required_skill TEXT NOT NULL DEFAULT 'general',
 status TEXT NOT NULL DEFAULT 'pending' CHECK(status IN ('pending','scheduled','completed','blocked'))
);
CREATE TABLE IF NOT EXISTS task_dependencies (
 task_id TEXT NOT NULL REFERENCES repair_tasks(task_id) ON DELETE CASCADE,
 prerequisite_task_id TEXT NOT NULL REFERENCES repair_tasks(task_id) ON DELETE CASCADE,
 PRIMARY KEY(task_id,prerequisite_task_id),
 CHECK(task_id<>prerequisite_task_id)
);
CREATE TABLE IF NOT EXISTS crews (
 crew_id TEXT PRIMARY KEY, crew_name TEXT NOT NULL,
 skill TEXT NOT NULL, available_from NUMERIC(10,2) NOT NULL DEFAULT 0 CHECK(available_from>=0)
);
CREATE TABLE IF NOT EXISTS restoration_runs (
 run_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
 scenario_id BIGINT NOT NULL REFERENCES outage_scenarios(scenario_id) ON DELETE CASCADE,
 strategy_name TEXT NOT NULL, started_at TIMESTAMPTZ NOT NULL DEFAULT now(),
 total_cost NUMERIC(12,2) NOT NULL CHECK(total_cost>=0),
 makespan_hours NUMERIC(10,2) NOT NULL CHECK(makespan_hours>=0),
 weighted_recovery_score NUMERIC(12,4) NOT NULL,
 notes JSONB NOT NULL DEFAULT '{}'::jsonb
);
CREATE TABLE IF NOT EXISTS scheduled_actions (
 action_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
 run_id BIGINT NOT NULL REFERENCES restoration_runs(run_id) ON DELETE CASCADE,
 task_id TEXT NOT NULL REFERENCES repair_tasks(task_id),
 crew_label TEXT NOT NULL, start_hour NUMERIC(10,2) NOT NULL CHECK(start_hour>=0),
 finish_hour NUMERIC(10,2) NOT NULL CHECK(finish_hour>start_hour),
 UNIQUE(run_id,task_id)
);
CREATE TABLE IF NOT EXISTS audit_log (
 audit_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY, table_name TEXT NOT NULL,
 operation TEXT NOT NULL, row_key TEXT, changed_at TIMESTAMPTZ NOT NULL DEFAULT now(),
 db_user TEXT NOT NULL DEFAULT current_user
);
CREATE OR REPLACE FUNCTION audit_repair_task_change() RETURNS TRIGGER LANGUAGE plpgsql AS $$
BEGIN
 INSERT INTO audit_log(table_name,operation,row_key)
 VALUES('repair_tasks',TG_OP,COALESCE(NEW.task_id,OLD.task_id));
 IF TG_OP='DELETE' THEN RETURN OLD; ELSE RETURN NEW; END IF;
END; $$;
DROP TRIGGER IF EXISTS trg_repair_task_audit ON repair_tasks;
CREATE TRIGGER trg_repair_task_audit AFTER INSERT OR UPDATE OR DELETE ON repair_tasks
 FOR EACH ROW EXECUTE FUNCTION audit_repair_task_change();
CREATE INDEX IF NOT EXISTS idx_nodes_region ON grid_nodes(region_code);
CREATE INDEX IF NOT EXISTS idx_tasks_scenario_status ON repair_tasks(scenario_id,status);
CREATE INDEX IF NOT EXISTS idx_runs_scenario_strategy ON restoration_runs(scenario_id,strategy_name);
CREATE INDEX IF NOT EXISTS idx_actions_run_time ON scheduled_actions(run_id,start_hour);
CREATE VIEW v_restoration_run_summary AS
 SELECT r.run_id,s.scenario_name,r.strategy_name,r.total_cost,r.makespan_hours,
 r.weighted_recovery_score,COUNT(a.action_id) AS scheduled_task_count
 FROM restoration_runs r JOIN outage_scenarios s USING(scenario_id)
 LEFT JOIN scheduled_actions a USING(run_id)
 GROUP BY r.run_id,s.scenario_name,r.strategy_name,r.total_cost,r.makespan_hours,r.weighted_recovery_score;
