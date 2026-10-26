"""Scenario versioning.

Every change to a scenario's repair tasks (edit, CSV import, rollback) runs in ONE transaction:

  1. lock the scenario row (SELECT ... FOR UPDATE) so two editors cannot interleave versions,
  2. if the scenario has no versions yet, store the pre-change state as version 1 (baseline),
  3. apply the change, reject it if the dependency graph now has a cycle,
  4. store a full snapshot of the result as the next version number.

Rollback never deletes history: it writes the old state back and records it as a new version.
Snapshots are plain JSON so they can be diffed in Python and survive schema changes.
"""
import json
from datetime import datetime

import psycopg
from .db import connect, set_app_user
from .scheduler import _topological_order
import pandas as pd

EDITABLE_FIELDS = {
    "component_name": str,
    "estimated_hours": float,
    "estimated_cost": float,
    "service_weight": float,
    "priority": int,
    "region_code": str,
    "required_skill": str,
    "outage_cause": str,
}
TASK_COLUMNS = ["task_id", "edge_id", *EDITABLE_FIELDS]


def _lock_scenario(cur, scenario_id):
    row = cur.execute(
        "SELECT scenario_id, scenario_name, budget, crew_count FROM outage_scenarios "
        "WHERE scenario_id=%s FOR UPDATE",
        (scenario_id,),
    ).fetchone()
    if row is None:
        raise LookupError(f"Scenario {scenario_id} not found")
    return row


def _snapshot(cur, scenario_id):
    scenario = cur.execute(
        "SELECT scenario_name, budget, crew_count FROM outage_scenarios WHERE scenario_id=%s",
        (scenario_id,),
    ).fetchone()
    tasks = cur.execute(
        f"SELECT {', '.join(TASK_COLUMNS)} FROM repair_tasks WHERE scenario_id=%s ORDER BY task_id",
        (scenario_id,),
    ).fetchall()
    deps = cur.execute(
        "SELECT d.task_id, d.prerequisite_task_id FROM task_dependencies d "
        "JOIN repair_tasks t ON t.task_id=d.task_id WHERE t.scenario_id=%s "
        "ORDER BY d.task_id, d.prerequisite_task_id",
        (scenario_id,),
    ).fetchall()
    return {
        "scenario": {"scenario_name": scenario["scenario_name"],
                     "budget": float(scenario["budget"]), "crew_count": int(scenario["crew_count"])},
        "tasks": [_plain_task(t) for t in tasks],
        "dependencies": [[d["task_id"], d["prerequisite_task_id"]] for d in deps],
    }


def _plain_task(row):
    """Convert DB types (Decimal, etc.) into JSON-safe values."""
    out = {"task_id": row["task_id"], "edge_id": row["edge_id"]}
    for field, kind in EDITABLE_FIELDS.items():
        value = row[field]
        out[field] = kind(value) if value is not None else None
    return out


def _next_version_no(cur, scenario_id):
    row = cur.execute(
        "SELECT COALESCE(MAX(version_no), 0) + 1 AS n FROM scenario_versions WHERE scenario_id=%s",
        (scenario_id,),
    ).fetchone()
    return row["n"]


def _store_version(cur, scenario_id, username, note, snapshot):
    number = _next_version_no(cur, scenario_id)
    cur.execute(
        "INSERT INTO scenario_versions(scenario_id,version_no,created_by,note,snapshot) "
        "VALUES (%s,%s,%s,%s,%s)",
        (scenario_id, number, username or "unknown", note or "", json.dumps(snapshot)),
    )
    return number


def _ensure_baseline(cur, scenario_id, username):
    exists = cur.execute(
        "SELECT 1 FROM scenario_versions WHERE scenario_id=%s LIMIT 1", (scenario_id,)
    ).fetchone()
    if exists is None:
        _store_version(cur, scenario_id, username, "baseline (state before first edit)",
                       _snapshot(cur, scenario_id))


def _check_acyclic(cur, scenario_id):
    """Reject any change that leaves the scenario's dependency graph with a cycle."""
    ids = [r["task_id"] for r in cur.execute(
        "SELECT task_id FROM repair_tasks WHERE scenario_id=%s", (scenario_id,)).fetchall()]
    deps = {}
    for row in cur.execute(
        "SELECT d.task_id, d.prerequisite_task_id FROM task_dependencies d "
        "JOIN repair_tasks t ON t.task_id=d.task_id WHERE t.scenario_id=%s", (scenario_id,)).fetchall():
        deps.setdefault(row["task_id"], []).append(row["prerequisite_task_id"])
    _topological_order(pd.DataFrame({"task_id": ids}), deps)


def _replace_dependencies(cur, scenario_id, task_id, prerequisites):
    """Rewrite one task's prerequisites. Prerequisites must belong to the same scenario."""
    for prereq in prerequisites:
        found = cur.execute("SELECT 1 FROM repair_tasks WHERE task_id=%s AND scenario_id=%s",
                            (prereq, scenario_id)).fetchone()
        if found is None:
            raise ValueError(f"Prerequisite {prereq} is not part of scenario {scenario_id}")
    cur.execute("DELETE FROM task_dependencies WHERE task_id=%s", (task_id,))
    for prereq in prerequisites:
        cur.execute("INSERT INTO task_dependencies(task_id,prerequisite_task_id) VALUES (%s,%s)",
                    (task_id, prereq))


def _translate_db_error(exc):
    """Turn constraint violations into user-facing ValueErrors (the transaction is rolled back)."""
    if isinstance(exc, psycopg.errors.CheckViolation):
        return ValueError(f"Value rejected by database rule {exc.diag.constraint_name}")
    if isinstance(exc, psycopg.errors.UniqueViolation):
        return ValueError("task_id already exists")
    if isinstance(exc, psycopg.errors.ForeignKeyViolation):
        return ValueError("Referenced row does not exist, or the task is used by a saved run")
    return ValueError(str(exc))


def _validate_update(update):
    fields = {k: v for k, v in update.items() if k not in ("task_id", "depends_on")}
    unknown = set(fields) - set(EDITABLE_FIELDS)
    if unknown:
        raise ValueError(f"Fields cannot be edited: {sorted(unknown)}")
    if not fields and "depends_on" not in update:
        raise ValueError(f"No changes given for task {update.get('task_id')}")
    return fields


def apply_changes(scenario_id, username, note="", updates=(), inserts=()):
    """Apply task updates and inserts in one transaction and store a new version.

    updates: [{"task_id": ..., <editable fields>, "depends_on": [..] (optional)}]
    inserts: [{"task_id", "edge_id", <editable fields>, "depends_on": [..]}]
    Returns the new version number.
    """
    if not updates and not inserts:
        raise ValueError("Nothing to change")
    try:
        with connect() as conn:
            with conn.cursor() as cur:
                set_app_user(cur, username)
                _lock_scenario(cur, scenario_id)
                _ensure_baseline(cur, scenario_id, username)
                for update in updates:
                    fields = _validate_update(update)
                    task_id = update["task_id"]
                    if fields:
                        assignments = ", ".join(f"{name}=%s" for name in fields)
                        result = cur.execute(
                            f"UPDATE repair_tasks SET {assignments} WHERE task_id=%s AND scenario_id=%s",
                            [*fields.values(), task_id, scenario_id],
                        )
                        if result.rowcount != 1:
                            raise ValueError(f"Task {task_id} is not part of scenario {scenario_id}")
                    if "depends_on" in update:
                        _replace_dependencies(cur, scenario_id, task_id, update["depends_on"] or [])
                # Insert every task first, then the prerequisite rows, so a CSV can reference
                # a task that appears later in the same file.
                for row in inserts:
                    _insert_task(cur, scenario_id, row)
                for row in inserts:
                    for prereq in row.get("depends_on") or []:
                        cur.execute("INSERT INTO task_dependencies(task_id,prerequisite_task_id) "
                                    "VALUES (%s,%s)", (row["task_id"], prereq))
                _check_acyclic(cur, scenario_id)
                return _store_version(cur, scenario_id, username, note, _snapshot(cur, scenario_id))
    except psycopg.Error as exc:
        raise _translate_db_error(exc) from exc


def _insert_task(cur, scenario_id, row):
    columns = ["task_id", "scenario_id", "edge_id", *EDITABLE_FIELDS]
    values = [row["task_id"], scenario_id, row["edge_id"], *[row[f] for f in EDITABLE_FIELDS]]
    cur.execute(
        f"INSERT INTO repair_tasks({', '.join(columns)}) VALUES ({', '.join(['%s'] * len(columns))})",
        values,
    )


def list_versions(scenario_id):
    with connect() as conn:
        rows = conn.execute(
            "SELECT version_no, created_at, created_by, note, "
            "jsonb_array_length(snapshot->'tasks') AS task_count "
            "FROM scenario_versions WHERE scenario_id=%s ORDER BY version_no DESC",
            (scenario_id,),
        ).fetchall()
    return [dict(r, created_at=r["created_at"].isoformat()) for r in rows]


def get_version(scenario_id, version_no):
    with connect() as conn:
        row = conn.execute(
            "SELECT snapshot FROM scenario_versions WHERE scenario_id=%s AND version_no=%s",
            (scenario_id, version_no),
        ).fetchone()
    if row is None:
        raise LookupError(f"Version {version_no} of scenario {scenario_id} not found")
    return row["snapshot"]


def diff_snapshots(old, new):
    """Pure comparison of two snapshots: field-level task changes plus added/removed tasks and deps."""
    old_tasks = {t["task_id"]: t for t in old["tasks"]}
    new_tasks = {t["task_id"]: t for t in new["tasks"]}
    changed = []
    for task_id in sorted(old_tasks.keys() & new_tasks.keys()):
        for field in ["edge_id", *EDITABLE_FIELDS]:
            before, after = old_tasks[task_id].get(field), new_tasks[task_id].get(field)
            if before != after:
                changed.append({"task_id": task_id, "field": field, "from": before, "to": after})
    old_deps = {tuple(d) for d in old["dependencies"]}
    new_deps = {tuple(d) for d in new["dependencies"]}
    return {
        "tasks_added": sorted(new_tasks.keys() - old_tasks.keys()),
        "tasks_removed": sorted(old_tasks.keys() - new_tasks.keys()),
        "fields_changed": changed,
        "dependencies_added": [list(d) for d in sorted(new_deps - old_deps)],
        "dependencies_removed": [list(d) for d in sorted(old_deps - new_deps)],
        "scenario_changed": old["scenario"] != new["scenario"],
    }


def rollback(scenario_id, version_no, username, note=""):
    """Restore a stored version. History is kept: the restore is recorded as a new version."""
    target = get_version(scenario_id, version_no)
    try:
        with connect() as conn:
            with conn.cursor() as cur:
                set_app_user(cur, username)
                _lock_scenario(cur, scenario_id)
                _ensure_baseline(cur, scenario_id, username)
                current = _snapshot(cur, scenario_id)
                wanted_ids = {t["task_id"] for t in target["tasks"]}
                # 1. Drop dependency rows for this scenario, then rewrite them from the target.
                cur.execute(
                    "DELETE FROM task_dependencies WHERE task_id IN "
                    "(SELECT task_id FROM repair_tasks WHERE scenario_id=%s)", (scenario_id,))
                # 2. Remove tasks added after the target version.
                for task in current["tasks"]:
                    if task["task_id"] not in wanted_ids:
                        cur.execute("DELETE FROM repair_tasks WHERE task_id=%s AND scenario_id=%s",
                                    (task["task_id"], scenario_id))
                # 3. Restore or re-insert every task in the target snapshot.
                existing = {t["task_id"] for t in current["tasks"]}
                for task in target["tasks"]:
                    if task["task_id"] in existing:
                        assignments = ", ".join(f"{f}=%s" for f in EDITABLE_FIELDS)
                        cur.execute(
                            f"UPDATE repair_tasks SET {assignments}, edge_id=%s "
                            "WHERE task_id=%s AND scenario_id=%s",
                            [*[task[f] for f in EDITABLE_FIELDS], task["edge_id"],
                             task["task_id"], scenario_id])
                    else:
                        _insert_task(cur, scenario_id, task)
                # 4. Restore dependencies (all tasks exist at this point).
                for child, prereq in target["dependencies"]:
                    cur.execute("INSERT INTO task_dependencies(task_id,prerequisite_task_id) "
                                "VALUES (%s,%s)", (child, prereq))
                _check_acyclic(cur, scenario_id)
                number = _store_version(cur, scenario_id, username,
                                        note or f"rollback to version {version_no}",
                                        _snapshot(cur, scenario_id))
                return number
    except psycopg.Error as exc:
        raise _translate_db_error(exc) from exc
