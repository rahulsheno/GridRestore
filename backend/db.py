"""PostgreSQL access layer. Requires DATABASE_URL in the environment."""
import os
from contextlib import contextmanager
from dotenv import load_dotenv
import psycopg
from psycopg.rows import dict_row

load_dotenv()

def get_database_url():
    url = os.getenv("DATABASE_URL")
    if not url:
        raise RuntimeError("DATABASE_URL is missing. Copy .env.example to .env and configure PostgreSQL.")
    return url

@contextmanager
def connect():
    """Connection context; psycopg commits on successful context exit and rolls back on error."""
    with psycopg.connect(get_database_url(), row_factory=dict_row) as conn:
        yield conn

def health_check():
    with connect() as conn:
        return conn.execute("SELECT current_database() AS database, version() AS version").fetchone()

def list_scenarios():
    with connect() as conn:
        return conn.execute(
            "SELECT scenario_id, scenario_name, budget, crew_count, created_at "
            "FROM outage_scenarios ORDER BY scenario_id DESC"
        ).fetchall()

def create_scenario(name: str, budget: float, crew_count: int):
    if not name.strip():
        raise ValueError("Scenario name cannot be empty")
    if budget <= 0 or crew_count < 1:
        raise ValueError("Budget must be positive and crew count must be at least one")
    with connect() as conn:
        row = conn.execute(
            "INSERT INTO outage_scenarios(scenario_name,budget,crew_count) "
            "VALUES (%s,%s,%s) RETURNING scenario_id,scenario_name,budget,crew_count,created_at",
            (name.strip(), budget, crew_count)
        ).fetchone()
        return row

def list_runs(scenario_id=None):
    sql = ("SELECT r.run_id,r.scenario_id,s.scenario_name,r.strategy_name,r.total_cost,"
           "r.makespan_hours,r.weighted_recovery_score,r.started_at "
           "FROM restoration_runs r JOIN outage_scenarios s USING(scenario_id)")
    params = ()
    if scenario_id is not None:
        sql += " WHERE r.scenario_id=%s"
        params = (scenario_id,)
    sql += " ORDER BY r.started_at DESC"
    with connect() as conn:
        return conn.execute(sql, params).fetchall()

def get_scenario_tasks(scenario_id):
    """Return repair tasks plus dependencies for one scenario."""
    with connect() as conn:
        tasks = conn.execute(
            "SELECT task_id, estimated_hours, estimated_cost, service_weight, "
            "priority, required_skill FROM repair_tasks WHERE scenario_id=%s "
            "ORDER BY task_id",
            (scenario_id,),
        ).fetchall()
        deps = conn.execute(
            "SELECT d.task_id, d.prerequisite_task_id FROM task_dependencies d "
            "JOIN repair_tasks t ON t.task_id=d.task_id "
            "WHERE t.scenario_id=%s",
            (scenario_id,),
        ).fetchall()
    dependencies = {}
    for row in deps:
        dependencies.setdefault(row["task_id"], []).append(row["prerequisite_task_id"])
    return tasks, dependencies

def save_run(scenario_id, result, notes=None):
    """Validate a scheduler result and persist it transactionally."""
    actions = result.get("actions", [])
    if not actions:
        raise ValueError("Nothing to save: schedule contains no actions")
    total = round(sum(float(a["estimated_cost"]) for a in actions), 2)
    if abs(total - float(result["total_cost"])) > 0.01:
        raise ValueError("Result total_cost does not match summed actions")
    for action in actions:
        if action["finish_hour"] <= action["start_hour"]:
            raise ValueError(f"Invalid timing for task {action['task_id']}")
    with connect() as conn:
        with conn.cursor() as cur:
            run = cur.execute(
                "INSERT INTO restoration_runs(scenario_id,strategy_name,total_cost,"
                "makespan_hours,weighted_recovery_score,notes) "
                "VALUES (%s,%s,%s,%s,%s,%s) RETURNING run_id",
                (scenario_id, result["strategy"], result["total_cost"],
                 result["makespan_hours"], result["weighted_recovery_score"],
                 __import__("json").dumps(notes or {})),
            ).fetchone()
            run_id = run["run_id"]
            cur.executemany(
                "INSERT INTO scheduled_actions(run_id,task_id,crew_label,start_hour,finish_hour) "
                "VALUES (%s,%s,%s,%s,%s)",
                [(run_id, a["task_id"], a["crew_id"], a["start_hour"], a["finish_hour"])
                 for a in actions],
            )
            return run_id

def list_run_actions(run_id):
    with connect() as conn:
        return conn.execute(
            "SELECT task_id, crew_label, start_hour, finish_hour "
            "FROM scheduled_actions WHERE run_id=%s ORDER BY start_hour",
            (run_id,),
        ).fetchall()
