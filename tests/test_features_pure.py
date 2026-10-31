"""Tests for the new logic that needs no database: exact solver, CSV validation, run diffs,
analytics, Markdown report, structured logging and token handling."""
import json
import logging

import numpy as np
import pandas as pd
import pytest

from backend import auth, diffing, exact, report, tasks_io
from backend.analytics import compare_strategies, make_crews, sweep
from backend.logging_config import JsonFormatter
from backend.scheduler import STRATEGIES, schedule_repairs


def _random_instance(rng, n):
    tasks = [dict(task_id=f"T{i}", estimated_hours=float(rng.integers(1, 6)),
                  estimated_cost=float(rng.integers(10, 50)), service_weight=float(rng.integers(1, 10)),
                  required_skill=str(rng.choice(["general", "electrical"])), priority=1) for i in range(n)]
    deps = {f"T{i}": [f"T{i - 1}"] for i in range(1, n) if rng.random() < 0.35}
    return tasks, deps


def _brute_force(tasks, deps, budget, crews, horizon):
    """Exhaustive search over every order and crew choice (earliest-start placement)."""
    by = {t["task_id"]: t for t in tasks}
    skill = {c["crew_id"]: c["skill"] for c in crews}
    best = [0.0]

    def eligible(i):
        return [k for k in skill if skill[k] in (by[i]["required_skill"], "multi-skill")]

    def dfs(remaining, free, finish, cost, value):
        best[0] = max(best[0], value)
        for i in remaining:
            if cost + by[i]["estimated_cost"] > budget + 1e-9:
                continue
            if any(p not in finish for p in deps.get(i, [])):
                continue
            ready = max([finish[p] for p in deps.get(i, [])], default=0.0)
            for k in eligible(i):
                start = max(free[k], ready)
                end = start + by[i]["estimated_hours"]
                if end > horizon + 1e-9:
                    continue
                nfree, nfinish = dict(free), dict(finish)
                nfree[k], nfinish[i] = end, end
                dfs(remaining - {i}, nfree, nfinish, cost + by[i]["estimated_cost"],
                    value + by[i]["service_weight"])

    dfs(frozenset(by), {k: 0.0 for k in skill}, {}, 0.0, 0.0)
    return best[0]


# ---------------------------------------------------------------- exact baseline

def test_solver_matches_hand_checked_case():
    tasks = [dict(task_id=t, estimated_hours=2, estimated_cost=10, service_weight=w,
                  required_skill="general") for t, w in [("A", 5), ("B", 3), ("C", 4)]]
    result = exact.solve_exact(tasks, {"B": ["A"]}, 100, [{"crew_id": "K1", "skill": "general"}], horizon=5)
    # One crew, 5 hours: A then C (2+2h) is worth 9; B needs A and cannot also fit.
    assert result["objective"] == pytest.approx(9.0)


@pytest.mark.parametrize("seed", [7, 11])
def test_solver_equals_exhaustive_search(seed):
    rng = np.random.default_rng(seed)
    for _ in range(8):
        tasks, deps = _random_instance(rng, int(rng.integers(3, 6)))
        crews = make_crews(int(rng.integers(1, 4)))
        budget = float(sum(t["estimated_cost"] for t in tasks) * rng.uniform(0.4, 1.0))
        horizon = float(sum(t["estimated_hours"] for t in tasks) / len(crews) * rng.uniform(0.5, 1.1))
        opt = exact.solve_exact(tasks, deps, budget, crews, horizon)
        assert exact.check_schedule(opt["actions"], tasks, deps, budget, crews, horizon) == []
        assert opt["objective"] == pytest.approx(_brute_force(tasks, deps, budget, crews, horizon), abs=1e-6)


def test_heuristics_never_beat_the_optimum():
    rng = np.random.default_rng(3)
    for _ in range(6):
        tasks, deps = _random_instance(rng, int(rng.integers(5, 9)))
        crews = make_crews(int(rng.integers(1, 4)))
        budget = float(sum(t["estimated_cost"] for t in tasks) * 0.6)
        horizon = float(sum(t["estimated_hours"] for t in tasks) / len(crews) * 0.8)
        rows = exact.evaluate_gap(pd.DataFrame(tasks), deps, budget, crews, horizon, time_limit=30)
        assert {r["strategy"] for r in rows} == set(STRATEGIES)
        assert all(r["gap_pct"] >= -1e-6 for r in rows)


def test_checker_reports_each_kind_of_violation():
    tasks = [dict(task_id="A", estimated_hours=2, estimated_cost=50, service_weight=1, required_skill="electrical"),
             dict(task_id="B", estimated_hours=2, estimated_cost=50, service_weight=1, required_skill="general")]
    crews = [{"crew_id": "G", "skill": "general"}]
    bad = [{"task_id": "A", "crew_id": "G", "start_hour": 0, "finish_hour": 2},   # wrong skill
           {"task_id": "B", "crew_id": "G", "start_hour": 1, "finish_hour": 3}]   # overlaps on crew G
    text = " | ".join(exact.check_schedule(bad, tasks, {"B": ["A"]}, 80, crews))
    assert "without the required skill" in text
    assert "double-booked" in text
    assert "budget exceeded" in text
    assert "starts before prerequisite" in text


def test_heuristic_schedule_passes_checker():
    rng = np.random.default_rng(5)
    tasks, deps = _random_instance(rng, 8)
    crews = make_crews(3)
    acts = exact.heuristic_actions(pd.DataFrame(tasks), deps, 300, crews, "gridrestore_score")
    assert exact.check_schedule(acts, tasks, deps, 300, crews) == []


# ---------------------------------------------------------------- CSV validation

CSV_HEADER = "task_id,edge_id,component_name,estimated_hours,estimated_cost,service_weight,priority\n"
EDGES = {"E1", "E2"}


def _validate(body, existing_global=(), scenario=()):
    return tasks_io.validate_task_csv(body, EDGES, set(existing_global), set(scenario))


def test_valid_csv_is_accepted_and_normalised():
    body = CSV_HEADER + "X1,E1,Feeder,3,1200,6,2\nX2,E2,Line,4.5,800,3,4\n"
    result = _validate(body)
    assert result["valid"], result["errors"]
    assert [r["region_code"] for r in result["rows"]] == ["Unassigned", "Unassigned"]
    assert result["rows"][1]["estimated_hours"] == 4.5


def test_every_row_error_is_reported_together():
    body = CSV_HEADER + ("X1,E9,Feeder,3,1200,6,2\n"      # unknown edge
                         "X2,E1,Line,0,800,3,4\n"         # zero hours
                         "X3,E1,Line,2,800,3,9\n"         # priority out of range
                         "X3,E1,Dup,2,800,3,2\n")         # duplicate id
    result = _validate(body)
    assert not result["valid"] and result["rows"] == []
    rows_with_errors = {e["row"] for e in result["errors"]}
    assert {2, 3, 4, 5} <= rows_with_errors
    columns = {(e["row"], e["column"]) for e in result["errors"]}
    assert (2, "edge_id") in columns and (4, "priority") in columns and (5, "task_id") in columns


def test_missing_and_unknown_columns_are_header_errors():
    result = _validate("task_id,edge_id,colour\nX1,E1,red\n")
    messages = " ".join(e["message"] for e in result["errors"])
    assert "missing required column" in messages and "unknown column" in messages


def test_ids_already_in_database_are_rejected():
    result = _validate(CSV_HEADER + "T01,E1,Feeder,3,1200,6,2\n", existing_global={"T01"})
    assert any("already exists" in e["message"] for e in result["errors"])


def test_prerequisite_may_appear_later_in_file_but_must_exist_somewhere():
    header = "task_id,edge_id,component_name,estimated_hours,estimated_cost,service_weight,priority,depends_on\n"
    later = header + "X2,E1,B,2,100,1,1,X1\nX1,E1,A,2,100,1,1,\n"
    assert _validate(later)["valid"]
    missing = header + "X2,E1,B,2,100,1,1,NOPE\n"
    assert any("not in this scenario" in e["message"] for e in _validate(missing)["errors"])
    in_scenario = header + "X2,E1,B,2,100,1,1,S1\n"
    assert _validate(in_scenario, scenario={"S1"})["valid"]


def test_cycle_in_file_is_rejected():
    body = ("task_id,edge_id,component_name,estimated_hours,estimated_cost,service_weight,priority,depends_on\n"
            "X1,E1,A,2,100,1,1,X2\nX2,E1,B,2,100,1,1,X1\n")
    result = _validate(body)
    assert not result["valid"]
    assert any("cycle" in e["message"].lower() for e in result["errors"])


def test_bad_numbers_and_short_rows():
    body = CSV_HEADER + "X1,E1,Feeder,abc,1200,6,2\nX2,E1,Feeder,2\n"
    messages = " | ".join(e["message"] for e in _validate(body)["errors"])
    assert "not a number" in messages and "too few values" in messages


def test_export_round_trips_through_validation():
    rows = [{"task_id": "R1", "edge_id": "E1", "component_name": "Feeder, north", "estimated_hours": 3.0,
             "estimated_cost": 1200.0, "service_weight": 6.0, "priority": 2, "region_code": "North",
             "required_skill": "electrical", "outage_cause": "storm"},
            {"task_id": "R2", "edge_id": "E2", "component_name": "Line", "estimated_hours": 2.0,
             "estimated_cost": 100.0, "service_weight": 1.0, "priority": 3, "region_code": "South",
             "required_skill": "general", "outage_cause": "unknown"}]
    text = tasks_io.export_task_csv(rows, {"R2": ["R1"]})
    result = _validate(text)
    assert result["valid"], result["errors"]
    assert result["rows"][1]["depends_on"] == ["R1"]
    assert result["rows"][0]["component_name"] == "Feeder, north"  # quoted commas survive


# ---------------------------------------------------------------- what-changed report

def _act(task, crew, start, finish):
    return {"task_id": task, "crew_label": crew, "start_hour": start, "finish_hour": finish}


def test_diff_classifies_upstream_delay_and_crew_contention():
    deps = {"B": ["A"], "D": []}
    before = [_act("A", "C1", 0, 2), _act("B", "C1", 2, 4), _act("D", "C2", 0, 1)]
    # A now finishes at 3, so B is pushed; D waits for crew C2 after being ready at hour 0.
    after = [_act("A", "C1", 0, 3), _act("B", "C1", 3, 5), _act("D", "C2", 6, 7)]
    diff = diffing.diff_runs(before, after, deps)
    reasons = {t["task_id"]: t["reason"] for t in diff["tasks"]}
    assert reasons["B"] == "upstream_delay"
    assert reasons["A"] == "dispatch_reordered"  # A has no prerequisite; its own order changed
    assert reasons["D"] == "crew_contention"
    assert diff["summary"]["finished_later"] >= 2
    assert diff["summary"]["makespan_delta_hours"] == pytest.approx(7 - 4)


def test_diff_reports_dropped_added_and_earlier_tasks():
    before = [_act("A", "C1", 0, 4), _act("B", "C1", 4, 6)]
    after = [_act("A", "C1", 0, 2), _act("N", "C2", 0, 1)]
    diff = diffing.diff_runs(before, after, {})
    assert diff["summary"]["dropped_in_b"] == ["B"]
    assert diff["summary"]["added_in_b"] == ["N"]
    a = next(t for t in diff["tasks"] if t["task_id"] == "A")
    assert a["reason"] == "finished_earlier" and a["finish_delta_hours"] == -2


def test_identical_runs_have_no_changes():
    acts = [_act("A", "C1", 0, 2)]
    diff = diffing.diff_runs(acts, acts, {})
    assert diff["tasks"] == [] and diff["summary"]["changed_tasks"] == 0


# ---------------------------------------------------------------- analytics

def _frame(n=10, seed=1):
    rng = np.random.default_rng(seed)
    return pd.DataFrame([{"task_id": f"R{i}", "estimated_hours": float(rng.uniform(1, 6)),
                          "estimated_cost": float(rng.uniform(100, 900)),
                          "service_weight": float(rng.uniform(1, 10)), "priority": int(rng.integers(1, 6)),
                          "required_skill": "general"} for i in range(n)])


def test_make_crews_has_one_multiskill_crew_first():
    crews = make_crews(4)
    assert crews[0]["skill"] == "multi-skill"
    assert [c["crew_id"] for c in crews] == ["C1", "C2", "C3", "C4"]


def test_sweep_returns_every_combination():
    frame = _frame()
    grid = sweep(frame, {}, [1000, 3000], [1, 2])
    assert len(grid) == len(STRATEGIES) * 2 * 2
    assert set(grid.strategy) == set(STRATEGIES)


def test_robustness_is_seeded_and_intervals_are_ordered():
    frame = _frame()
    crews = make_crews(2)
    a = compare_strategies(frame, {}, 2000, crews, trials=40, noise=0.2, seed=99)
    b = compare_strategies(frame, {}, 2000, crews, trials=40, noise=0.2, seed=99)
    assert a == b  # same seed, same numbers
    for strategy in STRATEGIES:
        ci = a["strategies"][strategy]["makespan_hours"]
        assert ci["n"] == 40
        assert ci["ci95_low"] <= ci["mean"] <= ci["ci95_high"]


def test_no_noise_means_no_spread():
    result = compare_strategies(_frame(), {}, 2000, make_crews(2), trials=5, noise=0.0)
    for strategy in STRATEGIES:
        assert result["strategies"][strategy]["makespan_hours"]["std"] == pytest.approx(0.0)


def test_robustness_rejects_bad_parameters():
    with pytest.raises(ValueError):
        compare_strategies(_frame(), {}, 2000, make_crews(2), trials=1)
    with pytest.raises(ValueError):
        compare_strategies(_frame(), {}, 2000, make_crews(2), trials=10, noise=1.0)


# ---------------------------------------------------------------- report and logging

def test_markdown_report_contains_schedule_metrics_and_limitations():
    frame = _frame(4)
    deps = {"R1": ["R0"]}
    result = schedule_repairs(frame, "priority_first", 5000, make_crews(2), deps)
    actions = [{"task_id": a["task_id"], "crew_label": a["crew_id"], "start_hour": a["start_hour"],
                "finish_hour": a["finish_hour"]} for a in result["actions"]]
    run = {"run_id": 42, "strategy_name": "priority_first", "total_cost": result["total_cost"],
           "makespan_hours": result["makespan_hours"], "weighted_recovery_score": result["weighted_recovery_score"],
           "started_at": "2026-10-18T10:00:00+00:00"}
    scenario = {"scenario_name": "Test", "budget": 5000, "crew_count": 2}
    tasks = {r["task_id"]: r for r in frame.to_dict("records")}
    text = report.render_run_report(run, scenario, actions, tasks, deps)
    assert text.startswith("# Restoration run 42: Test")
    assert "| Metric | Value |" in text and "## Limitations" in text
    assert "synthetic" in text
    assert "Unscheduled tasks" in text


def test_json_log_lines_are_valid_json_with_extra_fields():
    record = logging.LogRecord("gridrestore", logging.INFO, __file__, 1, "request completed", None, None)
    record.request_id = "abc123"
    record.status = 200
    record.secret_field = "not logged"
    line = JsonFormatter().format(record)
    payload = json.loads(line)
    assert payload["message"] == "request completed"
    assert payload["request_id"] == "abc123" and payload["status"] == 200
    assert "secret_field" not in payload


# ---------------------------------------------------------------- tokens

@pytest.fixture
def secret(monkeypatch):
    monkeypatch.setenv("SESSION_SECRET", "unit-test-secret")


def test_token_round_trip_and_role_check(secret):
    token = auth.create_token("alice", "operator")
    session = auth.parse_token(token)
    assert session == {"username": "alice", "role": "operator"}
    with pytest.raises(PermissionError):
        auth.require_role(token, "admin")


def test_tampered_token_is_rejected(secret):
    token = auth.create_token("alice", "operator")
    raw = bytearray(__import__("base64").urlsafe_b64decode(token.encode()))
    raw[0] ^= 0x01  # flip one bit in the username
    forged = __import__("base64").urlsafe_b64encode(bytes(raw)).decode()
    assert auth.parse_token(forged) is None


def test_expired_token_is_rejected(secret, monkeypatch):
    token = auth.create_token("alice", "admin")
    monkeypatch.setattr(auth.time, "time", lambda: 10**12)
    assert auth.parse_token(token) is None


def test_missing_secret_is_an_error(monkeypatch):
    monkeypatch.delenv("SESSION_SECRET", raising=False)
    with pytest.raises(RuntimeError):
        auth.create_token("alice", "admin")


def test_unknown_role_in_token_is_rejected(secret):
    import base64, hashlib, hmac, time
    payload = f"mallory:superuser:{int(time.time())}"
    sig = hmac.new(b"unit-test-secret", payload.encode(), hashlib.sha256).hexdigest()
    token = base64.urlsafe_b64encode(f"{payload}:{sig}".encode()).decode()
    assert auth.parse_token(token) is None
