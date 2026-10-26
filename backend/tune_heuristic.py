"""Tune the gridrestore_score heuristic against the exact solver (item 6).

Method: random small instances (the regime where the exact MILP baseline is
tractable), the same measuring rule as docs/METHODOLOGY.md — the horizon
objective: the summed service weight of tasks finishing by the horizon. The
heuristic's two ordering knobs are re-fitted by grid search:

    score(task) = weight * physics / hours ** hours_exponent
                  + (6 - priority) * priority_weight

The winning parameters land in backend/heuristic_weights.json and are picked up
by backend/scheduler.py::schedule_repairs on every subsequent call.

Usage:
    python -m backend.tune_heuristic            # 150 instances, ~2-6 min
    python -m backend.tune_heuristic --quick    # 40 instances, fast check
"""
import argparse
import itertools
import json
import random
import time

from .scheduler import heuristic_params, schedule_repairs
from .exact import solve_exact

HORIZON = 40.0


def random_instance(seed: int, n_tasks: int = 10, n_crews: int = 3, n_deps: int = 5):
    rng = random.Random(seed)
    tasks = []
    for i in range(n_tasks):
        tid = f"T{i:02d}"
        tasks.append({"task_id": tid,
                      "component_name": f"component {i}",
                      "estimated_hours": round(rng.uniform(0.5, 6.0), 2),
                      "estimated_cost": round(rng.uniform(200, 2500), 2),
                      "service_weight": round(rng.uniform(0.2, 10.0), 2),
                      "priority": rng.randint(1, 5),
                      "required_skill": rng.choice(["general", "general", "electrical"])})
    sets = {"general": [c for c in range(n_crews)],
            "electrical": [0]}
    crews = [{"crew_id": f"C{c+1}",
              "skill": "electrical" if c == 0 and n_crews > 1 else rng.choice(["multi-skill", "general", "general"]),
              "available_from": 0.0} for c in range(n_crews)]
    # Crew 0 is multi-skill when tasks need it covered: make crew with electrical skill usable.
    crews[0]["skill"] = "multi-skill" if n_crews > 0 else crews[0]["skill"]
    dependencies = {}
    for _ in range(n_deps):
        a, b = rng.sample(range(n_tasks), 2)
        child, pre = f"T{max(a,b):02d}", f"T{min(a,b):02d}"
        deps_for_child = dependencies.setdefault(child, [])
        if pre not in deps_for_child:          # deduplicate: the exact MILP has named constraints
            deps_for_child.append(pre)
    # keep only indices below the child (acyclic by construction) and deduplicate
    dependencies = {c: [p for p in dict.fromkeys(ps) if int(p[1:]) < int(c[1:])]
                    for c, ps in dependencies.items() if ps}
    # budget: enough for a majority of tasks but not all
    total = sum(t["estimated_cost"] for t in tasks)
    budget = round(total * rng.uniform(0.55, 0.95), 2)
    return tasks, dependencies, budget, crews


def grid(scale=1.0):
    exps = [round(e, 3) for e in (0.5, 0.75, 1.0, 1.25, 1.5)]
    pws = [round(p, 3) for p in (0.0, 0.05, 0.10, 0.15, 0.20, 0.25)]
    return list(itertools.product(exps, pws))


def _horizon_objective(sched, weight_by_id, horizon):
    return sum(weight_by_id[a["task_id"]] for a in sched["actions"] if a["finish_hour"] <= horizon)


def tune(n_instances: int = 150, seed0: int = 20261018, log_every: int = 50):
    combos = grid()
    gaps = {c: [] for c in combos}
    baseline = set()
    t0 = time.perf_counter()
    exact_times = []
    for i in range(n_instances):
        tasks, deps, budget, crews = random_instance(seed0 + i)
        weight = {t["task_id"]: float(t["service_weight"]) for t in tasks}
        t1 = time.perf_counter()
        exact = solve_exact(tasks, deps, budget, crews, HORIZON)
        exact_times.append(time.perf_counter() - t1)
        opt = _horizon_objective(exact, weight, HORIZON)
        if opt <= 0:
            continue  # nothing achievable; skip instance
        for combo in combos:
            params = heuristic_params()
            params["hours_exponent"], params["priority_weight"] = combo
            _apply(params)
            sched = schedule_repairs(_frame(tasks), "gridrestore_score", budget,
                                     crews, deps)
            h = _horizon_objective(sched, weight, HORIZON)
            gaps[combo].append((opt - h) / opt)
        if (i + 1) % log_every == 0:
            best = min(gaps, key=lambda c: (sum(gaps[c]) / max(1, len(gaps[c]))))
            print(f"  instance {i+1}/{n_instances}  best so far {best} "
                  f"mean gap {sum(gaps[best])/max(1,len(gaps[best])):.3f}  "
                  f"({time.perf_counter()-t0:.0f}s)")
    scored = []
    for c, g in gaps.items():
        if g:
            scored.append({"hours_exponent": c[0], "priority_weight": c[1],
                           "mean_gap": round(sum(g)/len(g), 5), "n": len(g)})
    scored.sort(key=lambda r: r["mean_gap"])
    best = scored[0]
    with open("backend/heuristic_weights.json", "w") as fh:
        json.dump(best, fh, indent=2)
    baseline_params = heuristic_params()
    print(f"tuned ({n_instances} instances, {(time.perf_counter()-t0)/60:.1f} min, "
          f"mean exact solve {sum(exact_times)/len(exact_times):.2f}s):")
    for r in scored[:5]:
        print("  ", r)
    print(f"written: backend/heuristic_weights.json -> {best}")
    return best, scored


def _frame(tasks):
    import pandas as pd
    return pd.DataFrame(tasks)


def _apply(params):
    """Temporarily point schedule_repairs at the candidate parameters."""
    import backend.scheduler as S
    S.heuristic_params = lambda: params


def restore():
    import backend.scheduler as S
    S.heuristic_params = _original


_original = None


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--quick", action="store_true", help="40 instances for a fast check")
    ap.add_argument("--instances", type=int, default=150)
    args = ap.parse_args()
    if args.quick:
        args.instances = 40
    import backend.scheduler as S
    _original = S.heuristic_params
    try:
        tune(args.instances)
    finally:
        S.heuristic_params = _original
