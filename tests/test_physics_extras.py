"""Tests for the physics additions: LNR, targeted stealthy attack, policy simulation, cyber topology file,
run pruning and the discount-factor sweep. Each is checked against an independent property where possible."""
import json
import os
import tempfile
import uuid

import numpy as np
import pandas as pd
import pytest

from backend.grid import fdia, mdp, telemetry
from backend.grid.ac_se import normalized_residuals
from backend.grid.cases import load_case
from backend.grid.cyber import build_cyber_model, load_topology
from backend.grid.study import setup, stealthy_attack


@pytest.fixture(scope="module")
def case14_state():
    s = setup("case14")
    ac, tel = s["ac"], s["telemetry"]
    sigma = telemetry.sigma_vector(tel)
    comp = telemetry.compromised_mask(tel)
    rng = np.random.default_rng(5)
    z = ac.h(ac.state_from_powerflow()) + rng.normal(0, sigma)
    x0, _, _, _ = ac.estimate(z, sigma)
    return ac, sigma, comp, z, x0, rng


# ---------------------------------------------------------------- largest normalised residual

def test_stealthy_attack_leaves_normalised_residuals_unchanged(case14_state):
    ac, sigma, comp, z, x0, _ = case14_state
    att = stealthy_attack(ac.jacobian(x0), z, comp)
    assert att.feasible
    xa, _, _, _ = ac.estimate(z + att.a, sigma, x0=x0)
    clean = normalized_residuals(ac, z, x0, sigma).max()
    attacked = normalized_residuals(ac, z + att.a, xa, sigma).max()
    assert abs(attacked - clean) < 1e-3


def test_random_attack_is_caught_by_normalised_residuals(case14_state):
    ac, sigma, comp, z, x0, rng = case14_state
    a = fdia.random_attack(z, comp, rng)
    xr, _, _, _ = ac.estimate(z + a, sigma, x0=x0)
    assert normalized_residuals(ac, z + a, xr, sigma).max() > 3.0


# ---------------------------------------------------------------- targeted attack

def test_targeted_attack_follows_the_linear_prediction_and_beats_max_energy(case14_state):
    ac, sigma, comp, z, x0, _ = case14_state
    H0 = ac.jacobian(x0)
    row = 3 * ac.n + 0
    att = fdia.targeted_attack(H0, z, comp, row)
    assert att.feasible
    assert np.all(att.a[~comp] == 0.0) and fdia.bound_satisfied(att.a, z, comp)
    xa, _, _, _ = ac.estimate(z + att.a, sigma, x0=x0)
    achieved = ac.h(xa)[row] - ac.h(x0)[row]
    predicted = float(H0[row] @ att.c)
    assert abs(achieved - predicted) < 0.05 * abs(predicted) + 1e-4
    max_energy = stealthy_attack(H0, z, comp)
    xm, _, _, _ = ac.estimate(z + max_energy.a, sigma, x0=x0)
    assert abs(achieved) > 100 * abs(ac.h(xm)[row] - ac.h(x0)[row])


# ---------------------------------------------------------------- policy simulation

def test_simulated_policy_return_agrees_with_value_iteration():
    cal = mdp.calibrate("case14")
    bus = mdp.most_critical_bus(load_case("case14"))
    m = mdp.build_mdp("case14", cal, bus=bus, outcomes=mdp.compute_outcomes("case14", cal, bus=bus),
                      w=mdp.HEADLINE_W)
    vi = mdp.value_iteration(m)
    mean, se = mdp.simulate_policy(m, vi["policy"], 0, episodes=3000, horizon=400)
    assert abs(mean - vi["V"][0]) < 4 * se + 1e-4


# ---------------------------------------------------------------- cyber topology file

def test_cyber_topology_file_reproduces_the_compromised_set():
    model = build_cyber_model(4)
    assert model.compromised_rtus() == ["RTU-01", "RTU-02"]
    assert model.attack_path("RTU-03") is None
    assert build_cyber_model(6).compromised_rtus() == ["RTU-01", "RTU-02", "RTU-03"]


def test_cyber_topology_file_must_be_complete():
    spec = load_topology()
    spec.pop("entry_point")
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as fh:
        json.dump(spec, fh)
        path = fh.name
    try:
        with pytest.raises(ValueError, match="entry_point"):
            load_topology(path)
    finally:
        os.unlink(path)


# ---------------------------------------------------------------- sweep and pruning (database)

@pytest.mark.db
def test_prune_only_removes_the_named_runs_and_keeps_the_newest():
    from backend.db import connect
    from backend.grid.store import prune_runs, store_run
    from tests.test_physics_store import _synthetic_results
    ids = [store_run(_synthetic_results(), mode="quick", settings={"test": uuid.uuid4().hex}) for _ in range(3)]
    try:
        removed = prune_runs(keep=1, only=ids[:2])
        assert removed == 2
        with connect() as conn:
            left = {r["run_id"] for r in conn.execute(
                "SELECT run_id FROM physics_runs WHERE run_id = ANY(%s)", (ids,)).fetchall()}
        assert left == {ids[2]}
    finally:
        with connect() as conn:
            conn.execute("DELETE FROM physics_runs WHERE run_id = ANY(%s)", (ids,))


def test_prune_refuses_to_keep_nothing():
    from backend.grid.store import prune_runs
    with pytest.raises(ValueError):
        prune_runs(keep=0)


def test_discount_factor_changes_the_value_scale():
    cal = mdp.calibrate("case14")
    bus = mdp.most_critical_bus(load_case("case14"))
    outcomes = mdp.compute_outcomes("case14", cal, bus=bus)
    m = mdp.build_mdp("case14", cal, bus=bus, outcomes=outcomes, w=mdp.HEADLINE_W)
    v90 = mdp.value_iteration(m, gamma=0.90)["V"][0]
    v99 = mdp.value_iteration(m, gamma=0.99)["V"][0]
    assert abs(v99) > abs(v90)   # longer horizon, larger accumulated cost in the thermal state
