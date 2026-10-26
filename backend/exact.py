"""Exact baseline for small instances, solved as a mixed-integer program with PuLP (CBC).

Objective, identical for the solver and for every heuristic:
    maximise   sum of service_weight over tasks that FINISH BY the horizon H
    subject to total estimated_cost <= budget,
               each scheduled task runs on exactly one crew with a matching skill,
               a crew runs one task at a time,
               a task starts only after all its prerequisites have finished,
               a prerequisite of a scheduled task is itself scheduled.

Heuristics schedule every task they can afford; the value they earn is counted the same way
(weight of tasks finishing by H), so the optimality gap = (OPT - heuristic) / OPT is fair.
This is an evaluation tool for small n (roughly <= 12 tasks); it does not scale.
"""
import pulp

from .scheduler import STRATEGIES, schedule_repairs

TOL = 1e-6
# The heuristic rounds start and finish to 3 decimals independently, so a rounded duration can be
# off by up to 0.001 h. The checker allows 2e-3 h for that; the solver itself is exact.
ROUNDING_TOL = 2e-3


def _eligible(task, crews):
    return [c["crew_id"] for c in crews if c["skill"] in (task["required_skill"], "multi-skill")]


def solve_exact(tasks, dependencies, budget, crews, horizon, time_limit=120):
    """tasks: [{task_id, estimated_hours, estimated_cost, service_weight, required_skill}]
    dependencies: {task_id: [prerequisite ids]}; crews: [{crew_id, skill}] available from hour 0."""
    by_id = {t["task_id"]: t for t in tasks}
    ids = list(by_id)
    dur = {i: float(by_id[i]["estimated_hours"]) for i in ids}
    cost = {i: float(by_id[i]["estimated_cost"]) for i in ids}
    weight = {i: float(by_id[i]["service_weight"]) for i in ids}
    crew_ids = [c["crew_id"] for c in crews]
    elig = {i: _eligible(by_id[i], crews) for i in ids}
    big_m = horizon + sum(dur.values()) + 1.0

    prob = pulp.LpProblem("restoration_exact", pulp.LpMaximize)
    x = {i: pulp.LpVariable(f"x_{i}", cat="Binary") for i in ids}
    s = {i: pulp.LpVariable(f"s_{i}", lowBound=0, upBound=horizon) for i in ids}
    y = {(i, k): pulp.LpVariable(f"y_{i}_{k}", cat="Binary") for i in ids for k in elig[i]}

    prob += pulp.lpSum(weight[i] * x[i] for i in ids)
    prob += pulp.lpSum(cost[i] * x[i] for i in ids) <= budget, "budget"

    for i in ids:
        if not elig[i]:
            prob += x[i] == 0, f"no_crew_{i}"
            continue
        # Exactly one eligible crew when scheduled, none otherwise.
        prob += pulp.lpSum(y[i, k] for k in elig[i]) == x[i], f"one_crew_{i}"
        # A scheduled task must finish by the horizon.
        prob += s[i] + dur[i] <= horizon + big_m * (1 - x[i]), f"horizon_{i}"

    for child, prereqs in dependencies.items():
        if child not in by_id:
            continue
        for pre in prereqs:
            if pre not in by_id:
                continue
            prob += x[child] <= x[pre], f"prereq_sel_{child}_{pre}"
            prob += (s[child] >= s[pre] + dur[pre] - big_m * (2 - x[child] - x[pre]),
                     f"prereq_time_{child}_{pre}")

    # Crew non-overlap: for each pair and each shared crew, one task finishes before the other starts.
    for a_idx, i in enumerate(ids):
        for j in ids[a_idx + 1:]:
            shared = [k for k in elig[i] if k in elig[j]]
            if not shared:
                continue
            z = pulp.LpVariable(f"z_{i}_{j}", cat="Binary")  # 1 means i runs before j
            for k in shared:
                both = 2 - y[i, k] - y[j, k]
                prob += s[j] >= s[i] + dur[i] - big_m * (1 - z) - big_m * both, f"ord1_{i}_{j}_{k}"
                prob += s[i] >= s[j] + dur[j] - big_m * z - big_m * both, f"ord2_{i}_{j}_{k}"

    status = prob.solve(pulp.PULP_CBC_CMD(msg=False, timeLimit=time_limit))
    if pulp.LpStatus[status] != "Optimal":
        raise RuntimeError(f"Solver did not prove optimality: {pulp.LpStatus[status]}")

    actions = []
    for i in ids:
        if x[i].value() is not None and x[i].value() > 0.5:
            crew = next(k for k in elig[i] if y[i, k].value() > 0.5)
            start = float(s[i].value())
            actions.append({"task_id": i, "crew_id": crew, "start_hour": round(start, 6),
                            "finish_hour": round(start + dur[i], 6),
                            "estimated_cost": cost[i], "service_weight": weight[i]})
    return {"objective": float(pulp.value(prob.objective)), "status": "Optimal", "actions": actions}


def check_schedule(actions, tasks, dependencies, budget, crews, horizon=None):
    """Independent feasibility checker. Returns a list of violations (empty means feasible)."""
    by_id = {t["task_id"]: t for t in tasks}
    skill = {c["crew_id"]: c["skill"] for c in crews}
    problems = []
    seen = set()
    total = 0.0
    for a in actions:
        tid = a["task_id"]
        if tid in seen:
            problems.append(f"{tid} scheduled twice")
        seen.add(tid)
        if tid not in by_id:
            problems.append(f"{tid} is not a task")
            continue
        task = by_id[tid]
        total += float(task["estimated_cost"])
        if a["crew_id"] not in skill:
            problems.append(f"{tid} uses unknown crew {a['crew_id']}")
        elif skill[a["crew_id"]] not in (task["required_skill"], "multi-skill"):
            problems.append(f"{tid} assigned to crew without the required skill")
        if a["finish_hour"] - a["start_hour"] + ROUNDING_TOL < float(task["estimated_hours"]):
            problems.append(f"{tid} duration shorter than estimate")
        if horizon is not None and a["finish_hour"] > horizon + TOL:
            problems.append(f"{tid} finishes after horizon")
    if total > budget + TOL:
        problems.append(f"budget exceeded: {total:.2f} > {budget:.2f}")
    times = {a["task_id"]: a for a in actions}
    for child, prereqs in dependencies.items():
        if child not in times:
            continue
        for pre in prereqs:
            if pre not in times:
                problems.append(f"{child} scheduled but prerequisite {pre} is not")
            elif times[child]["start_hour"] + ROUNDING_TOL < times[pre]["finish_hour"]:
                problems.append(f"{child} starts before prerequisite {pre} finishes")
    by_crew = {}
    for a in actions:
        by_crew.setdefault(a["crew_id"], []).append(a)
    for crew, items in by_crew.items():
        items.sort(key=lambda a: a["start_hour"])
        for prev, nxt in zip(items, items[1:]):
            if nxt["start_hour"] + ROUNDING_TOL < prev["finish_hour"]:
                problems.append(f"crew {crew} double-booked: {prev['task_id']} and {nxt['task_id']}")
    return problems


def value_within_horizon(actions, horizon):
    return sum(float(a["service_weight"]) for a in actions if a["finish_hour"] <= horizon + TOL)


def heuristic_actions(tasks_df, dependencies, budget, crews, strategy):
    """Run a scheduler heuristic and normalise its actions to the solver's format."""
    result = schedule_repairs(tasks_df, strategy, budget, crews, dependencies)
    return [{"task_id": a["task_id"], "crew_id": a["crew_id"], "start_hour": a["start_hour"],
             "finish_hour": a["finish_hour"], "estimated_cost": a["estimated_cost"],
             "service_weight": a["service_weight"]} for a in result["actions"]]


def evaluate_gap(tasks_df, dependencies, budget, crews, horizon, time_limit=120):
    """Solve exactly, then score each heuristic against the optimum on the same instance."""
    tasks = tasks_df.to_dict("records")
    opt = solve_exact(tasks, dependencies, budget, crews, horizon, time_limit)
    opt_problems = check_schedule(opt["actions"], tasks, dependencies, budget, crews, horizon)
    if opt_problems:
        raise AssertionError(f"solver produced an infeasible schedule: {opt_problems}")
    rows = []
    for strategy in STRATEGIES:
        acts = heuristic_actions(tasks_df, dependencies, budget, crews, strategy)
        problems = check_schedule(acts, tasks, dependencies, budget, crews)
        if problems:
            raise AssertionError(f"{strategy} produced an infeasible schedule: {problems}")
        value = value_within_horizon(acts, horizon)
        gap = 0.0 if opt["objective"] <= TOL else (opt["objective"] - value) / opt["objective"]
        rows.append({"strategy": strategy, "heuristic_value": value, "optimal_value": opt["objective"],
                     "gap_pct": round(100 * gap, 2)})
    return rows


def main(instances=200, seed=20261018, out_csv="docs/exact_gap_results.csv"):
    """Measure heuristic optimality gaps on random small instances (writes a CSV and prints a summary)."""
    import numpy as np
    import pandas as pd
    from .analytics import make_crews

    rng = np.random.default_rng(seed)
    rows = []
    for case in range(instances):
        n = int(rng.integers(6, 10))
        tasks = [dict(task_id=f"T{i}", estimated_hours=float(rng.integers(1, 7)),
                      estimated_cost=float(rng.integers(10, 60)), service_weight=float(rng.integers(1, 10)),
                      required_skill=str(rng.choice(["general", "electrical"])), priority=int(rng.integers(1, 6)))
                 for i in range(n)]
        deps = {f"T{i}": [f"T{i - 1}"] for i in range(1, n) if rng.random() < 0.3}
        crews = make_crews(int(rng.integers(1, 4)))
        budget = float(sum(t["estimated_cost"] for t in tasks) * rng.uniform(0.4, 0.9))
        horizon = float(sum(t["estimated_hours"] for t in tasks) / len(crews) * rng.uniform(0.5, 1.0))
        for row in evaluate_gap(pd.DataFrame(tasks), deps, budget, crews, horizon):
            rows.append({"instance": case, "tasks": n, "crews": len(crews), **row})
    frame = pd.DataFrame(rows)
    frame.to_csv(out_csv, index=False)
    summary = frame.groupby("strategy")["gap_pct"].agg(["mean", "median", "max",
                                                        lambda s: (s < 1e-6).mean() * 100])
    summary.columns = ["mean_gap_pct", "median_gap_pct", "max_gap_pct", "pct_instances_optimal"]
    print(summary.round(2).to_string())
    print(f"{instances} instances; results written to {out_csv}")
    return summary


if __name__ == "__main__":
    main()
