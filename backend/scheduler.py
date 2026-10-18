"""Synthetic resource-constrained scheduling heuristics with prerequisites and crew skills."""
import numpy as np

STRATEGIES = ("priority_first", "shortest_repair_first", "gridrestore_score")

def _topological_order(frame, dependencies):
    ids = set(frame["task_id"])
    prereqs = {task: set(dependencies.get(task, [])) for task in ids}
    for task, deps in prereqs.items():
        missing = deps - ids
        if missing:
            raise ValueError(f"Unknown prerequisite(s) for {task}: {sorted(missing)}")
        if task in deps:
            raise ValueError(f"Task {task} cannot depend on itself")
    ordered = []
    ready = sorted([t for t in ids if not prereqs[t]])
    while ready:
        current = ready.pop(0)
        ordered.append(current)
        for task in sorted(ids - set(ordered)):
            if current in prereqs[task]:
                prereqs[task].remove(current)
                if not prereqs[task] and task not in ready:
                    ready.append(task)
        ready.sort()
    if len(ordered) != len(ids):
        raise ValueError("Dependency cycle detected")
    return ordered

def schedule_repairs(frame, strategy, budget, crews, dependencies=None):
    """crews is a list of {'crew_id': str, 'skill': str}; task required_skill defaults to general."""
    if strategy not in STRATEGIES:
        raise ValueError(f"Unknown strategy: {strategy}")
    if budget <= 0 or not crews:
        raise ValueError("Budget must be positive and at least one crew is required")
    dependencies = dependencies or {}
    topo = _topological_order(frame, dependencies)
    by_id = frame.set_index("task_id").to_dict("index")
    rank = {tid:i for i,tid in enumerate(topo)}
    if strategy == "priority_first":
        ordered = sorted(topo, key=lambda t:(float(by_id[t]["priority"]),-float(by_id[t]["service_weight"]),rank[t]))
    elif strategy == "shortest_repair_first":
        ordered = sorted(topo, key=lambda t:(float(by_id[t]["estimated_hours"]),float(by_id[t]["priority"]),rank[t]))
    else:
        ordered = sorted(topo, key=lambda t:(-(float(by_id[t]["service_weight"])/float(by_id[t]["estimated_hours"])+(6-float(by_id[t]["priority"]))*.15),rank[t]))
    free = {c["crew_id"]:float(c.get("available_from",0)) for c in crews}
    skill = {c["crew_id"]:c["skill"] for c in crews}
    completed, actions, spent, score = set(), [], 0.0, 0.0
    finish_by = {}
    pending = list(ordered)
    # Iterate until no more tasks can be scheduled. A dependency must be scheduled before its child.
    while pending:
        progressed = False
        for tid in list(pending):
            task = by_id[tid]
            prereqs = set(dependencies.get(tid, []))
            if not prereqs.issubset(completed):
                continue
            cost = float(task["estimated_cost"])
            if spent + cost > budget:
                pending.remove(tid)
                progressed = True
                continue
            required = task.get("required_skill", "general")
            eligible = [c["crew_id"] for c in crews if skill[c["crew_id"]] in (required,"multi-skill")]
            if not eligible:
                # Leave explicitly unscheduled instead of assigning an unqualified crew.
                pending.remove(tid)
                progressed = True
                continue
            crew_id = min(eligible, key=lambda c:free[c])
            start = free[crew_id]
            # A task cannot start until its prerequisites have finished.
            prereq_finish = max(
                [finish_by[dep] for dep in prereqs if dep in finish_by],
                default=0.0,
            )
            start = max(start, prereq_finish)
            duration = float(task["estimated_hours"])
            finish = start + duration
            free[crew_id] = finish
            finish_by[tid] = finish
            spent += cost
            score += float(task["service_weight"]) / max(finish,.25)
            actions.append({"task_id":tid,"crew_id":crew_id,"start_hour":round(start,3),
                "finish_hour":round(finish,3),"duration_hours":round(duration,3),
                "estimated_cost":cost,"service_weight":float(task["service_weight"])})
            completed.add(tid)
            pending.remove(tid)
            progressed = True
        if not progressed:
            break
    return {"strategy":strategy,"total_cost":round(spent,2),
        "makespan_hours":round(max(free.values()),3),"weighted_recovery_score":round(score,4),
        "scheduled_count":len(actions),"actions":actions,
        "unscheduled_task_ids":pending}
