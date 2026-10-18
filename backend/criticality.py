"""Restorer-side criticality: unblock ranking + critical-path (CPM) analysis.

No attack graphs, no power-flow solver, no external grid cases. Everything
derives from the project's own repair_tasks + task_dependencies tables:
- unblock ranking: how many downstream tasks (transitively) each repair frees,
  via a recursive CTE, plus the service weight it unblocks.
- critical path: longest dependency chain by estimated_hours (classic CPM
  forward/backward pass); zero-slack tasks set the minimum makespan floor.
"""
from .db import connect

def critical_repairs(scenario_id: int):
    """Rank repairs by downstream unblock count (recursive CTE)."""
    sql = """
    WITH RECURSIVE downstream(root_id, task_id) AS (
      SELECT prerequisite_task_id, task_id FROM task_dependencies
      UNION
      SELECT d.root_id, t.task_id FROM task_dependencies t
      JOIN downstream d ON d.task_id = t.prerequisite_task_id
    )
    SELECT t.task_id, t.component_name, t.service_weight, t.priority,
           COUNT(DISTINCT d.task_id)::INT AS unblocks_count,
           COALESCE(SUM(dt.service_weight), 0)::FLOAT AS unblocked_service_weight
    FROM repair_tasks t
    LEFT JOIN downstream d ON d.root_id = t.task_id
    LEFT JOIN repair_tasks dt ON dt.task_id = d.task_id
    WHERE t.scenario_id = %s
    GROUP BY t.task_id, t.component_name, t.service_weight, t.priority
    ORDER BY unblocks_count DESC, unblocked_service_weight DESC, t.task_id
    """
    with connect() as conn:
        return [dict(r) for r in conn.execute(sql, (scenario_id,)).fetchall()]

def critical_path(scenario_id: int):
    """CPM forward/backward pass over the scenario's dependency DAG."""
    with connect() as conn:
        tasks = conn.execute(
            "SELECT task_id, estimated_hours FROM repair_tasks WHERE scenario_id=%s",
            (scenario_id,)).fetchall()
        deps = conn.execute(
            "SELECT d.task_id, d.prerequisite_task_id FROM task_dependencies d "
            "JOIN repair_tasks t ON t.task_id = d.task_id WHERE t.scenario_id=%s",
            (scenario_id,)).fetchall()
    if not tasks:
        raise ValueError("No repair_tasks for this scenario")
    duration = {r["task_id"]: float(r["estimated_hours"]) for r in tasks}
    prereqs = {t: [] for t in duration}
    children = {t: [] for t in duration}
    for row in deps:
        prereqs[row["task_id"]].append(row["prerequisite_task_id"])
        children[row["prerequisite_task_id"]].append(row["task_id"])
    # Forward pass in topological order (Kahn).
    from collections import deque
    indegree = {t: len(p) for t, p in prereqs.items()}
    queue = deque(sorted(t for t, d in indegree.items() if d == 0))
    topo = []
    earliest_start, earliest_finish = {}, {}
    while queue:
        current = queue.popleft()
        topo.append(current)
        earliest_start[current] = max([earliest_finish[p] for p in prereqs[current]], default=0.0)
        earliest_finish[current] = earliest_start[current] + duration[current]
        for child in sorted(children[current]):
            indegree[child] -= 1
            if indegree[child] == 0:
                queue.append(child)
    if len(topo) != len(duration):
        raise ValueError("Dependency cycle detected")
    makespan_floor = max(earliest_finish.values())
    # Backward pass.
    latest_finish = {t: makespan_floor for t in duration}
    latest_start = {}
    for task in reversed(topo):
        if children[task]:
            latest_finish[task] = min(latest_start[c] for c in children[task])
        latest_start[task] = latest_finish[task] - duration[task]
    rows = []
    for task in topo:
        slack = round(latest_start[task] - earliest_start[task], 3)
        rows.append({"task_id": task,
                     "duration_hours": duration[task],
                     "earliest_start": round(earliest_start[task], 3),
                     "earliest_finish": round(earliest_finish[task], 3),
                     "latest_start": round(latest_start[task], 3),
                     "latest_finish": round(latest_finish[task], 3),
                     "slack": slack,
                     "critical": slack == 0})
    chain = [r["task_id"] for r in rows if r["critical"]]
    return {"makespan_floor_hours": round(makespan_floor, 3),
            "critical_chain": chain, "tasks": rows}


def skill_gaps(scenario_id: int, crews: list = None):
    """Skill-coverage heatmap inputs: required vs available skills per scenario.

    crews defaults to the seeded C1 (multi-skill) + C2/C3 (general).
    Returns per-skill demand (task count, hours, weight) plus whether any
    crew on the roster can cover it. Electrical demand with no electrical or
    multi-skill crew is the headline gap.
    """
    default_crews = [{"crew_id": "C1", "skill": "multi-skill"},
                     {"crew_id": "C2", "skill": "general"},
                     {"crew_id": "C3", "skill": "general"}]
    crews = crews if crews is not None else default_crews
    roster = {c["skill"] for c in crews}

    def covers(required: str) -> bool:
        return any(s in ("multi-skill", required) for s in roster)

    sql = """SELECT required_skill,
             COUNT(*)::INT AS task_count,
             COALESCE(SUM(estimated_hours),0)::FLOAT AS total_hours,
             COALESCE(SUM(service_weight),0)::FLOAT AS total_weight
             FROM repair_tasks WHERE scenario_id=%s GROUP BY required_skill ORDER BY 1"""
    with connect() as conn:
        rows = [dict(r) for r in conn.execute(sql, (scenario_id,)).fetchall()]
    for row in rows:
        row["covered"] = covers(row["required_skill"])
        row["crews_available"] = sorted(
            c["crew_id"] for c in crews
            if c["skill"] in ("multi-skill", row["required_skill"]))
    gaps = [r["required_skill"] for r in rows if not r["covered"]]
    return {"scenario_id": scenario_id,
            "roster": [{"crew_id": c["crew_id"], "skill": c["skill"]} for c in crews],
            "demand": rows, "gaps": gaps,
            "verdict": ("OK - all required skills covered" if not gaps
                        else f"GAP - no crew covers: {', '.join(gaps)}")}
