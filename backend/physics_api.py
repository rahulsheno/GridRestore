"""Read-only REST endpoints for physics study runs (tables created by migration 006).

Runs are written by `python -m backend.grid.physics_study`, never by the API. Both roles may read.
"""
import base64
from typing import Optional

from fastapi import APIRouter, Header, HTTPException, Query

from .auth import require_role
from .grid import store

router = APIRouter(prefix="/api/physics", tags=["physics"])


def _session(authorization: str):
    if not authorization.startswith("Bearer "):
        raise HTTPException(401, "Missing bearer token")
    try:
        return require_role(authorization[7:], "admin", "operator")
    except PermissionError:
        raise HTTPException(403, "Not authorized")


def _found(value, what):
    if value is None:
        raise HTTPException(404, f"{what} not found")
    return value


@router.get("/runs", summary="List physics study runs, newest first")
def runs(limit: int = Query(default=50, ge=1, le=200), authorization: str = Header(default="")):
    """Each run is one execution of the physics study. The headline and plan weights are included."""
    _session(authorization)
    return store.list_runs(limit)


@router.get("/runs/{run_id}", summary="Overview of one physics run")
def overview(run_id: int, authorization: str = Header(default="")):
    """Validation checks, continuation summary, FDIA summaries, MDP policies (both weight sets) and the
    names of the stored figures. Long tables are served by the endpoints below."""
    _session(authorization)
    return _found(store.run_overview(run_id), f"Physics run {run_id}")


@router.get("/runs/{run_id}/continuation/{case}", summary="Load-scaling continuation curve for one case")
def continuation(run_id: int, case: str, authorization: str = Header(default="")):
    """One point per load factor alpha: operating status, maximum branch loading and minimum voltage."""
    _session(authorization)
    _found(store.run_overview(run_id), f"Physics run {run_id}")
    return store.continuation_curve(run_id, case)


@router.get("/runs/{run_id}/fdia/{case}/trials", summary="Per-trial FDIA results for one case")
def fdia_trials(run_id: int, case: str, limit: int = Query(default=200, ge=1, le=1000),
                offset: int = Query(default=0, ge=0), authorization: str = Header(default="")):
    """Clean false alarm, stealthy bypass and random-attack detection for each Monte Carlo trial."""
    _session(authorization)
    _found(store.run_overview(run_id), f"Physics run {run_id}")
    return store.fdia_trials(run_id, case, limit, offset)


@router.get("/runs/{run_id}/mdp/{case}", summary="MDP policies and transition probabilities for one case")
def mdp(run_id: int, case: str, weight_set: Optional[str] = Query(default=None, pattern="^(headline|plan)$"),
        authorization: str = Header(default="")):
    """Optimal action and value per state, for each stress vector and weight set, plus the transition
    probabilities of each action under both collapse models."""
    _session(authorization)
    _found(store.run_overview(run_id), f"Physics run {run_id}")
    return store.mdp_detail(run_id, case, weight_set)


@router.get("/runs/{run_id}/sensitivity", summary="Sensitivity sweeps (steepness, normal limit, weights, voltage scale)")
def sensitivity(run_id: int, authorization: str = Header(default="")):
    _session(authorization)
    return _found(store.sensitivity(run_id), f"Physics run {run_id}")


@router.get("/runs/{run_id}/convergence/{case}/{stress_vector}",
            summary="Value-iteration and finite-horizon convergence for one stress vector")
def convergence(run_id: int, case: str, stress_vector: str, authorization: str = Header(default="")):
    """stress_vector is 'base' or 'N-1 line <index>' (URL-encoded)."""
    _session(authorization)
    _found(store.run_overview(run_id), f"Physics run {run_id}")
    return store.convergence(run_id, case, stress_vector)


@router.get("/runs/{run_id}/figures/{name}", summary="A stored figure, as base64 with its content type")
def figure(run_id: int, name: str, authorization: str = Header(default="")):
    _session(authorization)
    content_type, data = _found(store.figure(run_id, name), f"Figure {name} of run {run_id}")
    return {"name": name, "content_type": content_type, "data_base64": base64.b64encode(data).decode()}
