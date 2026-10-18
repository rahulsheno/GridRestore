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
