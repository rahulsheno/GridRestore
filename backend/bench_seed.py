"""Benchmark dataset: 500 grid nodes, 50 scenarios with 500 repair tasks each, and saved runs.

Every run is produced by the real scheduler and saved through save_run(), so the crew-overlap
constraint, the audit triggers and the cost checks are all exercised on realistic data.
Deterministic: the same seed gives the same database contents.

Rebuild:  python -m backend.bench_seed           (replaces earlier 'Bench' data only)
"""
import random
import time

from .analytics import make_crews
from .db import connect, save_run
from .scheduler import STRATEGIES, schedule_repairs

SEED = 20261018
N_NODES = 500
N_SCENARIOS = 50
TASKS_PER_SCENARIO = 500
CAUSES = ["storm", "equipment_age", "vehicle_impact", "vegetation", "unknown"]
NODE_TYPES = ["substation", "bus", "residential", "industrial", "hospital", "water_facility"]
REGIONS = ["North", "Central", "South"]


def _clear(cur):
    # Runs go before scenarios (see db.delete_scenario); only Bench rows are removed.
    cur.execute("DELETE FROM restoration_runs WHERE scenario_id IN "
                "(SELECT scenario_id FROM outage_scenarios WHERE scenario_name LIKE 'Bench S%')")
    cur.execute("DELETE FROM outage_scenarios WHERE scenario_name LIKE 'Bench S%'")
    cur.execute("DELETE FROM grid_edges WHERE edge_id LIKE 'GE%'")
    cur.execute("DELETE FROM grid_nodes WHERE node_id LIKE 'GN%'")


def _insert_grid(cur, rng):
    nodes = []
    for i in range(N_NODES):
        nodes.append((f"GN{i:04d}", f"Bench node {i}", rng.choice(NODE_TYPES),
                      round(rng.uniform(1.0, 10.0), 2), rng.choice(REGIONS)))
    cur.executemany("INSERT INTO grid_nodes(node_id,node_name,node_type,criticality,region_code) "
                    "VALUES (%s,%s,%s,%s,%s)", nodes)
    # A spanning tree: every node after the first connects to an earlier node (N_NODES - 1 edges).
    edges = []
    for i in range(1, N_NODES):
        parent = rng.randrange(i)
        edges.append((f"GE{i:04d}", f"GN{parent:04d}", f"GN{i:04d}",
                      rng.choice(["feeder", "line", "tie_line"]), round(rng.uniform(500, 6000), 2)))
    cur.executemany("INSERT INTO grid_edges(edge_id,from_node_id,to_node_id,component_type,"
                    "nominal_capacity_kw) VALUES (%s,%s,%s,%s,%s)", edges)
    return [e[0] for e in edges]


def _insert_scenario(cur, rng, index, edge_ids, budget, crew_count):
    scenario = cur.execute(
        "INSERT INTO outage_scenarios(scenario_name,budget,crew_count) VALUES (%s,%s,%s) "
        "RETURNING scenario_id", (f"Bench S{index:02d}", budget, crew_count)).fetchone()
    sid = scenario["scenario_id"]
    tasks, deps = [], []
    for i in range(TASKS_PER_SCENARIO):
        tid = f"BT{index:02d}-{i:03d}"
        skill = "electrical" if rng.random() < 0.25 else "general"
        tasks.append((tid, sid, rng.choice(edge_ids), f"Bench component {tid}",
                      round(rng.uniform(0.5, 12.0), 2), round(rng.uniform(200, 9000), 2),
                      round(rng.uniform(1.0, 10.0), 2), rng.randint(1, 5),
                      rng.choice(REGIONS), skill, rng.choice(CAUSES), "pending"))
        if i % 5 == 4:  # a chain every five tasks: a branch waits on its upstream repair
            deps.append((tid, f"BT{index:02d}-{i - 1:03d}"))
    cur.executemany(
        "INSERT INTO repair_tasks(task_id,scenario_id,edge_id,component_name,estimated_hours,"
        "estimated_cost,service_weight,priority,region_code,required_skill,outage_cause,status) "
        "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)", tasks)
    cur.executemany("INSERT INTO task_dependencies(task_id,prerequisite_task_id) VALUES (%s,%s)", deps)
    return sid, tasks, deps


def run(verbose=True):
    rng = random.Random(SEED)
    started = time.perf_counter()
    with connect() as conn:
        with conn.cursor() as cur:
            _clear(cur)
            edge_ids = _insert_grid(cur, rng)
    scenario_ids = []
    for s in range(N_SCENARIOS):
        crew_count = 3 + (s % 4)  # 3 to 6 crews across scenarios
        with connect() as conn:  # one transaction per scenario
            with conn.cursor() as cur:
                sid, tasks, deps = _insert_scenario(cur, rng, s + 1, edge_ids, 1.0, crew_count)
                # Budget is 35% of total repair cost, so every scenario is budget-constrained.
                budget = round(sum(t[5] for t in tasks) * 0.35, 2)
                cur.execute("UPDATE outage_scenarios SET budget=%s WHERE scenario_id=%s", (budget, sid))
        scenario_ids.append(sid)
        dependencies = {}
        for child, prereq in deps:
            dependencies.setdefault(child, []).append(prereq)
        frame = _frame(tasks)
        crews = make_crews(crew_count)
        for strategy in STRATEGIES:
            result = schedule_repairs(frame, strategy, budget, crews, dependencies)
            save_run(sid, result, notes={"source": "bench_seed", "strategy": strategy,
                                         "crews": crews}, username="bench")
    elapsed = time.perf_counter() - started
    if verbose:
        print(f"bench dataset: {N_NODES} nodes, {N_SCENARIOS} scenarios x {TASKS_PER_SCENARIO} tasks, "
              f"{N_SCENARIOS * len(STRATEGIES)} runs, built in {elapsed:.1f}s")
    return scenario_ids


def _frame(tasks):
    import pandas as pd
    return pd.DataFrame([{"task_id": t[0], "estimated_hours": t[4], "estimated_cost": t[5],
                          "service_weight": t[6], "priority": t[7], "required_skill": t[9]}
                         for t in tasks])


if __name__ == "__main__":
    run()
