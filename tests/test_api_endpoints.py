"""API tests covering the remaining endpoints: auth errors, scheduling, dashboard, versions,
rollback, analytics and the figure/CSV writers. Database tests use their own scenario."""
import uuid

import pytest

from backend import analytics, versions
from backend.db import connect, delete_scenario, get_scenario_tasks

pytestmark = pytest.mark.db


@pytest.fixture(scope="module")
def client():
    import os
    os.environ.setdefault("SESSION_SECRET", "test-only-secret")
    from fastapi.testclient import TestClient
    from backend.api import app
    return TestClient(app)


@pytest.fixture(scope="module")
def auth(client):
    def _for(user="admin", password="admin123"):
        token = client.post("/api/login", json={"username": user, "password": password}).json()["token"]
        return {"Authorization": f"Bearer {token}"}
    return _for


@pytest.fixture
def scenario():
    prefix = "API" + uuid.uuid4().hex[:8]
    with connect() as conn:
        sid = conn.execute("INSERT INTO outage_scenarios(scenario_name,budget,crew_count) "
                           "VALUES (%s,%s,%s) RETURNING scenario_id",
                           (f"Api {prefix}", 5_000, 2)).fetchone()["scenario_id"]
        for i, (hours, cost, weight, skill) in enumerate([(2, 300, 5, "general"), (3, 400, 4, "electrical"),
                                                          (1, 200, 2, "general")]):
            conn.execute(
                "INSERT INTO repair_tasks(task_id,scenario_id,edge_id,component_name,estimated_hours,"
                "estimated_cost,service_weight,priority,required_skill,outage_cause) "
                "VALUES (%s,%s,'E1',%s,%s,%s,%s,2,%s,'storm')",
                (f"{prefix}-{i}", sid, f"Part {i}", hours, cost, weight, skill))
    yield {"sid": sid, "ids": [f"{prefix}-{i}" for i in range(3)]}
    delete_scenario(sid)


def test_missing_or_bad_token_is_401(client):
    assert client.get("/api/scenarios").status_code == 401
    assert client.get("/api/scenarios", headers={"Authorization": "Bearer nonsense"}).status_code == 403
    assert client.get("/health").json()["status"] == "ok"


def test_wrong_password_is_401(client):
    assert client.post("/api/login", json={"username": "admin", "password": "wrong"}).status_code == 401


def test_scenario_creation_copies_the_template_and_can_schedule(client, auth):
    name = "API clone " + uuid.uuid4().hex[:8]
    created = client.post("/api/scenarios", headers=auth(),
                          json={"name": name, "budget": 6_000, "crew_count": 2})
    assert created.status_code == 200
    scenario_id = created.json()["scenario_id"]
    try:
        tasks, dependencies = get_scenario_tasks(scenario_id)
        assert len(tasks) == 8
        ids = {task["task_id"] for task in tasks}
        assert ids == {f"S{scenario_id}-T{i:02d}" for i in range(1, 9)}
        assert dependencies and all(prereq in ids for prereqs in dependencies.values()
                                    for prereq in prereqs)
        run = client.post("/api/schedule", headers=auth("operator", "operator123"),
                          json={"scenario_id": scenario_id, "strategy": "gridrestore_score"})
        assert run.status_code == 200, run.text
        assert run.json()["actions"]
    finally:
        delete_scenario(scenario_id)


def test_operator_cannot_create_a_scenario(client, auth):
    response = client.post("/api/scenarios", headers=auth("operator", "operator123"),
                           json={"name": "Nope", "budget": 1000, "crew_count": 1})
    assert response.status_code == 403


def test_schedule_endpoint_saves_run_and_rejects_unknown_strategy(client, auth, scenario):
    ok = client.post("/api/schedule", headers=auth("operator", "operator123"),
                     json={"scenario_id": scenario["sid"], "strategy": "priority_first"})
    assert ok.status_code == 200 and ok.json()["run_id"] > 0
    bad = client.post("/api/schedule", headers=auth(),
                      json={"scenario_id": scenario["sid"], "strategy": "magic"})
    assert bad.status_code == 400
    missing = client.post("/api/schedule", headers=auth(), json={"scenario_id": 10**9})
    assert missing.status_code == 404


def test_runs_and_actions_endpoints(client, auth, scenario):
    run_id = client.post("/api/schedule", headers=auth(),
                         json={"scenario_id": scenario["sid"]}).json()["run_id"]
    runs = client.get(f"/api/runs?scenario_id={scenario['sid']}", headers=auth()).json()
    assert any(r["run_id"] == run_id for r in runs)
    actions = client.get(f"/api/runs/{run_id}/actions", headers=auth()).json()
    assert actions and {"task_id", "crew_label", "start_hour", "finish_hour"} <= set(actions[0])
    assert client.get("/api/runs/999999999/actions", headers=auth()).status_code == 404


def test_runs_diff_rejects_runs_from_different_scenarios(client, auth, scenario):
    first = client.post("/api/schedule", headers=auth(), json={"scenario_id": scenario["sid"]}).json()["run_id"]
    other = client.post("/api/schedule", headers=auth(), json={"scenario_id": 1}).json()["run_id"]
    response = client.get(f"/api/runs/diff?a={first}&b={other}", headers=auth())
    assert response.status_code == 400 and "same scenario" in response.json()["detail"]


def test_versions_list_read_and_rollback_endpoints(client, auth, scenario):
    edit = client.patch(f"/api/scenarios/{scenario['sid']}/tasks", headers=auth(), json={
        "updates": [{"task_id": scenario["ids"][0], "estimated_hours": 9}]})
    assert edit.status_code == 200 and edit.json()["version_no"] == 2
    listing = client.get(f"/api/scenarios/{scenario['sid']}/versions", headers=auth()).json()
    assert [v["version_no"] for v in listing] == [2, 1]
    one = client.get(f"/api/scenarios/{scenario['sid']}/versions/1", headers=auth()).json()
    assert len(one["snapshot"]["tasks"]) == 3
    assert client.get(f"/api/scenarios/{scenario['sid']}/versions/99", headers=auth()).status_code == 404
    restored = client.post(f"/api/scenarios/{scenario['sid']}/rollback", headers=auth(),
                           json={"version_no": 1, "note": "undo"})
    assert restored.status_code == 200 and restored.json()["version_no"] == 3
    assert client.post(f"/api/scenarios/{scenario['sid']}/rollback", headers=auth("operator", "operator123"),
                       json={"version_no": 1}).status_code == 403


def test_edit_rejects_unknown_fields_and_bad_values(client, auth, scenario):
    # Pydantic rejects out-of-range values before the database is touched.
    bad = client.patch(f"/api/scenarios/{scenario['sid']}/tasks", headers=auth(),
                       json={"updates": [{"task_id": scenario["ids"][0], "priority": 12}]})
    assert bad.status_code == 422 and "request_id" in bad.json()
    other_task = client.patch(f"/api/scenarios/{scenario['sid']}/tasks", headers=auth(),
                              json={"updates": [{"task_id": "NOT-A-TASK", "estimated_hours": 1}]})
    assert other_task.status_code == 400 and "not part of scenario" in other_task.json()["detail"]


def test_dashboard_endpoints(client, auth):
    stats = client.get("/api/dashboard/run-stats?mode=materialized", headers=auth("operator", "operator123"))
    assert stats.status_code == 200 and set(stats.json()["freshness"]) == {"live_runs", "materialized_runs", "stale"}
    live = client.get("/api/dashboard/run-stats?mode=live", headers=auth())
    assert live.status_code == 200 and live.json()["mode"] == "live"
    assert client.get("/api/dashboard/run-stats?mode=nope", headers=auth()).status_code == 400
    refresh = client.post("/api/dashboard/refresh", headers=auth())
    assert refresh.status_code == 200 and refresh.json()["refreshed"] is True
    assert client.post("/api/dashboard/refresh", headers=auth("operator", "operator123")).status_code == 403


def test_audit_filter_validation_through_api(client, auth):
    assert client.get("/api/audit?table_name=pg_user", headers=auth()).status_code == 400
    assert client.get("/api/audit?limit=0", headers=auth()).status_code == 422


def test_sweep_endpoint(client, auth, scenario):
    response = client.post("/api/analytics/sweep", headers=auth("operator", "operator123"), json={
        "scenario_id": scenario["sid"], "budgets": [1000, 4000], "crew_counts": [1, 2]})
    assert response.status_code == 200 and len(response.json()) == 3 * 2 * 2
    bad = client.post("/api/analytics/sweep", headers=auth(), json={
        "scenario_id": scenario["sid"], "budgets": [1000], "crew_counts": [25]})
    assert bad.status_code == 400


def test_scenario_critical_endpoints(client, auth):
    assert client.get("/api/scenarios/1/critical-repairs", headers=auth()).status_code == 200
    assert client.get("/api/scenarios/1/skill-gaps", headers=auth()).status_code == 200


def test_csv_import_commit_path_through_api(client, auth, scenario):
    new_id = f"{scenario['ids'][0]}X"
    body = ("task_id,edge_id,component_name,estimated_hours,estimated_cost,service_weight,priority\n"
            f"{new_id},E1,Imported,1,10,1,1\n")
    good = client.post(f"/api/scenarios/{scenario['sid']}/tasks/import", headers=auth(),
                       json={"csv": body, "commit": True, "note": "api import"})
    assert good.status_code == 200 and good.json()["committed"] is True and good.json()["inserted"] == 1
    again = client.post(f"/api/scenarios/{scenario['sid']}/tasks/import", headers=auth(),
                        json={"csv": body, "commit": True})
    assert again.json()["committed"] is False and "already exists" in str(again.json()["errors"])
    assert client.post(f"/api/scenarios/{scenario['sid']}/tasks/import", headers=auth("operator", "operator123"),
                       json={"csv": body}).status_code == 403


def test_write_outputs_creates_csv_and_figure(tmp_path):
    import pandas as pd
    frame = pd.DataFrame([{"task_id": f"R{i}", "estimated_hours": 1.0 + i, "estimated_cost": 100.0 * (i + 1),
                           "service_weight": float(i + 1), "priority": 2, "required_skill": "general"}
                          for i in range(6)])
    grid = analytics.write_outputs(frame, {}, out_dir=str(tmp_path / "figs"), csv_dir=str(tmp_path))
    assert (tmp_path / "sweep_results.csv").exists()
    assert (tmp_path / "figs" / "sweep_budget_crews.png").exists()
    assert len(grid) > 0


def test_grid_view_marks_blocked_tasks_and_edges(client, auth, scenario):
    # Before any run, nothing is scheduled: the dependent task is blocked by its unscheduled prerequisite.
    before = client.get(f"/api/scenarios/{scenario['sid']}/grid", headers=auth()).json()
    assert before["latest_run_id"] is None
    assert before["task_status"][scenario["ids"][0]] == "unscheduled"
    # After a run that skips the prerequisite task, nothing depending on it can run.
    with connect() as conn:
        conn.execute("INSERT INTO task_dependencies VALUES (%s,%s) ON CONFLICT DO NOTHING",
                     (scenario["ids"][1], scenario["ids"][0]))
    grid = client.get(f"/api/scenarios/{scenario['sid']}/grid", headers=auth()).json()
    assert grid["nodes"] and grid["edges"]
    assert grid["task_status"][scenario["ids"][1]] == "blocked"
    assert scenario["ids"][1] in grid["blocked_task_ids"]
    # The fixture puts every task on edge E1, so that edge is marked blocked.
    assert any(e["edge_id"] == "E1" and e["status"] == "blocked" for e in grid["edges"])
