"""Tests for the physics results: voltage-based collapse, headline policy, and the database and REST round trip.

The round-trip test stores a small synthetic run, reads it back through the API, and deletes it again. It
does not touch the runs created by the physics study.
"""
import base64
import uuid

import numpy as np
import pandas as pd
import pytest

from backend.grid import mdp
from backend.grid.cases import load_case
from backend.grid.store import store_run

pytestmark = pytest.mark.db


# ---------------------------------------------------------------- voltage-based collapse (pure MDP)

@pytest.fixture(scope="module")
def case14_outcomes():
    cal = mdp.calibrate("case14")
    bus = mdp.most_critical_bus(load_case("case14"))
    return cal, bus, mdp.compute_outcomes("case14", cal, bus=bus)


def test_voltage_collapse_probability_follows_post_action_voltage(case14_outcomes):
    cal, bus, outcomes = case14_outcomes
    m = mdp.build_mdp("case14", cal, bus=bus, outcomes=outcomes, w=mdp.HEADLINE_W, collapse="voltage")
    for a_idx, action in enumerate(mdp.ACTIONS):
        vm = outcomes[("S2", action)]["min_vm"]
        expected = mdp.sigmoid(mdp.K_VOLTAGE * (mdp.VOLTAGE_LIMIT - vm))
        assert abs(m.P[a_idx, 2, 3] - expected) < 1e-12


def test_lower_voltage_means_higher_collapse_probability():
    assert mdp.sigmoid(mdp.K_VOLTAGE * (mdp.VOLTAGE_LIMIT - 0.80)) > mdp.sigmoid(
        mdp.K_VOLTAGE * (mdp.VOLTAGE_LIMIT - 0.95))
    # 0.5 at the limit, and about 1e-4 at 0.93 pu with the 0.01 pu scale
    assert abs(mdp.sigmoid(0.0) - 0.5) < 1e-12
    assert mdp.sigmoid(mdp.K_VOLTAGE * (mdp.VOLTAGE_LIMIT - 0.93)) < 1e-3


def test_unknown_collapse_model_is_rejected(case14_outcomes):
    cal, bus, outcomes = case14_outcomes
    with pytest.raises(ValueError):
        mdp.build_mdp("case14", cal, bus=bus, outcomes=outcomes, collapse="magic")


def test_headline_weights_choose_mitigation_in_thermal_state(case14_outcomes):
    cal, bus, outcomes = case14_outcomes
    m = mdp.build_mdp("case14", cal, bus=bus, outcomes=outcomes, w=mdp.HEADLINE_W)
    policy = mdp.value_iteration(m)["policy"]
    assert policy[2] == "LOAD_SHED"
    assert policy[0] == "DO_NOTHING"


def test_plan_weights_do_not_choose_mitigation_in_any_state(case14_outcomes):
    cal, bus, outcomes = case14_outcomes
    m = mdp.build_mdp("case14", cal, bus=bus, outcomes=outcomes, w=mdp.PLAN_W)
    assert set(mdp.value_iteration(m)["policy"][:3]) == {"DO_NOTHING"}


# ---------------------------------------------------------------- database and REST round trip

def _synthetic_results():
    png = b"\x89PNG\r\n\x1a\n" + b"synthetic"
    cont = pd.DataFrame([{"case": "case14", "alpha": a, "status": "S0", "max_loading": 0.6, "min_vm": 1.0}
                         for a in (1.0, 1.02)])
    summary = pd.DataFrame([{"case": "case14", "voltage_limit_alpha": 1.60, "nose_alpha": 1.78,
                             "first_s2_alpha": 1.32, "first_s3_alpha": 1.62, "first_divergence_alpha": 1.78,
                             "voltage_limit_alpha_free_q": 3.36, "nose_alpha_free_q": 4.06}])
    dc = pd.DataFrame([{"case": "case14", "measurements": 40, "stealthy_feasible": True,
                        "abs_change_J_stealthy": 1e-13, "bound_ok": True, "stealthy_detected": False}])
    ac = pd.DataFrame([{"case": "case14", "trials": 2, "clean_false_alarm_rate": 0.0,
                        "compromised_rtus": ["RTU-01", "RTU-02"]}])
    trials = pd.DataFrame([{"case": "case14", "trial": t, "J_clean": 10.0 + t, "clean_alarm": False,
                            "stealthy_feasible": True, "stealthy_bypass": True, "J_random": 900.0,
                            "random_detected": True} for t in range(2)])
    policies = pd.DataFrame([{"case": "case14", "stress_vector": "base", "weight_set": w, "state": s,
                              "loading_target": 0.6, "min_vm": 1.0, "V_star": -0.1,
                              "optimal_action": "DO_NOTHING", "isolated_bus": 8, "lambda_v": 3.8}
                             for w in ("headline", "plan") for s in ("S0", "S1", "S2", "S3")])
    trans = pd.DataFrame([{"case": "case14", "stress_vector": "base", "collapse_model": "voltage",
                           "action": "DO_NOTHING", "p_s3_given_s2": 1e-7, "p_s1_given_s0": 0.1,
                           "p_s2_given_s1": 0.2}])
    conv = pd.DataFrame([{"case": "case14", "stress_vector": "base", "method": "infinite_horizon_VI",
                          "step": 1, "max_abs_change": 0.5}])
    sens = pd.DataFrame([{"sweep": "k_voltage", "k": 10.0, "lambda0": 0.8, "w1": 10.0, "w3": 0.1,
                          "k_voltage": 100.0, "gamma": 0.95, "V_star_S0": -0.03, "action_S1": "DO_NOTHING",
                          "action_S2": "LOAD_SHED", "non_default_states": 1, "p_s3_given_s2": 1e-7}])
    validation = pd.DataFrame([{"check_name": "ptdf_dc_flow", "case_name": "case14", "metric": "max_line_flow_error_MW",
                                "value": 1e-13}])
    extra = pd.DataFrame([{"case": "case14", "kind": "lnr", "metrics": {"lnr_detection_rate_random": 1.0}}])
    return {"validation": validation, "continuation_curves": cont, "continuation_summary": summary,
            "fdia_extra": extra,
            "fdia_dc_invariance": dc, "fdia_ac_summary": ac, "fdia_ac_trials": trials,
            "mdp_policies": policies, "mdp_transition_probabilities": trans,
            "state_space_convergence": conv, "sensitivity_grid": sens, "sensitivity_heatmap_png": png}


@pytest.fixture
def stored_run():
    run_id = store_run(_synthetic_results(), mode="quick", settings={"test": uuid.uuid4().hex})
    yield run_id
    from backend.db import connect
    with connect() as conn:
        conn.execute("DELETE FROM physics_runs WHERE run_id=%s", (run_id,))


@pytest.fixture(scope="module")
def client():
    import os
    os.environ.setdefault("SESSION_SECRET", "test-only-secret")
    from fastapi.testclient import TestClient
    from backend.api import app
    return TestClient(app)


def _headers(client, user="operator", password="operator123"):
    token = client.post("/api/login", json={"username": user, "password": password}).json()["token"]
    return {"Authorization": f"Bearer {token}"}


def test_stored_run_is_read_back_through_the_api(client, stored_run):
    h = _headers(client)
    overview = client.get(f"/api/physics/runs/{stored_run}", headers=h).json()
    assert overview["run"]["mode"] == "quick"
    assert overview["run"]["headline_weights"] == {"w1": 10.0, "w2": 5.0, "w3": mdp.W3_HEADLINE}
    assert overview["run"]["plan_weights"] == {"w1": 10.0, "w2": 5.0, "w3": 1.0}
    assert overview["continuation_summary"][0]["nose_alpha"] == pytest.approx(1.78)
    assert overview["continuation_summary"][0]["nose_alpha_free_q"] == pytest.approx(4.06)
    assert {f["kind"] for f in overview["fdia"]} == {"dc", "ac", "lnr"}
    assert "sensitivity_heatmap" in overview["figures"]


def test_mdp_endpoint_filters_by_weight_set(client, stored_run):
    h = _headers(client)
    both = client.get(f"/api/physics/runs/{stored_run}/mdp/case14", headers=h).json()
    headline = client.get(f"/api/physics/runs/{stored_run}/mdp/case14?weight_set=headline", headers=h).json()
    assert len(both["policy"]) == 8 and len(headline["policy"]) == 4
    assert {p["weight_set"] for p in headline["policy"]} == {"headline"}
    assert both["transitions"][0]["collapse_model"] == "voltage"


def test_trials_and_figure_endpoints(client, stored_run):
    h = _headers(client)
    trials = client.get(f"/api/physics/runs/{stored_run}/fdia/case14/trials", headers=h).json()
    assert [t["trial"] for t in trials] == [0, 1]
    fig = client.get(f"/api/physics/runs/{stored_run}/figures/sensitivity_heatmap", headers=h).json()
    assert base64.b64decode(fig["data_base64"]).startswith(b"\x89PNG")


def test_missing_run_and_missing_token(client):
    h = _headers(client)
    assert client.get("/api/physics/runs/999999999", headers=h).status_code == 404
    assert client.get("/api/physics/runs").status_code == 401


def test_deleting_a_run_removes_its_rows(client):
    run_id = store_run(_synthetic_results(), mode="quick", settings={})
    from backend.db import connect
    with connect() as conn:
        conn.execute("DELETE FROM physics_runs WHERE run_id=%s", (run_id,))
        left = conn.execute("SELECT COUNT(*) AS n FROM physics_validation WHERE run_id=%s", (run_id,)).fetchone()["n"]
    assert left == 0
