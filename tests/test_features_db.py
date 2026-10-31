"""Database and API tests for the new features. They need PostgreSQL (marker `db`).

Each test builds its own scenario with a unique prefix and deletes it afterwards, so the demo
scenario that other tests rely on is never modified.
"""
import uuid

import psycopg
import pytest

from backend import audit_dashboard, tasks_io, versions
from backend.db import connect, delete_scenario, save_run

pytestmark = pytest.mark.db


@pytest.fixture
def scenario():
    """A scenario with three tasks: T_B depends on T_A, T_C is independent."""
    prefix = "TST" + uuid.uuid4().hex[:8]
    with connect() as conn:
        sid = conn.execute("INSERT INTO outage_scenarios(scenario_name,budget,crew_count) "
                           "VALUES (%s,%s,%s) RETURNING scenario_id",
                           (f"Test {prefix}", 10_000, 2)).fetchone()["scenario_id"]
        for name, hours, cost, weight in [("A", 2, 100, 5), ("B", 3, 200, 4), ("C", 1, 50, 2)]:
            conn.execute(
                "INSERT INTO repair_tasks(task_id,scenario_id,edge_id,component_name,estimated_hours,"
                "estimated_cost,service_weight,priority,required_skill,outage_cause) "
                "VALUES (%s,%s,'E1',%s,%s,%s,%s,2,'general','storm')",
                (f"{prefix}-{name}", sid, f"Component {name}", hours, cost, weight))
        conn.execute("INSERT INTO task_dependencies VALUES (%s,%s)", (f"{prefix}-B", f"{prefix}-A"))
    yield {"sid": sid, "prefix": prefix, "a": f"{prefix}-A", "b": f"{prefix}-B", "c": f"{prefix}-C"}
    delete_scenario(sid)


# ---------------------------------------------------------------- crew overlap constraint

def _run_with_actions(sid, actions):
    result = {"strategy": "priority_first", "total_cost": 0.0, "makespan_hours": 0.0,
              "weighted_recovery_score": 0.0, "actions": []}
    total = 0.0
    for task, crew, start, finish in actions:
        result["actions"].append({"task_id": task, "crew_id": crew, "start_hour": start,
                                  "finish_hour": finish, "estimated_cost": 10.0, "service_weight": 1.0})
        total += 10.0
    result["total_cost"] = total
    return save_run(sid, result, username="tester")


def test_crew_cannot_be_double_booked_in_one_run(scenario):
    with pytest.raises(ValueError, match="double-booked"):
        _run_with_actions(scenario["sid"], [(scenario["a"], "K1", 0, 3), (scenario["c"], "K1", 2, 4)])


def test_touching_windows_and_other_crews_are_allowed(scenario):
    run_id = _run_with_actions(scenario["sid"], [
        (scenario["a"], "K1", 0, 2), (scenario["c"], "K1", 2, 3),   # touching: [0,2) and [2,3)
        (scenario["b"], "K2", 0, 3)])                              # different crew overlaps in time
    assert run_id > 0


def test_same_crew_in_different_runs_is_allowed(scenario):
    _run_with_actions(scenario["sid"], [(scenario["a"], "K9", 0, 3)])
    _run_with_actions(scenario["sid"], [(scenario["a"], "K9", 0, 3)])


def test_database_rejects_overlap_even_without_the_python_check(scenario):
    with connect() as conn:
        run_id = conn.execute("INSERT INTO restoration_runs(scenario_id,strategy_name,total_cost,makespan_hours,"
                              "weighted_recovery_score) VALUES (%s,'manual',0,0,0) RETURNING run_id",
                              (scenario["sid"],)).fetchone()["run_id"]
        conn.execute("INSERT INTO scheduled_actions(run_id,task_id,crew_label,start_hour,finish_hour) "
                     "VALUES (%s,%s,'K1',0,5)", (run_id, scenario["a"]))
    with connect() as conn:
        with pytest.raises(psycopg.errors.ExclusionViolation):
            conn.execute("INSERT INTO scheduled_actions(run_id,task_id,crew_label,start_hour,finish_hour) "
                         "VALUES (%s,%s,'K1',4,6)", (run_id, scenario["c"]))


# ---------------------------------------------------------------- audit

def test_scenario_update_is_audited_with_old_new_and_app_user(scenario):
    with connect() as conn:
        conn.execute("SELECT set_config('app.username', 'auditor', true)")
        conn.execute("UPDATE outage_scenarios SET scenario_name=scenario_name||' edited' "
                     "WHERE scenario_id=%s", (scenario["sid"],))
    history = audit_dashboard.query_audit(table_name="outage_scenarios", row_key=str(scenario["sid"]),
                                          operation="UPDATE", include_data=True)
    assert history["total"] >= 1
    entry = history["items"][0]
    assert entry["app_user"] == "auditor"
    assert entry["old_data"]["scenario_name"] != entry["new_data"]["scenario_name"]


def test_run_inserts_and_deletes_are_audited(scenario):
    run_id = _run_with_actions(scenario["sid"], [(scenario["a"], "K1", 0, 2)])
    with connect() as conn:
        conn.execute("DELETE FROM restoration_runs WHERE run_id=%s", (run_id,))
    ops = {e["operation"] for e in audit_dashboard.query_audit(
        table_name="restoration_runs", row_key=str(run_id))["items"]}
    assert ops == {"INSERT", "DELETE"}


def test_audit_filters_combine_and_paginate(scenario):
    for _ in range(3):
        with connect() as conn:
            conn.execute("SELECT set_config('app.username', 'paginator', true)")
            conn.execute("UPDATE repair_tasks SET priority=3 WHERE task_id=%s", (scenario["c"],))
            conn.execute("UPDATE repair_tasks SET priority=2 WHERE task_id=%s", (scenario["c"],))
    everything = audit_dashboard.query_audit(table_name="repair_tasks", row_key=scenario["c"],
                                             app_user="paginator", limit=2)
    assert everything["total"] >= 6 and len(everything["items"]) == 2
    second = audit_dashboard.query_audit(table_name="repair_tasks", row_key=scenario["c"],
                                         app_user="paginator", limit=2, offset=2)
    assert {i["audit_id"] for i in second["items"]}.isdisjoint({i["audit_id"] for i in everything["items"]})


def test_audit_rejects_unknown_filters():
    with pytest.raises(ValueError):
        audit_dashboard.query_audit(table_name="pg_user")
    with pytest.raises(ValueError):
        audit_dashboard.query_audit(operation="TRUNCATE")
    with pytest.raises(ValueError):
        audit_dashboard.query_audit(limit=10_000)


# ---------------------------------------------------------------- scenario versioning

def test_first_edit_stores_baseline_and_new_version(scenario):
    number = versions.apply_changes(scenario["sid"], "alice", "raise hours on A",
                                    updates=[{"task_id": scenario["a"], "estimated_hours": 5.0}])
    assert number == 2
    listing = versions.list_versions(scenario["sid"])
    assert [v["version_no"] for v in listing] == [2, 1]
    diff = versions.diff_snapshots(versions.get_version(scenario["sid"], 1),
                                   versions.get_version(scenario["sid"], 2))
    assert diff["fields_changed"] == [{"task_id": scenario["a"], "field": "estimated_hours",
                                       "from": 2.0, "to": 5.0}]


def test_cycle_is_rejected_and_nothing_is_partially_applied(scenario):
    with pytest.raises(ValueError, match="cycle"):
        versions.apply_changes(scenario["sid"], "alice", "bad", updates=[
            {"task_id": scenario["c"], "estimated_hours": 9.0},              # would be applied first
            {"task_id": scenario["a"], "depends_on": [scenario["b"]]}])      # A <-> B cycle
    assert len(versions.list_versions(scenario["sid"])) == 0
    with connect() as conn:
        hours = conn.execute("SELECT estimated_hours FROM repair_tasks WHERE task_id=%s",
                             (scenario["c"],)).fetchone()["estimated_hours"]
    assert float(hours) == 1.0


def test_prerequisite_from_another_scenario_is_rejected(scenario):
    with connect() as conn:
        other = conn.execute("SELECT task_id FROM repair_tasks WHERE scenario_id<>%s LIMIT 1",
                             (scenario["sid"],)).fetchone()["task_id"]
    with pytest.raises(ValueError, match="not part of scenario"):
        versions.apply_changes(scenario["sid"], "alice", "x",
                               updates=[{"task_id": scenario["c"], "depends_on": [other]}])


def test_rollback_restores_values_and_dependencies_and_keeps_history(scenario):
    versions.apply_changes(scenario["sid"], "alice", "step 1",
                           updates=[{"task_id": scenario["a"], "estimated_hours": 7.0}])
    versions.apply_changes(scenario["sid"], "alice", "step 2",
                           updates=[{"task_id": scenario["b"], "depends_on": []}])
    restored = versions.rollback(scenario["sid"], 1, "bob")
    assert restored == 4  # baseline 1, step 1 = 2, step 2 = 3, rollback = 4
    with connect() as conn:
        a = conn.execute("SELECT estimated_hours FROM repair_tasks WHERE task_id=%s",
                         (scenario["a"],)).fetchone()["estimated_hours"]
        deps = conn.execute("SELECT COUNT(*) AS n FROM task_dependencies WHERE task_id=%s",
                            (scenario["b"],)).fetchone()["n"]
    assert float(a) == 2.0 and deps == 1
    assert len(versions.list_versions(scenario["sid"])) == 4


def test_rollback_removes_tasks_added_later_when_no_run_uses_them(scenario):
    versions.apply_changes(scenario["sid"], "alice", "add task", inserts=[
        {"task_id": f"{scenario['prefix']}-N", "edge_id": "E1", "component_name": "New", "estimated_hours": 1.0,
         "estimated_cost": 10.0, "service_weight": 1.0, "priority": 3, "region_code": "Unassigned",
         "required_skill": "general", "outage_cause": "unknown", "depends_on": [scenario["c"]]}])
    versions.rollback(scenario["sid"], 1, "bob")
    with connect() as conn:
        n = conn.execute("SELECT COUNT(*) AS n FROM repair_tasks WHERE scenario_id=%s", (scenario["sid"],)).fetchone()["n"]
    assert n == 3


def test_rollback_fails_cleanly_when_a_saved_run_uses_the_removed_task(scenario):
    versions.apply_changes(scenario["sid"], "alice", "add task", inserts=[
        {"task_id": f"{scenario['prefix']}-N", "edge_id": "E1", "component_name": "New", "estimated_hours": 1.0,
         "estimated_cost": 10.0, "service_weight": 1.0, "priority": 3, "region_code": "Unassigned",
         "required_skill": "general", "outage_cause": "unknown", "depends_on": []}])
    _run_with_actions(scenario["sid"], [(f"{scenario['prefix']}-N", "K1", 0, 1)])
    with pytest.raises(ValueError, match="saved run"):
        versions.rollback(scenario["sid"], 1, "bob")
    assert len(versions.list_versions(scenario["sid"])) == 2  # the failed rollback left no trace


# ---------------------------------------------------------------- CSV import

def test_import_is_all_or_nothing_and_commits_as_one_version(scenario):
    edges, global_ids, scenario_ids = tasks_io.load_reference_ids(scenario["sid"])
    good = (f"task_id,edge_id,component_name,estimated_hours,estimated_cost,service_weight,priority,depends_on\n"
            f"{scenario['prefix']}-X1,E1,Imported A,2,100,3,2,\n"
            f"{scenario['prefix']}-X2,E1,Imported B,2,100,3,2,{scenario['prefix']}-X1\n")
    result = tasks_io.validate_task_csv(good, edges, global_ids, scenario_ids)
    assert result["valid"], result["errors"]
    number = versions.apply_changes(scenario["sid"], "alice", "csv", inserts=result["rows"])
    assert number == 2
    with connect() as conn:
        deps = conn.execute("SELECT COUNT(*) AS n FROM task_dependencies WHERE task_id=%s",
                            (f"{scenario['prefix']}-X2",)).fetchone()["n"]
    assert deps == 1


# ---------------------------------------------------------------- materialized view

def test_materialized_view_reports_staleness_until_refreshed(scenario):
    audit_dashboard.refresh_run_stats()
    assert audit_dashboard.stats_freshness()["stale"] is False
    _run_with_actions(scenario["sid"], [(scenario["a"], "K1", 0, 2)])
    assert audit_dashboard.stats_freshness()["stale"] is True
    audit_dashboard.refresh_run_stats()
    assert audit_dashboard.stats_freshness()["stale"] is False


def test_live_and_materialized_stats_agree_after_refresh():
    audit_dashboard.refresh_run_stats()
    live = {(r["scenario_id"], r["strategy_name"]): r for r in audit_dashboard.run_stats("live")}
    mat = {(r["scenario_id"], r["strategy_name"]): r for r in audit_dashboard.run_stats("materialized")}
    assert live.keys() == mat.keys()
    for key in live:
        assert live[key]["run_count"] == mat[key]["run_count"]
        assert live[key]["scheduled_actions"] == mat[key]["scheduled_actions"]


# ---------------------------------------------------------------- API: roles, docs, errors

@pytest.fixture(scope="module")
def client():
    import os
    os.environ.setdefault("SESSION_SECRET", "test-only-secret")
    from fastapi.testclient import TestClient
    from backend.api import app
    return TestClient(app)


def _token(client, user, password):
    return client.post("/api/login", json={"username": user, "password": password}).json()["token"]


def _auth(client, user="admin", password="admin123"):
    return {"Authorization": f"Bearer {_token(client, user, password)}"}


def test_operator_gets_a_clear_403_for_admin_actions(client, scenario):
    headers = _auth(client, "operator", "operator123")
    response = client.patch(f"/api/scenarios/{scenario['sid']}/tasks", headers=headers,
                            json={"updates": [{"task_id": scenario["a"], "estimated_hours": 3}]})
    assert response.status_code == 403
    assert "admin role" in response.json()["detail"]
    assert client.get("/api/audit", headers=headers).status_code == 403


def test_validation_errors_are_structured_with_request_id(client):
    response = client.post("/api/login", json={"username": ""})
    assert response.status_code == 422
    assert response.headers["X-Request-ID"] and response.json()["request_id"]


def test_api_docs_render_and_every_operation_is_described(client):
    assert client.get("/docs").status_code == 200
    spec = client.get("/openapi.json").json()
    missing = []
    for path, methods in spec["paths"].items():
        for method, op in methods.items():
            if not op.get("summary") or not op.get("tags"):
                missing.append(f"{method.upper()} {path}")
    assert missing == []


def test_csv_export_and_import_through_the_api(client, scenario):
    headers = _auth(client)
    export = client.get(f"/api/scenarios/{scenario['sid']}/tasks.csv", headers=headers)
    assert export.status_code == 200 and export.text.startswith("task_id,edge_id")
    bad = client.post(f"/api/scenarios/{scenario['sid']}/tasks/import", headers=headers,
                      json={"csv": "task_id,edge_id,component_name,estimated_hours,estimated_cost,"
                                   "service_weight,priority\nZ1,NOPE,x,1,1,1,9\n", "commit": True})
    body = bad.json()
    assert bad.status_code == 200 and body["committed"] is False and body["valid"] is False
    assert {e["column"] for e in body["errors"]} >= {"edge_id", "priority"}


def test_version_edit_and_diff_through_the_api(client, scenario):
    headers = _auth(client)
    edit = client.patch(f"/api/scenarios/{scenario['sid']}/tasks", headers=headers, json={
        "note": "api edit", "updates": [{"task_id": scenario["c"], "service_weight": 9.5}]})
    assert edit.status_code == 200
    version = edit.json()["version_no"]
    diff = client.get(f"/api/scenarios/{scenario['sid']}/versions/diff?from={version - 1}&to={version}",
                      headers=headers).json()
    assert diff["fields_changed"][0]["field"] == "service_weight"


def test_run_diff_and_report_through_the_api(client, scenario):
    headers = _auth(client)
    first = _run_with_actions(scenario["sid"], [(scenario["a"], "K1", 0, 2), (scenario["b"], "K1", 2, 5)])
    second = _run_with_actions(scenario["sid"], [(scenario["a"], "K1", 0, 3), (scenario["b"], "K1", 3, 6)])
    diff = client.get(f"/api/runs/diff?a={first}&b={second}", headers=headers)
    assert diff.status_code == 200
    reasons = {t["task_id"]: t["reason"] for t in diff.json()["tasks"]}
    assert reasons[scenario["b"]] == "upstream_delay"
    report_text = client.get(f"/api/runs/{second}/report.md", headers=headers)
    assert report_text.status_code == 200 and f"# Restoration run {second}" in report_text.text


def test_audit_endpoint_for_admin(client, scenario):
    response = client.get(f"/api/audit?table_name=outage_scenarios&limit=5", headers=_auth(client))
    assert response.status_code == 200
    assert set(response.json()) == {"total", "limit", "offset", "items"}


def test_robustness_and_exact_gap_endpoints(client, scenario):
    headers = _auth(client, "operator", "operator123")
    rob = client.post("/api/analytics/robustness", headers=headers,
                      json={"scenario_id": scenario["sid"], "trials": 20, "noise": 0.1})
    assert rob.status_code == 200 and set(rob.json()["strategies"]) == {
        "priority_first", "shortest_repair_first", "gridrestore_score"}
    gap = client.post("/api/analytics/exact-gap", headers=headers,
                      json={"scenario_id": scenario["sid"], "horizon_hours": 4.0})
    assert gap.status_code == 200 and len(gap.json()["results"]) == 3


def test_exact_gap_refuses_large_scenarios(client):
    headers = _auth(client)
    response = client.post("/api/analytics/exact-gap", headers=headers,
                           json={"scenario_id": 1, "horizon_hours": 10})
    # The demo scenario has 8 tasks, so it is allowed; a 500-task scenario must be refused.
    assert response.status_code == 200
    with connect() as conn:
        big = conn.execute("SELECT scenario_id FROM outage_scenarios WHERE scenario_name='Bench S01'").fetchone()
    if big:
        refused = client.post("/api/analytics/exact-gap", headers=headers,
                              json={"scenario_id": big["scenario_id"], "horizon_hours": 10})
        assert refused.status_code == 400 and "12 tasks" in refused.json()["detail"]
