"""'What changed' report: compare two saved runs of the same scenario.

Each task present in both runs is classified:
  unchanged            same crew, start and finish
  upstream_delay       a prerequisite finishes later in run B, which pushes this task back
  crew_contention      the task waited for a crew in run B after its prerequisites were done
  dispatch_reordered   it moved, but neither of the above explains it (scheduling order changed)
  finished_earlier     it finishes sooner in run B
Tasks only in one run are reported as dropped (in A only) or added (in B only).
"""
EPS = 1e-9


def _index(actions):
    return {a["task_id"]: {"crew": a["crew_label"], "start": float(a["start_hour"]),
                           "finish": float(a["finish_hour"])} for a in actions}


def diff_runs(actions_a, actions_b, dependencies):
    """actions_*: rows with task_id, crew_label, start_hour, finish_hour.
    dependencies: {task_id: [prerequisite task_ids]} for the scenario."""
    a, b = _index(actions_a), _index(actions_b)
    tasks = []
    for task_id in sorted(a.keys() & b.keys()):
        ra, rb = a[task_id], b[task_id]
        delta = rb["finish"] - ra["finish"]
        moved = abs(rb["start"] - ra["start"]) > EPS or rb["crew"] != ra["crew"]
        if not moved and abs(delta) <= EPS:
            continue
        reason = _reason(task_id, ra, rb, a, b, dependencies, delta)
        tasks.append({"task_id": task_id, "crew_a": ra["crew"], "crew_b": rb["crew"],
                      "start_a": ra["start"], "start_b": rb["start"],
                      "finish_a": ra["finish"], "finish_b": rb["finish"],
                      "finish_delta_hours": round(delta, 3), "reason": reason})
    dropped = sorted(a.keys() - b.keys())
    added = sorted(b.keys() - a.keys())
    summary = {
        "changed_tasks": len(tasks),
        "finished_later": sum(1 for t in tasks if t["finish_delta_hours"] > EPS),
        "finished_earlier": sum(1 for t in tasks if t["finish_delta_hours"] < -EPS),
        "dropped_in_b": dropped,
        "added_in_b": added,
        "makespan_a": max((r["finish"] for r in a.values()), default=0.0),
        "makespan_b": max((r["finish"] for r in b.values()), default=0.0),
    }
    summary["makespan_delta_hours"] = round(summary["makespan_b"] - summary["makespan_a"], 3)
    return {"summary": summary, "tasks": tasks}


def _reason(task_id, ra, rb, a, b, dependencies, delta):
    if delta < -EPS:
        return "finished_earlier"
    prereqs = dependencies.get(task_id, [])
    # Did an upstream task finish later in B than in A?
    for prereq in prereqs:
        if prereq not in b:
            return "upstream_delay"
        if prereq in a and b[prereq]["finish"] > a[prereq]["finish"] + EPS:
            return "upstream_delay"
    # Did it wait for a crew after its prerequisites were done?
    ready_b = max((b[p]["finish"] for p in prereqs if p in b), default=0.0)
    if rb["start"] > ready_b + EPS:
        return "crew_contention"
    return "dispatch_reordered"
