"""Deterministic scale seed: bulk synthetic volume for the performance story.

Creates ONE extra scenario ('Scale test 10k') with 10,000 repair_tasks,
~2,000 chain dependencies, 500 runs + actions, and 5,000 embeddings — all from
a fixed seed so results are reproducible. Demo rows (T01..T08) are untouched.
Run: python -m backend.scale_seed
"""
import random
import numpy as np
from pgvector.psycopg import register_vector
from .db import connect
from .vectors import embed_text, DIM

SEED = 20261018
N_TASKS = 10000
N_RUNS = 500
N_EMBED = 5000
CAUSES = ["storm", "equipment_age", "vehicle_impact", "vegetation", "unknown"]
SKILLS = ["general", "general", "general", "electrical"]
NARRATIVE_WORDS = ["feeder", "line", "pole", "transformer", "fuse", "repair",
                   "storm", "hospital", "residential", "industrial", "branch",
                   "inspection", "restringing", "testing", "emergency", "feeder"]

def run():
    rng = random.Random(SEED)
    with connect() as conn:
        register_vector(conn)
        with conn.cursor() as cur:
            scenario = cur.execute(
                "INSERT INTO outage_scenarios(scenario_name,budget,crew_count) "
                "VALUES(%s,%s,%s) RETURNING scenario_id",
                ("Scale test 10k", 50_000_000, 10)).fetchone()
            sid = scenario["scenario_id"]
            print("scale scenario:", sid)
            batch = []
            for i in range(N_TASKS):
                tid = f"S{i:05d}"
                batch.append((tid, sid, "E1", f"Scale component {tid}",
                              round(rng.uniform(0.5, 12.0), 2),
                              round(rng.uniform(200, 9000), 2),
                              round(rng.uniform(1.0, 10.0), 2),
                              rng.randint(1, 5), rng.choice(["North", "Central", "South"]),
                              rng.choice(SKILLS), rng.choice(CAUSES), "pending"))
                if len(batch) == 1000:
                    cur.executemany(
                        "INSERT INTO repair_tasks(task_id,scenario_id,edge_id,component_name,"
                        "estimated_hours,estimated_cost,service_weight,priority,region_code,"
                        "required_skill,outage_cause,status) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                        batch)
                    batch = []
            if batch:
                cur.executemany(
                    "INSERT INTO repair_tasks(task_id,scenario_id,edge_id,component_name,"
                    "estimated_hours,estimated_cost,service_weight,priority,region_code,"
                    "required_skill,outage_cause,status) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                    batch)
            deps = [(f"S{i:05d}", f"S{i-1:05d}") for i in range(1, N_TASKS, 5)]
            cur.executemany("INSERT INTO task_dependencies(task_id,prerequisite_task_id) "
                            "VALUES(%s,%s) ON CONFLICT DO NOTHING", deps)
            strategies = ["priority_first", "shortest_repair_first", "gridrestore_score"]
            for r in range(N_RUNS):
                strategy = strategies[r % 3]
                cost = round(rng.uniform(5000, 40000), 2)
                makespan = round(rng.uniform(5, 120), 2)
                score = round(rng.uniform(1, 60), 4)
                row = cur.execute(
                    "INSERT INTO restoration_runs(scenario_id,strategy_name,total_cost,"
                    "makespan_hours,weighted_recovery_score,notes) VALUES(%s,%s,%s,%s,%s,%s) "
                    "RETURNING run_id",
                    (sid, strategy, cost, makespan, score, '{"source":"scale_seed"}')).fetchone()
                rid = row["run_id"]
                sample = rng.sample(range(N_TASKS), 8)
                cur.executemany(
                    "INSERT INTO scheduled_actions(run_id,task_id,crew_label,start_hour,finish_hour) "
                    "VALUES(%s,%s,%s,%s,%s)",
                    [(rid, f"S{i:05d}", f"C{(i % 10) + 1}",
                      round(rng.uniform(0, 40), 2), round(rng.uniform(41, 80), 2))
                     for i in sample])
            for i in rng.sample(range(N_TASKS), N_EMBED):
                tid = f"S{i:05d}"
                narrative = " ".join(rng.sample(NARRATIVE_WORDS, 6)) + f" {tid}"
                cur.execute("SELECT upsert_repair_embedding(%s,%s,%s)",
                            (tid, narrative, np.array(embed_text(narrative, DIM))))
    print(f"seeded {N_TASKS} tasks, {len(deps)} deps, {N_RUNS} runs, {N_EMBED} embeddings")
    return sid

if __name__ == "__main__":
    run()
