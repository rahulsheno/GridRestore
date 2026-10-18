import pandas as pd
import pytest
from backend.scheduler import schedule_repairs

@pytest.fixture
def tasks():
    return pd.DataFrame([
      {"task_id":"A","estimated_hours":2.0,"estimated_cost":100,"service_weight":8,"priority":1,"required_skill":"electrical"},
      {"task_id":"B","estimated_hours":1.0,"estimated_cost":50,"service_weight":3,"priority":3,"required_skill":"general"},
      {"task_id":"C","estimated_hours":2.0,"estimated_cost":70,"service_weight":10,"priority":1,"required_skill":"electrical"},
    ])

def crews():
    return [{"crew_id":"C1","skill":"electrical"},{"crew_id":"C2","skill":"general"}]

def test_budget_and_schedule_integrity(tasks):
    result=schedule_repairs(tasks,"priority_first",180,crews())
    assert result["total_cost"] <= 180
    assert result["scheduled_count"] == len(result["actions"])
    assert all(a["finish_hour"] > a["start_hour"] for a in result["actions"])

def test_dependency_is_respected(tasks):
    result=schedule_repairs(tasks,"shortest_repair_first",500,crews(),{"C":["A"]})
    by_id={a["task_id"]:a for a in result["actions"]}
    assert by_id["A"]["finish_hour"] <= by_id["C"]["start_hour"]

def test_skill_constraint(tasks):
    result=schedule_repairs(tasks,"gridrestore_score",500,[{"crew_id":"C1","skill":"general"}])
    scheduled_ids = {a["task_id"] for a in result["actions"]}
    assert "A" not in scheduled_ids
    assert "C" not in scheduled_ids

def test_prerequisite_finish_before_dependent_start(tasks):
    crews = [{"crew_id": "C1", "skill": "electrical"}, {"crew_id": "C2", "skill": "general"}]
    result = schedule_repairs(tasks, "priority_first", 500, crews, {"C": ["A"]})
    by_id = {a["task_id"]: a for a in result["actions"]}
    assert by_id["A"]["finish_hour"] <= by_id["C"]["start_hour"]

def test_multi_skill_crew_can_cover_specialty(tasks):
    result = schedule_repairs(tasks, "priority_first", 500, [{"crew_id": "C1", "skill": "multi-skill"}])
    assert result["scheduled_count"] == 3

def test_budget_never_exceeded(tasks):
    result = schedule_repairs(tasks, "priority_first", 100, crews())
    assert result["total_cost"] <= 100
    assert {a["task_id"] for a in result["actions"]} != {"A", "B", "C"}

def test_dependency_cycle_rejected(tasks):
    with pytest.raises(ValueError,match="cycle"):
        schedule_repairs(tasks,"priority_first",500,crews(),{"A":["C"],"C":["A"]})

def test_unknown_strategy_rejected(tasks):
    with pytest.raises(ValueError,match="Unknown strategy"):
        schedule_repairs(tasks,"magic",500,crews())

def test_embedding_is_deterministic_and_normalized():
    from backend.vectors import embed_text
    first, second = embed_text("Hospital branch emergency repair"), embed_text("Hospital branch emergency repair")
    assert first == second
    assert len(first) == 32
    assert abs(sum(v * v for v in first) - 1.0) < 1e-6

def test_vector_search_returns_ranked_results():
    from backend.vectors import embed_text
    import math
    # Hermetic ranking check on the 8 demo narratives (no DB): cosine order
    # must be sorted and a hospital query must surface T02/T07 near the top.
    from backend.vectors import NARRATIVES
    query = embed_text("hospital emergency power repair")
    def cosine(a, b):
        return sum(x * y for x, y in zip(a, b))
    ranked = sorted(NARRATIVES, key=lambda t: -cosine(query, embed_text(NARRATIVES[t])))
    assert set(ranked[:4]) & {"T02", "T07"}
    # Live DB check: results come back distance-ordered.
    from backend.vectors import find_similar_repairs
    rows = find_similar_repairs("hospital emergency power repair", limit=3)
    assert len(rows) == 3
    distances = [float(r["distance"]) for r in rows]
    assert distances == sorted(distances)

def test_full_text_search_finds_hospital():
    from backend.vectors import full_text_search_repairs
    rows = full_text_search_repairs("hospital", limit=5)
    assert {r["task_id"] for r in rows} >= {"T02", "T07"}

def test_auth_rejects_wrong_password():
    from backend.auth import authenticate, parse_token
    assert authenticate("admin", "wrong-password") is None
    good = authenticate("admin", "admin123")
    assert good and good["role"] == "admin"
    assert parse_token(good["token"])["username"] == "admin"

def test_operator_cannot_use_admin_role():
    from backend.auth import create_token, require_role
    import pytest as _pytest
    token = create_token("operator", "operator")
    with _pytest.raises(PermissionError):
        require_role(token, "admin")
    assert require_role(token, "admin", "operator")["role"] == "operator"

def test_api_login_and_guard():
    from fastapi.testclient import TestClient
    from backend.api import app
    client = TestClient(app)
    assert client.get("/api/scenarios").status_code == 401
    login = client.post("/api/login", json={"username": "admin", "password": "admin123"})
    assert login.status_code == 200
    token = login.json()["token"]
    assert client.get("/api/scenarios", headers={"Authorization": f"Bearer {token}"}).status_code == 200
    bad = client.post("/api/login", json={"username": "admin", "password": "nope"})
    assert bad.status_code == 401

def test_critical_repairs_ranking():
    from backend.criticality import critical_repairs
    rows = critical_repairs(1)
    assert len(rows) == 8
    top = {r["task_id"] for r in rows[:2]}
    assert top == {"T07", "T03"}
    assert all(rows[i]["unblocks_count"] >= rows[i + 1]["unblocks_count"]
               for i in range(len(rows) - 1))

def test_critical_path_chain_and_floor():
    from backend.criticality import critical_path
    result = critical_path(1)
    assert result["makespan_floor_hours"] == 10.0
    assert result["critical_chain"] == ["T03", "T05"]
    by_id = {t["task_id"]: t for t in result["tasks"]}
    assert by_id["T03"]["slack"] == 0 and by_id["T05"]["slack"] == 0
    assert by_id["T02"]["slack"] > 0

def test_api_critical_endpoints():
    from fastapi.testclient import TestClient
    from backend.api import app
    client = TestClient(app)
    token = client.post("/api/login", json={"username": "operator", "password": "operator123"}).json()["token"]
    headers = {"Authorization": f"Bearer {token}"}
    crit = client.get("/api/scenarios/1/critical-repairs", headers=headers)
    assert crit.status_code == 200 and crit.json()[0]["task_id"] in ("T07", "T03")
    path = client.get("/api/scenarios/1/critical-path", headers=headers)
    assert path.status_code == 200 and path.json()["critical_chain"] == ["T03", "T05"]

def test_skill_gaps_covered_and_gap_case():
    from backend.criticality import skill_gaps
    ok_result = skill_gaps(1)
    assert ok_result["gaps"] == [] and "OK" in ok_result["verdict"]
    gap_result = skill_gaps(1, crews=[{"crew_id": "C9", "skill": "general"}])
    assert gap_result["gaps"] == ["electrical"] and "GAP" in gap_result["verdict"]

def test_cause_breakdown_endpoint():
    from fastapi.testclient import TestClient
    from backend.api import app
    client = TestClient(app)
    token = client.post("/api/login", json={"username": "admin", "password": "admin123"}).json()["token"]
    rows = client.get("/api/scenarios/1/cause-breakdown",
                      headers={"Authorization": f"Bearer {token}"}).json()
    causes = {r["outage_cause"] for r in rows}
    assert causes >= {"storm", "vegetation", "equipment_age", "vehicle_impact"}
    assert sum(r["task_count"] for r in rows) == 8
