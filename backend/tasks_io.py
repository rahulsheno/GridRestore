"""CSV import and export of repair tasks.

validate_task_csv() is pure Python: it checks the header, every row and the dependency graph,
and returns ALL row-level errors at once, so an admin can fix a file in one pass. Nothing is
written unless the whole file is valid (the API calls this first, then inserts in one transaction).
"""
import csv
import io
import re

import pandas as pd

from .scheduler import _topological_order

COLUMNS = ["task_id", "edge_id", "component_name", "estimated_hours", "estimated_cost",
           "service_weight", "priority", "region_code", "required_skill", "outage_cause",
           "depends_on"]
REQUIRED = ["task_id", "edge_id", "component_name", "estimated_hours", "estimated_cost",
            "service_weight", "priority"]
SKILLS = {"general", "electrical", "multi-skill"}
CAUSES = {"storm", "equipment_age", "vehicle_impact", "vegetation", "unknown"}
ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]{1,40}$")
MAX_HOURS = 500.0


def _err(row, column, message):
    return {"row": row, "column": column, "message": message}


def _number(text, low, high, row, column, errors, integer=False):
    try:
        value = int(text) if integer else float(text)
    except ValueError:
        errors.append(_err(row, column, f"'{text}' is not a {'whole number' if integer else 'number'}"))
        return None
    if value != value:  # NaN
        errors.append(_err(row, column, "NaN is not allowed"))
        return None
    if value < low or value > high:
        errors.append(_err(row, column, f"must be between {low} and {high}"))
        return None
    return value


def validate_task_csv(text, known_edges, global_task_ids, scenario_task_ids):
    """Return {"valid": bool, "rows": [normalised rows], "errors": [row errors]}.

    known_edges:       edge_ids that exist in grid_edges
    global_task_ids:   every task_id in the database (task_id is a global primary key)
    scenario_task_ids: task_ids already in the target scenario (valid prerequisites)
    """
    errors = []
    try:
        reader = csv.DictReader(io.StringIO(text.strip()))
        header = reader.fieldnames or []
        records = list(reader)
    except csv.Error as exc:
        return {"valid": False, "rows": [], "errors": [_err(1, "header", f"unreadable CSV: {exc}")]}

    missing = [c for c in REQUIRED if c not in header]
    if missing:
        errors.append(_err(1, "header", f"missing required column(s): {', '.join(missing)}"))
    unknown = [c for c in header if c not in COLUMNS]
    if unknown:
        errors.append(_err(1, "header", f"unknown column(s): {', '.join(unknown)}"))
    if len(set(header)) != len(header):
        errors.append(_err(1, "header", "duplicate column names"))
    if missing:
        return {"valid": False, "rows": [], "errors": errors}

    # Pass 1: every task_id in the file, so a prerequisite may appear anywhere in the file.
    file_ids = {(r.get("task_id") or "").strip() for r in records}
    file_ids.discard("")

    rows, seen_ids = [], set()
    for line_no, record in enumerate(records, start=2):  # line 1 is the header
        if None in record:
            errors.append(_err(line_no, "row", "too many values for this row"))
            continue
        if any(v is None for v in record.values()):
            errors.append(_err(line_no, "row", "too few values for this row"))
            continue
        clean = {k: (v or "").strip() for k, v in record.items()}
        errors_before = len(errors)

        task_id = clean["task_id"]
        if not ID_PATTERN.match(task_id):
            errors.append(_err(line_no, "task_id", "use 1-40 letters, digits, '-' or '_'"))
        elif task_id in seen_ids:
            errors.append(_err(line_no, "task_id", f"'{task_id}' appears twice in this file"))
        elif task_id in global_task_ids:
            errors.append(_err(line_no, "task_id", f"'{task_id}' already exists in the database"))
        seen_ids.add(task_id)

        edge_id = clean["edge_id"]
        if edge_id not in known_edges:
            errors.append(_err(line_no, "edge_id", f"unknown edge '{edge_id}'"))

        if not clean["component_name"]:
            errors.append(_err(line_no, "component_name", "cannot be empty"))
        elif len(clean["component_name"]) > 120:
            errors.append(_err(line_no, "component_name", "longer than 120 characters"))

        hours = _number(clean["estimated_hours"], 0.01, MAX_HOURS, line_no, "estimated_hours", errors)
        cost = _number(clean["estimated_cost"], 0, 10_000_000, line_no, "estimated_cost", errors)
        weight = _number(clean["service_weight"], 0, 1000, line_no, "service_weight", errors)
        priority = _number(clean["priority"], 1, 5, line_no, "priority", errors, integer=True)

        region = clean.get("region_code") or "Unassigned"
        if len(region) > 30:
            errors.append(_err(line_no, "region_code", "longer than 30 characters"))

        skill = clean.get("required_skill") or "general"
        if skill not in SKILLS:
            errors.append(_err(line_no, "required_skill", f"must be one of {sorted(SKILLS)}"))

        cause = clean.get("outage_cause") or "unknown"
        if cause not in CAUSES:
            errors.append(_err(line_no, "outage_cause", f"must be one of {sorted(CAUSES)}"))

        depends = [d.strip() for d in clean.get("depends_on", "").split(";") if d.strip()]
        for prereq in depends:
            if prereq == task_id:
                errors.append(_err(line_no, "depends_on", "a task cannot depend on itself"))
            elif prereq not in scenario_task_ids and prereq not in file_ids:
                errors.append(_err(line_no, "depends_on",
                                   f"prerequisite '{prereq}' is not in this scenario or this file"))

        if len(errors) == errors_before:
            rows.append({"task_id": task_id, "edge_id": edge_id, "component_name": clean["component_name"],
                         "estimated_hours": hours, "estimated_cost": cost, "service_weight": weight,
                         "priority": priority, "region_code": region, "required_skill": skill,
                         "outage_cause": cause, "depends_on": depends})

    if not errors:
        errors.extend(_cycle_errors(rows, scenario_task_ids))
    return {"valid": not errors, "rows": rows if not errors else [], "errors": errors}


def _cycle_errors(rows, scenario_task_ids):
    """Check that the new tasks do not create a dependency cycle, using the scheduler's own check."""
    ids = set(scenario_task_ids) | {r["task_id"] for r in rows}
    deps = {r["task_id"]: r["depends_on"] for r in rows if r["depends_on"]}
    try:
        _topological_order(pd.DataFrame({"task_id": sorted(ids)}), deps)
        return []
    except ValueError as exc:
        return [_err(0, "depends_on", str(exc))]


def export_task_csv(task_rows, dependencies):
    """task_rows: dicts with the repair_tasks columns; dependencies: {task_id: [prereq ids]}."""
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=COLUMNS, lineterminator="\n")
    writer.writeheader()
    for row in task_rows:
        writer.writerow({
            "task_id": row["task_id"], "edge_id": row["edge_id"],
            "component_name": row["component_name"],
            "estimated_hours": float(row["estimated_hours"]),
            "estimated_cost": float(row["estimated_cost"]),
            "service_weight": float(row["service_weight"]),
            "priority": int(row["priority"]),
            "region_code": row.get("region_code") or "Unassigned",
            "required_skill": row.get("required_skill") or "general",
            "outage_cause": row.get("outage_cause") or "unknown",
            "depends_on": ";".join(sorted(dependencies.get(row["task_id"], []))),
        })
    return buffer.getvalue()


def load_reference_ids(scenario_id):
    """(known edge ids, every task id in the database, task ids in this scenario)."""
    from .db import connect
    with connect() as conn:
        edges = {r["edge_id"] for r in conn.execute("SELECT edge_id FROM grid_edges").fetchall()}
        global_ids = {r["task_id"] for r in conn.execute("SELECT task_id FROM repair_tasks").fetchall()}
        scenario_ids = {r["task_id"] for r in conn.execute(
            "SELECT task_id FROM repair_tasks WHERE scenario_id=%s", (scenario_id,)).fetchall()}
    return edges, global_ids, scenario_ids


def load_task_rows(scenario_id):
    """Task rows plus dependency map for export and reports."""
    from .db import connect
    with connect() as conn:
        rows = conn.execute(
            "SELECT task_id, edge_id, component_name, estimated_hours, estimated_cost, service_weight, "
            "priority, region_code, required_skill, outage_cause FROM repair_tasks "
            "WHERE scenario_id=%s ORDER BY task_id", (scenario_id,)).fetchall()
        deps = conn.execute(
            "SELECT d.task_id, d.prerequisite_task_id FROM task_dependencies d "
            "JOIN repair_tasks t ON t.task_id=d.task_id WHERE t.scenario_id=%s", (scenario_id,)).fetchall()
    dependencies = {}
    for d in deps:
        dependencies.setdefault(d["task_id"], []).append(d["prerequisite_task_id"])
    return [dict(r) for r in rows], dependencies
