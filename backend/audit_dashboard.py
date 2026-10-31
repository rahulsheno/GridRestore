"""Audit history queries and dashboard statistics (live aggregate vs materialized view)."""
from datetime import datetime

from .db import connect

AUDITED_TABLES = ("repair_tasks", "outage_scenarios", "restoration_runs")
OPERATIONS = ("INSERT", "UPDATE", "DELETE")


def query_audit(table_name=None, operation=None, row_key=None, app_user=None,
                since=None, until=None, limit=50, offset=0, include_data=False):
    """Filtered, paginated audit history. Every filter is optional and parameterised."""
    if table_name is not None and table_name not in AUDITED_TABLES:
        raise ValueError(f"table must be one of {list(AUDITED_TABLES)}")
    if operation is not None and operation not in OPERATIONS:
        raise ValueError(f"operation must be one of {list(OPERATIONS)}")
    if not 1 <= limit <= 500 or offset < 0:
        raise ValueError("limit must be 1-500 and offset must be 0 or more")

    clauses, params = [], []
    if table_name:
        clauses.append("table_name = %s"); params.append(table_name)
    if operation:
        clauses.append("operation = %s"); params.append(operation)
    if row_key:
        clauses.append("row_key = %s"); params.append(row_key)
    if app_user:
        clauses.append("app_user = %s"); params.append(app_user)
    if since:
        clauses.append("changed_at >= %s"); params.append(since)
    if until:
        clauses.append("changed_at < %s"); params.append(until)
    where = ("WHERE " + " AND ".join(clauses)) if clauses else ""

    data_cols = ", old_data, new_data" if include_data else ""
    sql = (f"SELECT audit_id, table_name, operation, row_key, changed_at, db_user, app_user"
           f"{data_cols}, COUNT(*) OVER() AS total_matching "
           f"FROM audit_log {where} ORDER BY audit_id DESC LIMIT %s OFFSET %s")
    with connect() as conn:
        rows = conn.execute(sql, [*params, limit, offset]).fetchall()
    total = rows[0]["total_matching"] if rows else 0
    items = []
    for row in rows:
        item = {k: v for k, v in row.items() if k != "total_matching"}
        item["changed_at"] = item["changed_at"].isoformat()
        items.append(item)
    return {"total": total, "limit": limit, "offset": offset, "items": items}


def run_stats(mode="materialized"):
    """Per scenario+strategy statistics. mode='live' aggregates base tables; 'materialized' reads the MV."""
    if mode == "live":
        sql = """
            SELECT r.scenario_id, r.strategy_name, COUNT(DISTINCT r.run_id)::INT AS run_count,
                   ROUND(AVG(r.total_cost), 2) AS avg_cost,
                   ROUND(AVG(r.makespan_hours), 2) AS avg_makespan_hours,
                   MAX(r.weighted_recovery_score) AS best_score,
                   COUNT(a.action_id)::INT AS scheduled_actions,
                   MAX(r.started_at) AS last_run_at
            FROM restoration_runs r LEFT JOIN scheduled_actions a ON a.run_id = r.run_id
            GROUP BY r.scenario_id, r.strategy_name ORDER BY r.scenario_id, r.strategy_name"""
    elif mode == "materialized":
        sql = ("SELECT scenario_id, strategy_name, run_count, avg_cost, avg_makespan_hours, "
               "best_score, scheduled_actions, last_run_at FROM mv_scenario_run_stats "
               "ORDER BY scenario_id, strategy_name")
    else:
        raise ValueError("mode must be 'live' or 'materialized'")
    with connect() as conn:
        rows = conn.execute(sql).fetchall()
    return [_jsonable(r) for r in rows]


def refresh_run_stats():
    """Refresh the materialized view without blocking readers (needs the unique index)."""
    started = datetime.now()
    with connect() as conn:
        conn.execute("REFRESH MATERIALIZED VIEW CONCURRENTLY mv_scenario_run_stats")
    return {"refreshed": True, "duration_ms": round((datetime.now() - started).total_seconds() * 1000, 2)}


def stats_freshness():
    """The MV is stale when the number of runs it has counted differs from the base table."""
    with connect() as conn:
        row = conn.execute(
            "SELECT (SELECT COUNT(*) FROM restoration_runs) AS live_runs, "
            "(SELECT COALESCE(SUM(run_count), 0) FROM mv_scenario_run_stats) AS materialized_runs"
        ).fetchone()
    return {"live_runs": row["live_runs"], "materialized_runs": int(row["materialized_runs"]),
            "stale": row["live_runs"] != int(row["materialized_runs"])}


def _jsonable(row):
    out = dict(row)
    for key, value in out.items():
        if hasattr(value, "isoformat"):
            out[key] = value.isoformat()
        elif hasattr(value, "as_tuple"):  # Decimal
            out[key] = float(value)
    return out
