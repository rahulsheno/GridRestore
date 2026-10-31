"""PostgreSQL access layer. Requires DATABASE_URL in the environment."""
import os
from contextlib import contextmanager
from dotenv import load_dotenv
import psycopg
from psycopg.rows import dict_row
from psycopg.errors import ExclusionViolation

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

def _template_scenario(cur):
    """Oldest scenario that already has tasks; the source for new scenario task lists."""
    row = cur.execute(
        "SELECT s.scenario_id FROM outage_scenarios s "
        "WHERE EXISTS (SELECT 1 FROM repair_tasks t WHERE t.scenario_id=s.scenario_id) "
        "ORDER BY s.scenario_id LIMIT 1"
    ).fetchone()
    return row["scenario_id"] if row else None


def _copy_template_tasks(cur, scenario_id, template_id):
    """Copy a scenario's tasks and dependencies using scenario-scoped ids.

    Task ids are globally unique, so cloned rows get `S<scenario>-T01`, `S<scenario>-T02`,
    ... in template order. Embeddings are intentionally not copied: repair narratives are
    indexed separately by `backend.vectors.seed_embeddings`.
    """
    if cur.execute("SELECT 1 FROM repair_tasks WHERE scenario_id=%s LIMIT 1",
                   (scenario_id,)).fetchone():
        return 0
    rows = cur.execute(
        "SELECT task_id, edge_id, component_name, estimated_hours, estimated_cost, "
        "service_weight, priority, region_code, required_skill, outage_cause "
        "FROM repair_tasks WHERE scenario_id=%s ORDER BY task_id",
        (template_id,),
    ).fetchall()
    if not rows:
        return 0
    mapping = {row["task_id"]: f"S{scenario_id}-T{index:02d}"
               for index, row in enumerate(rows, 1)}
    cur.executemany(
        "INSERT INTO repair_tasks(task_id, scenario_id, edge_id, component_name, estimated_hours, "
        "estimated_cost, service_weight, priority, region_code, required_skill, outage_cause, status) "
        "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'pending')",
        [(mapping[row["task_id"]], scenario_id, row["edge_id"], row["component_name"],
          row["estimated_hours"], row["estimated_cost"], row["service_weight"],
          row["priority"], row["region_code"], row["required_skill"], row["outage_cause"])
         for row in rows],
    )
    deps = cur.execute(
        "SELECT d.task_id, d.prerequisite_task_id FROM task_dependencies d "
        "JOIN repair_tasks t ON t.task_id=d.task_id WHERE t.scenario_id=%s",
        (template_id,),
    ).fetchall()
    if deps:
        cur.executemany(
            "INSERT INTO task_dependencies(task_id,prerequisite_task_id) VALUES (%s,%s) "
            "ON CONFLICT DO NOTHING",
            [(mapping[d["task_id"]], mapping[d["prerequisite_task_id"]]) for d in deps
             if d["task_id"] in mapping and d["prerequisite_task_id"] in mapping],
        )
    return len(rows)


def create_scenario(name: str, budget: float, crew_count: int, username=None):
    if not name.strip():
        raise ValueError("Scenario name cannot be empty")
    if budget <= 0 or crew_count < 1:
        raise ValueError("Budget must be positive and crew count must be at least one")
    with connect() as conn:
        with conn.cursor() as cur:
            if username:
                set_app_user(cur, username)
            row = cur.execute(
                "INSERT INTO outage_scenarios(scenario_name,budget,crew_count) "
                "VALUES (%s,%s,%s) RETURNING scenario_id,scenario_name,budget,crew_count,created_at",
                (name.strip(), budget, crew_count)
            ).fetchone()
            template_id = _template_scenario(cur)
            if template_id is not None:
                _copy_template_tasks(cur, row["scenario_id"], template_id)
            return row


def backfill_scenario_tasks():
    """Copy the demo task set into scenarios that were created before task cloning.

    Returns {scenario_id: copied_task_count}. Run with `python -m backend.backfill_scenarios`.
    """
    with connect() as conn:
        with conn.cursor() as cur:
            template_id = _template_scenario(cur)
            if template_id is None:
                return {}
            empty = cur.execute(
                "SELECT s.scenario_id FROM outage_scenarios s "
                "WHERE NOT EXISTS (SELECT 1 FROM repair_tasks t WHERE t.scenario_id=s.scenario_id) "
                "ORDER BY s.scenario_id"
            ).fetchall()
            return {row["scenario_id"]: _copy_template_tasks(cur, row["scenario_id"], template_id)
                    for row in empty}

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

def set_app_user(cur, username):
    """Record the application user for audit rows written in this transaction (app.username)."""
    if username:
        cur.execute("SELECT set_config('app.username', %s, true)", (username,))

def save_run(scenario_id, result, notes=None, username=None):
    """Validate a scheduler result and persist it transactionally.

    The exclusion constraint excl_crew_overlap (migration 005) is the last line of defence:
    a crew that is double-booked in one run is rejected by PostgreSQL and reported as a ValueError.
    """
    actions = result.get("actions", [])
    if not actions:
        raise ValueError("Nothing to save: schedule contains no actions")
    total = round(sum(float(a["estimated_cost"]) for a in actions), 2)
    if abs(total - float(result["total_cost"])) > 0.01:
        raise ValueError("Result total_cost does not match summed actions")
    for action in actions:
        if action["finish_hour"] <= action["start_hour"]:
            raise ValueError(f"Invalid timing for task {action['task_id']}")
    try:
        return _insert_run(scenario_id, result, notes, username)
    except ExclusionViolation as exc:
        raise ValueError(f"Crew double-booked in this schedule: {exc.diag.message_detail}") from exc

def _insert_run(scenario_id, result, notes, username):
    import json
    actions = result["actions"]
    with connect() as conn:
        with conn.cursor() as cur:
            set_app_user(cur, username)
            run = cur.execute(
                "INSERT INTO restoration_runs(scenario_id,strategy_name,total_cost,"
                "makespan_hours,weighted_recovery_score,notes) "
                "VALUES (%s,%s,%s,%s,%s,%s) RETURNING run_id",
                (scenario_id, result["strategy"], result["total_cost"],
                 result["makespan_hours"], result["weighted_recovery_score"],
                 json.dumps(notes or {})),
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

def delete_scenario(scenario_id):
    """Delete a scenario, its runs and its tasks in one transaction.

    Runs are removed first on purpose: scheduled_actions reference repair_tasks without
    ON DELETE CASCADE, so that a saved run can never silently lose a task it was built from.
    """
    with connect() as conn:
        conn.execute("DELETE FROM restoration_runs WHERE scenario_id=%s", (scenario_id,))
        conn.execute("DELETE FROM outage_scenarios WHERE scenario_id=%s", (scenario_id,))
