"""Decision-support analytics on top of the scheduler.

- sweep(): run every strategy over a grid of budgets and crew counts.
- compare_strategies(): seeded robustness trials. Each trial perturbs repair durations by a
  uniform factor in [1-noise, 1+noise]. The SAME perturbation is used for every strategy in a
  trial (common random numbers), so differences between strategies are not caused by luck.
- Confidence intervals are normal-approximation 95% intervals: mean +/- 1.96 * s / sqrt(n).

Run from the command line to produce CSV files and figures in docs/figures:
    python -m backend.analytics
"""
import math
import sys

import numpy as np
import pandas as pd

from .scheduler import STRATEGIES, schedule_repairs

Z95 = 1.96


def make_crews(count):
    """Deterministic crew mix: one multi-skill crew, then electrical and general crews."""
    crews = []
    for i in range(count):
        if i == 0:
            skill = "multi-skill"
        elif i % 3 == 0:
            skill = "electrical"
        else:
            skill = "general"
        crews.append({"crew_id": f"C{i + 1}", "skill": skill, "available_from": 0.0})
    return crews


def sweep(frame, dependencies, budgets, crew_counts, strategies=STRATEGIES):
    rows = []
    for strategy in strategies:
        for budget in budgets:
            for count in crew_counts:
                result = schedule_repairs(frame, strategy, float(budget), make_crews(count), dependencies)
                rows.append({
                    "strategy": strategy, "budget": float(budget), "crews": count,
                    "weighted_recovery_score": result["weighted_recovery_score"],
                    "makespan_hours": result["makespan_hours"],
                    "total_cost": result["total_cost"],
                    "scheduled_count": result["scheduled_count"],
                })
    return pd.DataFrame(rows)


def _ci95(values):
    arr = np.asarray(values, dtype=float)
    n = len(arr)
    mean = float(arr.mean())
    if n < 2:
        return {"mean": mean, "std": 0.0, "ci95_low": mean, "ci95_high": mean, "n": n}
    std = float(arr.std(ddof=1))
    half = Z95 * std / math.sqrt(n)
    return {"mean": mean, "std": std, "ci95_low": mean - half, "ci95_high": mean + half, "n": n}


def compare_strategies(frame, dependencies, budget, crews, trials=200, noise=0.2, seed=20261018,
                       strategies=STRATEGIES):
    """Return per-strategy mean and 95% CI for makespan and score over seeded trials."""
    if not 0 <= noise < 1:
        raise ValueError("noise must be in [0, 1)")
    if not 2 <= trials <= 5000:
        raise ValueError("trials must be between 2 and 5000")
    rng = np.random.default_rng(seed)
    base_hours = frame["estimated_hours"].astype(float).to_numpy()
    multipliers = rng.uniform(1 - noise, 1 + noise, size=(trials, len(base_hours)))

    samples = {s: {"makespan": [], "score": [], "scheduled": []} for s in strategies}
    for t in range(trials):
        perturbed = frame.copy()
        perturbed["estimated_hours"] = base_hours * multipliers[t]
        for strategy in strategies:
            result = schedule_repairs(perturbed, strategy, budget, crews, dependencies)
            samples[strategy]["makespan"].append(result["makespan_hours"])
            samples[strategy]["score"].append(result["weighted_recovery_score"])
            samples[strategy]["scheduled"].append(result["scheduled_count"])

    out = {}
    for strategy in strategies:
        s = samples[strategy]
        out[strategy] = {"makespan_hours": _ci95(s["makespan"]),
                         "weighted_recovery_score": _ci95(s["score"]),
                         "scheduled_count": _ci95(s["scheduled"])}
    return {"trials": trials, "noise": noise, "seed": seed, "strategies": out}


def write_outputs(frame, dependencies, out_dir="docs/figures", csv_dir="docs"):
    import os
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    os.makedirs(out_dir, exist_ok=True)
    # Budgets are fractions of the scenario's total repair cost, so the grid covers the
    # interesting range (from a few tasks affordable to nearly all of them) for any scenario.
    total_cost = float(frame["estimated_cost"].astype(float).sum())
    budgets = np.round(np.linspace(0.05, 0.6, 10) * total_cost, 2)
    crew_counts = [1, 2, 3, 4, 5, 6]
    grid = sweep(frame, dependencies, budgets, crew_counts)
    grid.to_csv(os.path.join(csv_dir, "sweep_results.csv"), index=False)

    fig, axes = plt.subplots(1, 2, figsize=(11, 4.2))
    for strategy in STRATEGIES:
        sub = grid[(grid.strategy == strategy) & (grid.crews == 3)].sort_values("budget")
        axes[0].plot(sub.budget / 1000, sub.weighted_recovery_score, marker="o", label=strategy)
        sub = grid[(grid.strategy == strategy) & (grid.budget == budgets[-1])].sort_values("crews")
        axes[1].plot(sub.crews, sub.makespan_hours, marker="o", label=strategy)
    axes[0].set(title="Score vs budget (3 crews)", xlabel="Budget (thousands)",
                ylabel="Weighted recovery score")
    axes[1].set(title="Makespan vs crews (max budget)", xlabel="Crews", ylabel="Makespan (hours)")
    axes[0].legend()
    fig.tight_layout()
    fig.savefig(os.path.join(out_dir, "sweep_budget_crews.png"), dpi=120)
    plt.close(fig)
    return grid


def main(argv=None):
    import argparse
    import pandas as pd
    from .db import get_scenario_tasks

    parser = argparse.ArgumentParser(description="Budget/crew sweep for one scenario.")
    parser.add_argument("scenario_id", type=int)
    args = parser.parse_args(argv)
    rows, deps = get_scenario_tasks(args.scenario_id)
    if not rows:
        raise SystemExit(f"Scenario {args.scenario_id} has no repair tasks")
    grid = write_outputs(pd.DataFrame(rows), deps)
    print(grid.groupby("strategy")["weighted_recovery_score"].max().round(3).to_string())
    print("wrote docs/sweep_results.csv and docs/figures/sweep_budget_crews.png")


if __name__ == "__main__":
    main()
