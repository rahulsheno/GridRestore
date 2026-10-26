"""Markdown run report: schedule, metrics and limitations, matching the notebook's experiment report."""
from datetime import datetime

LIMITATIONS = (
    "All network, outage, cost, repair-duration, crew and outcome data are synthetic.",
    "The scheduler is a greedy heuristic, not an optimal solver; see the exact-baseline section "
    "of docs/METHODOLOGY.md for measured gaps on small instances.",
    "Durations are fixed estimates. Robustness trials perturb them; real crews will differ.",
    "This is an academic demonstration, not an operational control system or validated power-flow model.",
)


def render_run_report(run, scenario, actions, tasks_by_id, dependencies):
    """run/scenario: dict rows; actions: scheduled_actions rows; tasks_by_id: {task_id: task dict}."""
    lines = []
    lines.append(f"# Restoration run {run['run_id']}: {scenario['scenario_name']}")
    lines.append("")
    started = run["started_at"]
    started = started.isoformat() if hasattr(started, "isoformat") else str(started)
    lines.append(f"Strategy: `{run['strategy_name']}`  ")
    lines.append(f"Saved: {started}  ")
    lines.append(f"Budget: {float(scenario['budget']):,.2f}  ")
    lines.append(f"Crews: {scenario['crew_count']}")
    lines.append("")
    lines.append("## Metrics")
    lines.append("")
    lines.append("| Metric | Value |")
    lines.append("| --- | --- |")
    lines.append(f"| Total cost | {float(run['total_cost']):,.2f} |")
    lines.append(f"| Makespan (hours) | {float(run['makespan_hours']):.2f} |")
    lines.append(f"| Weighted recovery score | {float(run['weighted_recovery_score']):.4f} |")
    lines.append(f"| Scheduled tasks | {len(actions)} of {len(tasks_by_id)} |")
    lines.append("")
    lines.append("## Schedule")
    lines.append("")
    lines.append("| Task | Crew | Start (h) | Finish (h) | Prerequisites |")
    lines.append("| --- | --- | ---: | ---: | --- |")
    for a in sorted(actions, key=lambda r: (float(r["start_hour"]), r["task_id"])):
        prereqs = ", ".join(sorted(dependencies.get(a["task_id"], []))) or "none"
        lines.append(f"| {a['task_id']} | {a['crew_label']} | {float(a['start_hour']):.2f} | "
                     f"{float(a['finish_hour']):.2f} | {prereqs} |")
    unscheduled = sorted(set(tasks_by_id) - {a["task_id"] for a in actions})
    lines.append("")
    lines.append("## Unscheduled tasks")
    lines.append("")
    lines.append(", ".join(unscheduled) if unscheduled else "None: every task was scheduled.")
    lines.append("")
    lines.append("## Limitations")
    lines.append("")
    lines.extend(f"- {item}" for item in LIMITATIONS)
    lines.append("")
    lines.append(f"_Generated {datetime.now().strftime('%Y-%m-%d %H:%M')} from the stored run._")
    return "\n".join(lines) + "\n"
