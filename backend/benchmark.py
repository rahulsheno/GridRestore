"""Measure the database choices in this project on the benchmark dataset.

Measurements (median of N runs, milliseconds):
  1. Index effect: a scenario's pending tasks, with and without idx_tasks_scenario_status.
  2. Index effect: a run's scheduled actions, with and without idx_actions_run_time.
     Without it the planner looks up the run through UNIQUE(run_id, task_id) and sorts the rows, which
     costs little at this size. The overlap constraint's GiST index is not used for this query.
  3. Dashboard: live aggregate over the base tables vs reading mv_scenario_run_stats.
  4. Refresh cost of the materialized view.
  5. Cost of the crew-overlap exclusion constraint on a bulk insert of one run.

Index and constraint drops run inside a transaction that is rolled back, so the database is unchanged.
Run after `python -m backend.bench_seed`:   python -m backend.benchmark
"""
import json
import statistics
import time
from pathlib import Path

from .db import connect

REPEATS = 30


def _median_ms(fn, repeats=REPEATS):
    samples = []
    for _ in range(repeats):
        started = time.perf_counter()
        fn()
        samples.append((time.perf_counter() - started) * 1000)
    return round(statistics.median(samples), 3)


def _plan_root(conn, sql, params):
    rows = conn.execute("EXPLAIN " + sql, params).fetchall()
    return rows[0]["QUERY PLAN"].strip()


def _scenario_and_run(conn):
    sid = conn.execute("SELECT scenario_id FROM outage_scenarios WHERE scenario_name='Bench S01'").fetchone()
    rid = conn.execute("SELECT run_id FROM restoration_runs WHERE scenario_id=%s ORDER BY run_id LIMIT 1",
                       (sid["scenario_id"],)).fetchone()
    return sid["scenario_id"], rid["run_id"]


def run(out_path="docs/benchmark_results.json"):
    results = {}
    with connect() as conn:
        conn.execute("ANALYZE")
        scenario_id, run_id = _scenario_and_run(conn)
        results["dataset"] = {
            key: conn.execute(f"SELECT COUNT(*) AS n FROM {table}").fetchone()["n"]
            for key, table in [("grid_nodes", "grid_nodes"), ("repair_tasks", "repair_tasks"),
                               ("outage_scenarios", "outage_scenarios"), ("restoration_runs", "restoration_runs"),
                               ("scheduled_actions", "scheduled_actions"), ("audit_log", "audit_log")]
        }
        conn.commit()

    q_tasks = ("SELECT task_id FROM repair_tasks WHERE scenario_id=%s AND status='pending'", (scenario_id,))
    q_actions = ("SELECT task_id, crew_label, start_hour FROM scheduled_actions WHERE run_id=%s "
                 "ORDER BY start_hour", (run_id,))
    q_live = ("SELECT r.scenario_id, r.strategy_name, COUNT(DISTINCT r.run_id), AVG(r.total_cost), "
              "COUNT(a.action_id) FROM restoration_runs r LEFT JOIN scheduled_actions a "
              "ON a.run_id = r.run_id GROUP BY r.scenario_id, r.strategy_name", ())
    q_mv = ("SELECT scenario_id, strategy_name, run_count, avg_cost, scheduled_actions "
            "FROM mv_scenario_run_stats", ())

    def timed(conn, sql_params):
        """Measure on the given connection: DDL inside an open transaction is visible only there."""
        sql, params = sql_params
        return _median_ms(lambda: conn.execute(sql, params).fetchall())

    # 1 and 2: with indexes (the normal state of the database)
    with connect() as conn:
        results["index_scenario_status"] = {"with_index_ms": timed(conn, q_tasks),
                                           "plan_with_index": _plan_root(conn, *q_tasks)}
        results["index_run_time"] = {"with_index_ms": timed(conn, q_actions),
                                    "plan_with_index": _plan_root(conn, *q_actions)}
    # 1 and 2: without the composite indexes, inside a rolled-back transaction
    with connect() as conn:
        conn.execute("DROP INDEX idx_tasks_scenario_status")
        conn.execute("ANALYZE repair_tasks")
        results["index_scenario_status"]["without_index_ms"] = timed(conn, q_tasks)
        results["index_scenario_status"]["plan_without_index"] = _plan_root(conn, *q_tasks)
        conn.rollback()
    with connect() as conn:
        conn.execute("DROP INDEX idx_actions_run_time")
        conn.execute("ANALYZE scheduled_actions")
        results["index_run_time"]["without_index_ms"] = timed(conn, q_actions)
        results["index_run_time"]["plan_without_index"] = _plan_root(conn, *q_actions)
        conn.rollback()
    with connect() as conn:
        conn.execute("ANALYZE")

    # 3: dashboard, live aggregate vs materialized view
    with connect() as conn:
        results["dashboard"] = {"live_ms": timed(conn, q_live), "materialized_ms": timed(conn, q_mv)}

    # 4: refresh cost
    with connect() as conn:
        started = time.perf_counter()
        conn.execute("REFRESH MATERIALIZED VIEW CONCURRENTLY mv_scenario_run_stats")
        conn.commit()
        results["dashboard"]["refresh_once_ms"] = round((time.perf_counter() - started) * 1000, 3)

    # 5: exclusion constraint overhead on a bulk insert of one run's actions (rolled back)
    results["overlap_constraint"] = _constraint_overhead(scenario_id)

    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    Path(out_path).write_text(json.dumps(results, indent=2, default=str))
    _print_summary(results)
    return results


def _constraint_overhead(scenario_id, rows=2000, per_run=500):
    """Insert `rows` non-overlapping actions (spread over runs of `per_run` unique tasks), with and
    without the exclusion constraint. Everything is rolled back afterwards."""
    with connect() as conn:
        task_ids = [r["task_id"] for r in conn.execute(
            "SELECT task_id FROM repair_tasks WHERE scenario_id=%s ORDER BY task_id", (scenario_id,)).fetchall()]
    per_run = min(per_run, len(task_ids))

    def insert_all(conn):
        total_ms = 0.0
        for chunk_start in range(0, rows, per_run):
            run_id = conn.execute(
                "INSERT INTO restoration_runs(scenario_id,strategy_name,total_cost,makespan_hours,"
                "weighted_recovery_score) VALUES (%s,'bench',0,0,0) RETURNING run_id",
                (scenario_id,)).fetchone()["run_id"]
            data, cursor = [], {}
            for i in range(min(per_run, rows - chunk_start)):
                crew = f"C{i % 10}"  # 10 crews, back-to-back windows: no overlap, every insert succeeds
                start = cursor.get(crew, 0.0)
                cursor[crew] = start + 0.5
                data.append((run_id, task_ids[i], crew, start, start + 0.5))
            started = time.perf_counter()
            with conn.cursor() as cur:
                cur.executemany("INSERT INTO scheduled_actions(run_id,task_id,crew_label,start_hour,finish_hour) "
                                "VALUES (%s,%s,%s,%s,%s)", data)
            total_ms += (time.perf_counter() - started) * 1000
        return round(total_ms, 3)

    with connect() as conn:
        with_constraint = insert_all(conn)
        conn.rollback()
    with connect() as conn:
        conn.execute("ALTER TABLE scheduled_actions DROP CONSTRAINT excl_crew_overlap")
        without_constraint = insert_all(conn)
        conn.rollback()
    return {"rows": rows, "with_constraint_ms": with_constraint, "without_constraint_ms": without_constraint}


def _print_summary(r):
    print("Dataset:", r["dataset"])
    idx = r["index_scenario_status"]
    print(f"Index idx_tasks_scenario_status: {idx['with_index_ms']} ms with, {idx['without_index_ms']} ms without")
    print(f"  plan with:    {idx['plan_with_index']}")
    print(f"  plan without: {idx['plan_without_index']}")
    idx = r["index_run_time"]
    print(f"Index idx_actions_run_time:      {idx['with_index_ms']} ms with, {idx['without_index_ms']} ms without")
    print(f"  plan with:    {idx['plan_with_index']}")
    print(f"  plan without: {idx['plan_without_index']}")
    d = r["dashboard"]
    print(f"Dashboard: live {d['live_ms']} ms, materialized {d['materialized_ms']} ms, "
          f"refresh {d['refresh_once_ms']} ms")
    c = r["overlap_constraint"]
    print(f"Exclusion constraint on {c['rows']} inserts: {c['with_constraint_ms']} ms with, "
          f"{c['without_constraint_ms']} ms without")


if __name__ == "__main__":
    run()
