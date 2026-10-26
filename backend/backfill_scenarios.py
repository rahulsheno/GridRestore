"""Backfill task lists for scenarios created before cloning was added.

Run: python -m backend.backfill_scenarios
"""
from .db import backfill_scenario_tasks


if __name__ == "__main__":
    result = backfill_scenario_tasks()
    for scenario_id, count in result.items():
        print(f"scenario {scenario_id}: copied {count} task(s)")
    print(f"backfilled {len(result)} scenario(s)")
