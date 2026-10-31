"""FastAPI backend for the Next.js frontend.

Roles: admin (everything) and operator (view, run schedules, analytics). Admin-only routes return
403 with a clear message for operators. Interactive docs: http://127.0.0.1:8000/docs
"""
import os
import time
import uuid
from datetime import datetime
from typing import Optional

import pandas as pd
from dotenv import load_dotenv
from fastapi import FastAPI, Header, HTTPException, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, PlainTextResponse
from pydantic import BaseModel, Field

from . import analytics, audit_dashboard, diffing, exact, report, tasks_io, versions
from .auth import (authenticate, change_password, create_token, create_user,
                   require_role, revoke_refresh, rotate_refresh)
from .criticality import critical_path, critical_repairs, skill_gaps
from .db import (connect, create_scenario, get_scenario_tasks, health_check, list_run_actions,
                 list_runs, list_scenarios, save_run)
from .logging_config import log
from . import physics_map, ratelimit
from .scheduler import STRATEGIES, schedule_repairs
from .vectors import find_similar_repairs, full_text_search_repairs

load_dotenv()

TAGS = [
    {"name": "auth", "description": "Log in and receive a signed session token."},
    {"name": "scenarios", "description": "Outage scenarios: budget, crew count and criticality views."},
    {"name": "versions", "description": "Scenario history. Every task edit is stored as a version; "
                                       "versions can be compared and restored (history is kept)."},
    {"name": "tasks-io", "description": "CSV export, and CSV import with row-level validation."},
    {"name": "scheduling", "description": "Run a heuristic scheduler and save the result as a run."},
    {"name": "runs", "description": "Saved runs, their actions, what-changed diffs and Markdown reports."},
    {"name": "analytics", "description": "Budget/crew sweeps, seeded robustness trials, exact-baseline gaps."},
    {"name": "dashboard", "description": "Run statistics from the materialized view, with a staleness check."},
    {"name": "audit", "description": "Audit history with filters (admin only)."},
    {"name": "search", "description": "Similar-repair search: pgvector (vector) or full-text (fts)."},
    {"name": "physics", "description": "Results of the physics study (IEEE cases): validation, continuation, "
                                      "FDIA Monte Carlo, MDP policies and sensitivity. Read-only."},
]

app = FastAPI(
    title="GridRestore API",
    version="2.0.0",
    description=(
        "Synthetic power-distribution restoration planner: PostgreSQL + pgvector with role-based access.\n\n"
        "**Roles:** `admin` can change data and read the audit log; `operator` can view and run schedules. "
        "Send the token from `/api/login` as `Authorization: Bearer <token>`.\n\n"
        "All data is synthetic. This is an academic demonstration, not an operational control system."
    ),
    openapi_tags=TAGS,
)
app.add_middleware(
    CORSMiddleware,
    allow_origin_regex=r"^https?://(localhost|127\.0\.0\.1|\[::1\]|192\.168\.\d+\.\d+|10\.\d+\.\d+\.\d+|172\.(1[6-9]|2\d|3[01])\.\d+\.\d+)(:\d+)?$",
    allow_credentials=True, allow_methods=["*"], allow_headers=["*"],
)

from .physics_api import router as physics_router  # noqa: E402  (read-only physics results)
app.include_router(physics_router)


# ---------------------------------------------------------------- request logging and errors

@app.middleware("http")
async def log_requests(request: Request, call_next):
    request_id = request.headers.get("X-Request-ID") or uuid.uuid4().hex
    request.state.request_id = request_id
    started = time.perf_counter()
    response = await call_next(request)
    duration = round((time.perf_counter() - started) * 1000, 2)
    response.headers["X-Request-ID"] = request_id
    log.info("request completed", extra={"event": "http_request", "request_id": request_id,
                                          "method": request.method, "path": request.url.path,
                                          "status": response.status_code, "duration_ms": duration})
    return response


@app.exception_handler(RequestValidationError)
async def validation_error(request: Request, exc: RequestValidationError):
    request_id = getattr(request.state, "request_id", uuid.uuid4().hex)
    log.warning("request validation failed", extra={"event": "validation_error",
                                                    "request_id": request_id, "path": request.url.path})
    return JSONResponse(status_code=422, content={"detail": exc.errors(), "request_id": request_id},
                        headers={"X-Request-ID": request_id})


@app.exception_handler(Exception)
async def unhandled_error(request: Request, exc: Exception):
    request_id = getattr(request.state, "request_id", uuid.uuid4().hex)
    log.error("unhandled error", extra={"event": "unhandled_error", "request_id": request_id,
                                        "path": request.url.path, "error": type(exc).__name__},
              exc_info=exc)
    return JSONResponse(status_code=500, content={"detail": "Internal server error",
                                                  "request_id": request_id},
                        headers={"X-Request-ID": request_id})


# ---------------------------------------------------------------- authorisation helpers

def session(authorization: str = ""):
    if not authorization.startswith("Bearer "):
        raise HTTPException(401, "Missing bearer token")
    try:
        return require_role(authorization[7:], "admin", "operator")
    except PermissionError:
        raise HTTPException(403, "Not authorized")


def admin_only(authorization: str = ""):
    """Return the admin session, or raise a clear 403 for operators."""
    if not authorization.startswith("Bearer "):
        raise HTTPException(401, "Missing bearer token")
    try:
        return require_role(authorization[7:], "admin")
    except PermissionError:
        raise HTTPException(403, "This action needs the admin role. Operators can view and run schedules.")


def _scenario_or_404(scenario_id):
    for row in list_scenarios():
        if row["scenario_id"] == scenario_id:
            return row
    raise HTTPException(404, "Scenario not found")


def _run_or_404(run_id):
    with connect() as conn:
        row = conn.execute("SELECT run_id, scenario_id, strategy_name, total_cost, makespan_hours, "
                           "weighted_recovery_score, started_at FROM restoration_runs WHERE run_id=%s",
                           (run_id,)).fetchone()
    if row is None:
        raise HTTPException(404, f"Run {run_id} not found")
    return row


# ---------------------------------------------------------------- request bodies

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
    use_physics: bool = False  # apply physics-layer voltage-risk weights (edge→IEEE case mapping)


class SearchBody(BaseModel):
    query: str = Field(min_length=1)
    mode: str = "vector"
    limit: int = Field(default=5, ge=1, le=20)


class TaskUpdate(BaseModel):
    task_id: str
    component_name: Optional[str] = None
    estimated_hours: Optional[float] = Field(default=None, gt=0, le=500)
    estimated_cost: Optional[float] = Field(default=None, ge=0)
    service_weight: Optional[float] = Field(default=None, ge=0)
    priority: Optional[int] = Field(default=None, ge=1, le=5)
    region_code: Optional[str] = None
    required_skill: Optional[str] = None
    outage_cause: Optional[str] = None
    depends_on: Optional[list[str]] = None


class TaskEditBody(BaseModel):
    note: str = Field(default="", max_length=300)
    updates: list[TaskUpdate] = Field(min_length=1, max_length=500)


class RollbackBody(BaseModel):
    version_no: int = Field(ge=1)
    note: str = Field(default="", max_length=300)


class ImportBody(BaseModel):
    csv: str = Field(min_length=1, max_length=2_000_000)
    commit: bool = False
    note: str = Field(default="CSV import", max_length=300)


class RobustnessBody(BaseModel):
    scenario_id: int
    trials: int = Field(default=200, ge=2, le=5000)
    noise: float = Field(default=0.2, ge=0, lt=1)
    seed: int = 20261018


class SweepBody(BaseModel):
    scenario_id: int
    budgets: list[float] = Field(min_length=1, max_length=30)
    crew_counts: list[int] = Field(min_length=1, max_length=10)


class ExactGapBody(BaseModel):
    scenario_id: int
    horizon_hours: float = Field(gt=0, le=1000)


# ---------------------------------------------------------------- system and auth

@app.get("/health", tags=["system"], summary="Database health check")
def health():
    """Returns 200 with the database name when PostgreSQL answers, otherwise 503."""
    try:
        info = health_check()
        return {"status": "ok", "database": info["database"]}
    except Exception as exc:
        raise HTTPException(503, str(exc))


@app.post("/api/login", tags=["auth"], summary="Log in and get an access + refresh token")
def login(body: LoginBody, request: Request):
    """Check the username and password (bcrypt) and return a short-lived access
    token plus a rotating refresh token. Rate limit: 5 attempts per minute."""
    allowed, retry = ratelimit.check(
        f"login:{request.client.host if request.client else 'NA'}:{body.username}",
        limit=int(os.getenv("LOGIN_RATE_LIMIT", "5")))
    if not allowed:
        raise HTTPException(429, f"Too many attempts; retry after {retry}s")
    result = authenticate(body.username, body.password)
    if not result:
        raise HTTPException(401, "Invalid credentials")
    log.info("login", extra={"event": "login", "username": result["username"], "role": result["role"]})
    return result


class RefreshBody(BaseModel):
    refresh_token: str = Field(min_length=16)


@app.post("/api/refresh", tags=["auth"], summary="Rotate the refresh token and get a new access token")
def refresh(body: RefreshBody, request: Request):
    """Exchange a valid refresh token for a new pair. The used token is revoked
    (rotation); reusing a revoked, expired or unknown token is refused."""
    allowed, retry = ratelimit.check(
        f"refresh:{request.client.host if request.client else 'NA'}",
        limit=int(os.getenv("REFRESH_RATE_LIMIT", "5")))
    if not allowed:
        raise HTTPException(429, f"Too many attempts; retry after {retry}s")
    result = rotate_refresh(body.refresh_token)
    if not result:
        raise HTTPException(401, "Refresh token is invalid, expired or already used")
    return result


@app.post("/api/logout", tags=["auth"], summary="Revoke a refresh token")
def logout(body: RefreshBody):
    revoke_refresh(body.refresh_token)
    return {"revoked": True}


class PasswordBody(BaseModel):
    old_password: str = Field(min_length=1)
    new_password: str = Field(min_length=6)


@app.post("/api/password", tags=["auth"], summary="Change the current password")
def change_password_route(body: PasswordBody, authorization: str = Header(default="")):
    who = session(authorization)
    result = change_password(who["username"], body.old_password, body.new_password)
    if not result:
        raise HTTPException(400, "Password change rejected: old password wrong, new password too short, or identical")
    log.info("password_changed", extra={"event": "password_changed", "username": who["username"]})
    return result


@app.post("/api/register", tags=["auth"], summary="Sign up a new user (operator role)")
def register(body: LoginBody, request: Request):
    """Creates a new operator account. New sign-ups can never become admin;
    admin accounts exist only through the seeded migration."""
    allowed, retry = ratelimit.check(
        f"register:{request.client.host if request.client else 'NA'}",
        limit=int(os.getenv("REGISTER_RATE_LIMIT", "5")))
    if not allowed:
        raise HTTPException(429, f"Too many attempts; retry after {retry}s")
    result = create_user(body.username, body.password)
    if not result:
        raise HTTPException(400, "Sign-up failed: pick a username of 3-50 characters and a password of at least 6 characters (username may already be taken)")
    log.info("register", extra={"event": "register", "username": result["username"]})
    return result


@app.get("/api/strategies", tags=["scheduling"], summary="List scheduler strategies")
def strategies(authorization: str = Header(default="")):
    session(authorization)
    return list(STRATEGIES)


# ---------------------------------------------------------------- scenarios

@app.get("/api/scenarios", tags=["scenarios"], summary="List outage scenarios")
def scenarios(authorization: str = Header(default="")):
    session(authorization)
    return [dict(r) for r in list_scenarios()]


@app.post("/api/scenarios", tags=["scenarios"], summary="Create an outage scenario (admin)")
def create(body: ScenarioBody, authorization: str = Header(default="")):
    """Create a scenario and copy the demo task template into it. Admin only."""
    user = admin_only(authorization)
    try:
        return dict(create_scenario(body.name, body.budget, body.crew_count,
                                    username=user["username"]))
    except ValueError as exc:
        raise HTTPException(400, str(exc))


@app.get("/api/scenarios/{scenario_id}/critical-repairs", tags=["scenarios"],
         summary="Repairs ranked by how many others they unblock")
def critical(scenario_id: int, authorization: str = Header(default="")):
    session(authorization)
    return critical_repairs(scenario_id)


@app.get("/api/scenarios/{scenario_id}/critical-path", tags=["scenarios"],
         summary="Longest dependency chain and the makespan floor")
def criticalpath(scenario_id: int, authorization: str = Header(default="")):
    session(authorization)
    try:
        return critical_path(scenario_id)
    except ValueError as exc:
        raise HTTPException(400, str(exc))


@app.get("/api/scenarios/{scenario_id}/skill-gaps", tags=["scenarios"],
         summary="Required skills that no crew can cover")
def skillgaps(scenario_id: int, authorization: str = Header(default="")):
    session(authorization)
    return skill_gaps(scenario_id)


@app.get("/api/scenarios/{scenario_id}/cause-breakdown", tags=["scenarios"],
         summary="Task counts and averages grouped by outage cause")
def causes(scenario_id: int, authorization: str = Header(default="")):
    session(authorization)
    with connect() as conn:
        return [dict(r) for r in conn.execute(
            "SELECT outage_cause, COUNT(*)::INT AS task_count, "
            "ROUND(AVG(estimated_cost),2)::FLOAT AS avg_cost, "
            "ROUND(AVG(service_weight),2)::FLOAT AS avg_weight "
            "FROM repair_tasks WHERE scenario_id=%s GROUP BY outage_cause "
            "HAVING COUNT(*) >= 1 ORDER BY task_count DESC",
            (scenario_id,)).fetchall()]


@app.get("/api/scenarios/{scenario_id}/grid", tags=["scenarios"],
         summary="Grid network with each edge's restoration status from the latest run")
def grid_view(scenario_id: int, authorization: str = Header(default="")):
    """Nodes and edges of the grid, plus task status from the scenario's most recent run.

    A task is `scheduled` if the latest run includes it, `blocked` if it is unscheduled and at least
    one prerequisite is also unscheduled (it cannot start), and `unscheduled` otherwise.
    An edge takes the worst status of the tasks on it: blocked > unscheduled > restored; `clear` has no tasks.
    """
    session(authorization)
    _scenario_or_404(scenario_id)
    with connect() as conn:
        nodes = [dict(r) for r in conn.execute(
            "SELECT node_id, node_name, node_type, criticality, region_code FROM grid_nodes ORDER BY node_id").fetchall()]
        edges = [dict(r) for r in conn.execute(
            "SELECT edge_id, from_node_id, to_node_id, component_type FROM grid_edges ORDER BY edge_id").fetchall()]
        tasks = [dict(r) for r in conn.execute(
            "SELECT task_id, edge_id FROM repair_tasks WHERE scenario_id=%s", (scenario_id,)).fetchall()]
        deps = conn.execute(
            "SELECT d.task_id, d.prerequisite_task_id FROM task_dependencies d "
            "JOIN repair_tasks t ON t.task_id=d.task_id WHERE t.scenario_id=%s", (scenario_id,)).fetchall()
        latest = conn.execute("SELECT run_id FROM restoration_runs WHERE scenario_id=%s "
                              "ORDER BY run_id DESC LIMIT 1", (scenario_id,)).fetchone()
        scheduled = set()
        if latest:
            scheduled = {r["task_id"] for r in conn.execute(
                "SELECT task_id FROM scheduled_actions WHERE run_id=%s", (latest["run_id"],)).fetchall()}
    prereqs = {}
    for d in deps:
        prereqs.setdefault(d["task_id"], []).append(d["prerequisite_task_id"])
    task_status = {}
    for t in tasks:
        if t["task_id"] in scheduled:
            task_status[t["task_id"]] = "scheduled"
        elif any(p not in scheduled for p in prereqs.get(t["task_id"], [])):
            task_status[t["task_id"]] = "blocked"
        else:
            task_status[t["task_id"]] = "unscheduled"
    rank = {"blocked": 3, "unscheduled": 2, "scheduled": 1}
    edge_status = {}
    for t in tasks:
        current = edge_status.get(t["edge_id"])
        status = task_status[t["task_id"]]
        if current is None or rank[status] > rank[current]:
            edge_status[t["edge_id"]] = status
    for e in edges:
        worst = edge_status.get(e["edge_id"])
        e["status"] = {"blocked": "blocked", "unscheduled": "unscheduled",
                       "scheduled": "restored"}.get(worst, "clear")
    return {"scenario_id": scenario_id, "latest_run_id": latest["run_id"] if latest else None,
            "nodes": nodes, "edges": edges, "task_status": task_status,
            "blocked_task_ids": sorted(t for t, s in task_status.items() if s == "blocked")}


# ---------------------------------------------------------------- scenario versions

@app.get("/api/scenarios/{scenario_id}/versions", tags=["versions"], summary="List versions of a scenario")
def list_versions(scenario_id: int, authorization: str = Header(default="")):
    session(authorization)
    _scenario_or_404(scenario_id)
    return versions.list_versions(scenario_id)


@app.get("/api/scenarios/{scenario_id}/versions/diff", tags=["versions"],
         summary="Compare two versions of a scenario")
def diff_versions(scenario_id: int, from_version: int = Query(alias="from", ge=1),
                  to_version: int = Query(alias="to", ge=1), authorization: str = Header(default="")):
    """Field-level task changes, added and removed tasks, and dependency changes between two versions."""
    session(authorization)
    try:
        old = versions.get_version(scenario_id, from_version)
        new = versions.get_version(scenario_id, to_version)
    except LookupError as exc:
        raise HTTPException(404, str(exc))
    return {"from": from_version, "to": to_version, **versions.diff_snapshots(old, new)}


@app.get("/api/scenarios/{scenario_id}/versions/{version_no}", tags=["versions"],
         summary="Read one stored version")
def read_version(scenario_id: int, version_no: int, authorization: str = Header(default="")):
    session(authorization)
    try:
        return {"version_no": version_no, "snapshot": versions.get_version(scenario_id, version_no)}
    except LookupError as exc:
        raise HTTPException(404, str(exc))


@app.patch("/api/scenarios/{scenario_id}/tasks", tags=["versions"],
           summary="Edit repair tasks; stores a new version (admin)")
def edit_tasks(scenario_id: int, body: TaskEditBody, authorization: str = Header(default="")):
    """Applies all updates in one transaction, rejects dependency cycles, and stores the result as a new version."""
    admin = admin_only(authorization)
    updates = [u.model_dump(exclude_unset=True) for u in body.updates]
    try:
        number = versions.apply_changes(scenario_id, admin["username"], body.note, updates=updates)
    except LookupError as exc:
        raise HTTPException(404, str(exc))
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    log.info("scenario edited", extra={"event": "scenario_edit", "scenario_id": scenario_id,
                                       "username": admin["username"], "task_count": len(updates)})
    return {"scenario_id": scenario_id, "version_no": number}


@app.post("/api/scenarios/{scenario_id}/rollback", tags=["versions"],
          summary="Restore an earlier version (admin); history is kept")
def rollback_scenario(scenario_id: int, body: RollbackBody, authorization: str = Header(default="")):
    admin = admin_only(authorization)
    try:
        number = versions.rollback(scenario_id, body.version_no, admin["username"], body.note)
    except LookupError as exc:
        raise HTTPException(404, str(exc))
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    log.info("scenario rolled back", extra={"event": "scenario_rollback", "scenario_id": scenario_id,
                                            "username": admin["username"]})
    return {"scenario_id": scenario_id, "restored_from": body.version_no, "version_no": number}


# ---------------------------------------------------------------- CSV import and export

@app.get("/api/scenarios/{scenario_id}/tasks.csv", tags=["tasks-io"],
         summary="Export repair tasks as CSV", response_class=PlainTextResponse)
def export_tasks(scenario_id: int, authorization: str = Header(default="")):
    session(authorization)
    _scenario_or_404(scenario_id)
    rows, deps = tasks_io.load_task_rows(scenario_id)
    return PlainTextResponse(tasks_io.export_task_csv(rows, deps), media_type="text/csv")


@app.post("/api/scenarios/{scenario_id}/tasks/import", tags=["tasks-io"],
          summary="Validate, and optionally import, repair tasks from CSV (admin)")
def import_tasks(scenario_id: int, body: ImportBody, authorization: str = Header(default="")):
    """Every row is validated and all row errors are returned together. With `commit: true`, nothing
    is written unless the whole file is valid; a valid import is stored as one new version."""
    admin = admin_only(authorization)
    _scenario_or_404(scenario_id)
    edges, global_ids, scenario_ids = tasks_io.load_reference_ids(scenario_id)
    result = tasks_io.validate_task_csv(body.csv, edges, global_ids, scenario_ids)
    response = {"valid": result["valid"], "errors": result["errors"], "committed": False,
                "version_no": None}
    if not body.commit:
        return response
    if not result["valid"]:
        response["message"] = "Nothing imported: fix the errors and try again."
        return response
    try:
        response["version_no"] = versions.apply_changes(scenario_id, admin["username"], body.note,
                                                        inserts=result["rows"])
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    response.update(committed=True, inserted=len(result["rows"]))
    log.info("tasks imported", extra={"event": "csv_import", "scenario_id": scenario_id,
                                      "username": admin["username"], "task_count": len(result["rows"])})
    return response


# ---------------------------------------------------------------- scheduling and runs

@app.get("/api/scenarios/{scenario_id}/physics-map", tags=["physics"],
         summary="Element mapping: every repair task's edge -> IEEE case element + voltage risk")
def physics_mapping(scenario_id: int, refresh: bool = False, authorization: str = Header(default="")):
    session(authorization)
    _scenario_or_404(scenario_id)
    if refresh:
        physics_map.ensure_map()
    rows = physics_map.map_rows(scenario_id)
    if not rows:
        raise HTTPException(400, "This scenario has no repair tasks. Add tasks in Task data, or create a scenario from a template.")
    return {"scenario_id": scenario_id, "max_bonus": 1.0 + physics_map._PHI, "rows": rows}

@app.post("/api/schedule", tags=["scheduling"], summary="Run a scheduler and save the result as a run")
def schedule(body: ScheduleBody, authorization: str = Header(default="")):
    user = session(authorization)
    if body.strategy not in STRATEGIES:
        raise HTTPException(400, f"Unknown strategy: {body.strategy}")
    scenario = _scenario_or_404(body.scenario_id)
    rows, deps = get_scenario_tasks(body.scenario_id)
    if not rows:
        raise HTTPException(400, "This scenario has no repair tasks. Add tasks in Task data, or create a scenario from a template.")
    started = time.perf_counter()
    pweights = None
    if body.use_physics:
        pweights = physics_map.task_weights(body.scenario_id, refresh=True)
    try:
        result = schedule_repairs(pd.DataFrame(rows), body.strategy,
                                  float(scenario["budget"]), body.crews, deps,
                                  physics_weights=pweights if body.strategy == "gridrestore_score" else None)
        notes = {"strategy": body.strategy, "crews": body.crews}
        if pweights is not None:
            notes["physics_weights_applied"] = pweights
        run_id = save_run(body.scenario_id, result, notes=notes,
                          username=user["username"])
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    log.info("schedule run saved", extra={
        "event": "schedule_run", "run_id": run_id, "scenario_id": body.scenario_id,
        "strategy": body.strategy, "task_count": len(rows), "scheduled_count": result["scheduled_count"],
        "total_cost": result["total_cost"], "makespan_hours": result["makespan_hours"],
        "duration_ms": round((time.perf_counter() - started) * 1000, 2), "username": user["username"]})
    return {"run_id": run_id, **result}


@app.get("/api/runs", tags=["runs"], summary="List saved runs, optionally for one scenario")
def runs(scenario_id: int = None, authorization: str = Header(default="")):
    session(authorization)
    return [dict(r) for r in list_runs(scenario_id)]


@app.get("/api/runs/diff", tags=["runs"], summary="What changed between two runs of one scenario")
def runs_diff(a: int, b: int, authorization: str = Header(default="")):
    """Lists tasks whose crew, start or finish changed, with a reason for each change."""
    session(authorization)
    run_a, run_b = _run_or_404(a), _run_or_404(b)
    if run_a["scenario_id"] != run_b["scenario_id"]:
        raise HTTPException(400, "Both runs must belong to the same scenario")
    _, deps = get_scenario_tasks(run_a["scenario_id"])
    return {"run_a": a, "run_b": b, "scenario_id": run_a["scenario_id"],
            **diffing.diff_runs(list_run_actions(a), list_run_actions(b), deps)}


@app.get("/api/runs/{run_id}/actions", tags=["runs"], summary="Scheduled actions of one run")
def actions(run_id: int, authorization: str = Header(default="")):
    session(authorization)
    _run_or_404(run_id)
    return [dict(r) for r in list_run_actions(run_id)]


@app.get("/api/runs/{run_id}/report.md", tags=["runs"], summary="Markdown report for one run",
         response_class=PlainTextResponse)
def run_report(run_id: int, authorization: str = Header(default="")):
    session(authorization)
    run = _run_or_404(run_id)
    scenario = _scenario_or_404(run["scenario_id"])
    rows, deps = get_scenario_tasks(run["scenario_id"])
    tasks_by_id = {r["task_id"]: r for r in rows}
    body = report.render_run_report(run, scenario, list_run_actions(run_id), tasks_by_id, deps)
    return PlainTextResponse(body, media_type="text/markdown")


# ---------------------------------------------------------------- analytics

@app.post("/api/analytics/robustness", tags=["analytics"],
          summary="Seeded robustness trials per strategy, with 95% confidence intervals")
def robustness(body: RobustnessBody, authorization: str = Header(default="")):
    """Perturbs repair durations in each trial. Every strategy sees the same perturbations."""
    session(authorization)
    scenario = _scenario_or_404(body.scenario_id)
    rows, deps = get_scenario_tasks(body.scenario_id)
    if not rows:
        raise HTTPException(400, "This scenario has no repair tasks. Add tasks in Task data, or create a scenario from a template.")
    crews = analytics.make_crews(int(scenario["crew_count"]))
    return {"scenario_id": body.scenario_id, "budget": float(scenario["budget"]),
            **analytics.compare_strategies(pd.DataFrame(rows), deps, float(scenario["budget"]),
                                           crews, body.trials, body.noise, body.seed)}


@app.post("/api/analytics/sweep", tags=["analytics"],
          summary="Score and makespan over a grid of budgets and crew counts")
def sweep(body: SweepBody, authorization: str = Header(default="")):
    session(authorization)
    _scenario_or_404(body.scenario_id)
    if any(c < 1 or c > 20 for c in body.crew_counts):
        raise HTTPException(400, "crew counts must be between 1 and 20")
    rows, deps = get_scenario_tasks(body.scenario_id)
    if not rows:
        raise HTTPException(400, "This scenario has no repair tasks. Add tasks in Task data, or create a scenario from a template.")
    grid = analytics.sweep(pd.DataFrame(rows), deps, body.budgets, body.crew_counts)
    return grid.to_dict(orient="records")


@app.post("/api/analytics/exact-gap", tags=["analytics"],
          summary="Optimality gap of each heuristic against an exact solver (small scenarios)")
def exact_gap(body: ExactGapBody, authorization: str = Header(default="")):
    """Solves the scenario as an integer program. Limited to 12 tasks and 4 crews."""
    session(authorization)
    scenario = _scenario_or_404(body.scenario_id)
    rows, deps = get_scenario_tasks(body.scenario_id)
    if not rows:
        raise HTTPException(400, "This scenario has no repair tasks. Add tasks in Task data, or create a scenario from a template.")
    if len(rows) > 12:
        raise HTTPException(400, "The exact solver is limited to 12 tasks; this scenario has more")
    if int(scenario["crew_count"]) > 4:
        raise HTTPException(400, "The exact solver is limited to 4 crews")
    crews = analytics.make_crews(int(scenario["crew_count"]))
    try:
        gaps = exact.evaluate_gap(pd.DataFrame(rows), deps, float(scenario["budget"]), crews,
                                  body.horizon_hours, time_limit=60)
    except (RuntimeError, AssertionError) as exc:
        raise HTTPException(500, str(exc))
    return {"scenario_id": body.scenario_id, "horizon_hours": body.horizon_hours,
            "objective": "service weight of tasks finishing by the horizon", "results": gaps}


# ---------------------------------------------------------------- dashboard and audit

@app.get("/api/dashboard/run-stats", tags=["dashboard"],
         summary="Run statistics per scenario and strategy (materialized view or live)")
def dashboard_stats(mode: str = "materialized", authorization: str = Header(default="")):
    """mode=materialized reads mv_scenario_run_stats; mode=live aggregates the base tables.
    `freshness.stale` is true when runs were added after the view was last refreshed."""
    session(authorization)
    try:
        rows = audit_dashboard.run_stats(mode)
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    return {"mode": mode, "rows": rows, "freshness": audit_dashboard.stats_freshness()}


@app.post("/api/dashboard/refresh", tags=["dashboard"],
          summary="Refresh the materialized run statistics (admin)")
def dashboard_refresh(authorization: str = Header(default="")):
    admin = admin_only(authorization)
    result = audit_dashboard.refresh_run_stats()
    log.info("materialized view refreshed", extra={"event": "mv_refresh", "username": admin["username"],
                                                   "duration_ms": result["duration_ms"]})
    return result


@app.get("/api/audit", tags=["audit"], summary="Audit history with filters (admin)")
def audit_history(table_name: Optional[str] = None, operation: Optional[str] = None,
                  row_key: Optional[str] = None, app_user: Optional[str] = None,
                  since: Optional[datetime] = None, until: Optional[datetime] = None,
                  limit: int = Query(default=50, ge=1, le=500), offset: int = Query(default=0, ge=0),
                  include_data: bool = False, authorization: str = Header(default="")):
    """Filter by table, operation, row key, app user and time window. Operators receive 403."""
    admin_only(authorization)
    try:
        return audit_dashboard.query_audit(table_name, operation, row_key, app_user, since, until,
                                           limit, offset, include_data)
    except ValueError as exc:
        raise HTTPException(400, str(exc))


# ---------------------------------------------------------------- search

@app.post("/api/search", tags=["search"], summary="Find similar past repairs (vector or full-text)")
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
