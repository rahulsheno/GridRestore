# Methodology

## Strategies
- `priority_first`: sort by priority, then service weight.
- `shortest_repair_first`: sort by estimated duration.
- `gridrestore_score`: sort by service weight per duration with a small priority bonus.

All strategies enforce the same budget, crew eligibility and dependency prerequisites. The scheduler is greedy and not guaranteed optimal. Task order is a heuristic, not a proof of globally optimal recovery.

## Uncertainty
The notebook uses seeded lognormal multipliers for repair-duration stress tests. Report mean, standard deviation and percentile statistics. These are scenario experiments, not calibrated forecasts.

## Metrics
`weighted_recovery_score = sum(service_weight / finish_hour)` is a project-defined comparative score. It is not an IEC/IEEE standard metric. Makespan is the maximum crew completion time; cost is the sum of scheduled task costs.

---

## Exact baseline (small instances)

`backend/exact.py` solves each instance as a mixed-integer program (PuLP with the CBC solver).
Objective, the same for solver and heuristics: maximise the total service weight of tasks that
finish by a horizon H, subject to the budget, one crew per task with a matching skill, a crew
doing one task at a time, prerequisites finishing before their dependants start, and a
prerequisite of a scheduled task also being scheduled.

Checks performed:

- On 60 random instances with 3 to 6 tasks, the optimum equals an exhaustive search over every
  order and crew choice (maximum difference 0.0). Test: `tests/test_features_pure.py`.
- Every solver schedule and every heuristic schedule passes an independent checker
  (`check_schedule`). The checker allows 0.002 h of rounding, because the scheduler rounds start and finish
  to three decimals separately.

Gap study (`python -m backend.exact`, 200 random instances with 6 to 9 tasks, 1 to 3 crews, seed
20261018; full results in `docs/exact_gap_results.csv`):

| Strategy | Mean gap | Median gap | Max gap | Instances solved optimally |
| --- | ---: | ---: | ---: | ---: |
| gridrestore_score | 14.7% | 11.1% | 61.9% | 32% |
| shortest_repair_first | 22.4% | 21.2% | 87.5% | 22% |
| priority_first | 28.0% | 27.1% | 85.7% | 13% |

The gap is relative to the optimum on the same instance. The exact solver is limited to about 12 tasks and
4 crews, so these results describe small instances. They do not show how far the heuristics are from the
optimum at benchmark size. The gap is measured on the horizon objective; the heuristics optimise a
different score (weight divided by finish time), so a heuristic can be near-optimal on this objective and
still be imperfect on the other.

## Seeded robustness

Each trial multiplies every repair duration by a uniform factor in [1 - noise, 1 + noise]. The
same multipliers are shared by all strategies in a trial, so differences between strategies come from
the strategies, not from luck. Confidence intervals are normal-approximation 95% intervals,
mean ± 1.96 s / sqrt(n).

On the benchmark scenario (budget 35% of total cost, 3 crews, 100 trials, noise 0.2, seed 20261018;
`docs/robustness_results.json`):

- `gridrestore_score`: score 111.4 (95% CI 110.4 to 112.3), makespan 222.7 h (221.1 to 224.4)
- `shortest_repair_first`: score 98.3 (97.2 to 99.4), makespan 184.4 h (183.1 to 185.6)
- `priority_first`: score 18.2 (18.1 to 18.4), makespan 338.4 h (337.7 to 339.1)

The intervals do not overlap for score, so the ranking holds under the duration noise tested. The
interval only reflects duration noise; it says nothing about errors in the model itself.
Note that `shortest_repair_first` has the shorter makespan, so the best heuristic depends on whether
score or makespan matters more.

## Schedule change report

`GET /api/runs/diff` compares two runs of the same scenario task by task and labels each change:
`upstream_delay` (a prerequisite finishes later), `crew_contention` (the task waited for a crew after its
prerequisites were done), `dispatch_reordered` (its own position in the order changed), or
`finished_earlier`. Tasks present in only one run are listed as dropped or added.
