"""FastAPI backend for the Next.js frontend: auth + scheduling + vectors."""
import os
import pandas as pd
from fastapi import FastAPI, HTTPException, Header
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from dotenv import load_dotenv

from .db import (health_check, list_scenarios, create_scenario, list_runs,
                 get_scenario_tasks, save_run, list_run_actions)
from .scheduler import schedule_repairs, STRATEGIES
from .auth import authenticate, require_role
from .vectors import seed_embeddings, find_similar_repairs, full_text_search_repairs
from .criticality import critical_repairs, critical_path, skill_gaps

load_dotenv()
app = FastAPI(title="GridRestore API", version="1.0.0",
              description="Synthetic restoration planner: SQL + pgvector, role-based access.")
app.add_middleware(CORSMiddleware, allow_origins=["http://localhost:3000"],
                   allow_credentials=True, allow_methods=["*"], allow_headers=["*"])

def session(authorization: str = ""):
    if not authorization.startswith("Bearer "):
        raise HTTPException(401, "Missing bearer token")
    try:
        return require_role(authorization[7:], "admin", "operator")
    except PermissionError:
        raise HTTPException(403, "Not authorized")

def admin_only(authorization: str = ""):
    if not authorization.startswith("Bearer "):
        raise HTTPException(401, "Missing bearer token")
    try:
        return require_role(authorization[7:], "admin")
    except PermissionError:
        raise HTTPException(403, "Admin role required")

class LoginBody(BaseModel):
    username: str = Field(min_length=1)
    password: str = Field(min_length=1)

class ScenarioBody(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    budget: float = Field(gt=0)
    crew_count: int = Field(ge=1, le=20)

class ScheduleBody(BaseModel):
    scenario_id: int
    strategy: str = "gridrestore_score"
    crews: list = Field(default=[{"crew_id": "C1", "skill": "multi-skill"},
                                 {"crew_id": "C2", "skill": "general"},
                                 {"crew_id": "C3", "skill": "general"}])

class SearchBody(BaseModel):
    query: str = Field(min_length=1)
    mode: str = "vector"
    limit: int = Field(default=5, ge=1, le=20)

@app.get("/health")
def health():
    try:
        info = health_check()
        return {"status": "ok", "database": info["database"]}
    except Exception as exc:
        raise HTTPException(503, str(exc))

@app.post("/api/login")
def login(body: LoginBody):
    result = authenticate(body.username, body.password)
    if not result:
        raise HTTPException(401, "Invalid credentials")
    return result

@app.get("/api/scenarios")
def scenarios(authorization: str = Header(default="")):
    session(authorization)
    return [dict(r) for r in list_scenarios()]

@app.post("/api/scenarios")
def create(body: ScenarioBody, authorization: str = Header(default="")):
    admin_only(authorization)
    try:
        return dict(create_scenario(body.name, body.budget, body.crew_count))
    except ValueError as exc:
        raise HTTPException(400, str(exc))

@app.post("/api/schedule")
def schedule(body: ScheduleBody, authorization: str = Header(default="")):
    session(authorization)
    if body.strategy not in STRATEGIES:
        raise HTTPException(400, f"Unknown strategy: {body.strategy}")
    scenarios = {s["scenario_id"]: s for s in list_scenarios()}
    if body.scenario_id not in scenarios:
        raise HTTPException(404, "Scenario not found")
    scenario = scenarios[body.scenario_id]
    rows, deps = get_scenario_tasks(body.scenario_id)
    if not rows:
        raise HTTPException(400, "No repair_tasks for this scenario")
    result = schedule_repairs(pd.DataFrame(rows), body.strategy,
                              float(scenario["budget"]), body.crews, deps)
    try:
        run_id = save_run(body.scenario_id, result,
                          notes={"strategy": body.strategy, "crews": body.crews})
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    return {"run_id": run_id, **result, "unscheduled_task_ids": result["unscheduled_task_ids"]}

@app.get("/api/runs")
def runs(scenario_id: int = None, authorization: str = Header(default="")):
    session(authorization)
    return [dict(r) for r in list_runs(scenario_id)]

@app.get("/api/runs/{run_id}/actions")
def actions(run_id: int, authorization: str = Header(default="")):
    session(authorization)
    return [dict(r) for r in list_run_actions(run_id)]

@app.post("/api/search")
def search(body: SearchBody, authorization: str = Header(default="")):
    session(authorization)
    try:
        if body.mode == "fts":
            rows = full_text_search_repairs(body.query, body.limit)
        else:
            rows = find_similar_repairs(body.query, body.limit)
        return [dict(r) for r in rows]
    except Exception as exc:
        raise HTTPException(500, str(exc))

@app.get("/api/strategies")
def strategies(authorization: str = Header(default="")):
    session(authorization)
    return list(STRATEGIES)

@app.get("/api/scenarios/{scenario_id}/critical-repairs")
def critical(scenario_id: int, authorization: str = Header(default="")):
    session(authorization)
    return critical_repairs(scenario_id)

@app.get("/api/scenarios/{scenario_id}/critical-path")
def criticalpath(scenario_id: int, authorization: str = Header(default="")):
    session(authorization)
    try:
        return critical_path(scenario_id)
    except ValueError as exc:
        raise HTTPException(400, str(exc))

@app.get("/api/scenarios/{scenario_id}/skill-gaps")
def skillgaps(scenario_id: int, authorization: str = Header(default="")):
    session(authorization)
    return skill_gaps(scenario_id)

@app.get("/api/scenarios/{scenario_id}/cause-breakdown")
def causes(scenario_id: int, authorization: str = Header(default="")):
    session(authorization)
    from .db import connect
    with connect() as conn:
        return [dict(r) for r in conn.execute(
            "SELECT outage_cause, COUNT(*)::INT AS task_count, "
            "ROUND(AVG(estimated_cost),2)::FLOAT AS avg_cost, "
            "ROUND(AVG(service_weight),2)::FLOAT AS avg_weight "
            "FROM repair_tasks WHERE scenario_id=%s GROUP BY outage_cause "
            "HAVING COUNT(*) >= 1 ORDER BY task_count DESC",
            (scenario_id,)).fetchall()]
