"""Tests for the physics layer (backend/grid). These check the claims the artifacts rely on.

They use the IEEE cases bundled with pandapower only. Runtime is a few tens of seconds.
"""
import warnings

import networkx as nx
import numpy as np
import pandapower as pp
import pytest
from scipy.stats import binomtest, chi2

from backend.grid import cyber, fdia, mdp, operating_point, study, telemetry
from backend.grid.ac_se import ACModel
from backend.grid.cases import load_case
from backend.grid.dc_model import DCModel

warnings.simplefilter("ignore")


# ---------------------------------------------------------------- physics models vs pandapower

@pytest.mark.parametrize("case", ["case9", "case14", "case30", "case57", "case118"])
def test_ptdf_matches_pandapower_dc_flows(case):
    net = load_case(case)
    dc = DCModel(net)
    pp.rundcpp(net)
    full = np.zeros(dc.n)
    for pp_bus in net.bus.index:
        full[int(net._pd2ppc_lookups["bus"][pp_bus])] = -net.res_bus.p_mw.loc[pp_bus] / net.sn_mva
    flows = dc.flows_from_injections(full) * net.sn_mva
    for (elm, loc), f in zip(dc.branch_labels(net), flows):
        ref = net.res_line.p_from_mw.iloc[loc] if elm == "line" else net.res_trafo.p_hv_mw.iloc[loc]
        assert abs(f - ref) < 1e-7, (case, elm, loc)


@pytest.mark.parametrize("case", ["case14", "case30", "case118"])
def test_measurement_model_reproduces_pandapower_ac_solution(case):
    net = load_case(case)
    ac = ACModel(net)
    h = ac.h(ac.state_from_powerflow())
    ref, _ = ac.pandapower_reference()
    n = ac.n
    assert np.max(np.abs(h[:n] - ref[:n])) < 1e-9
    assert np.max(np.abs(h[n:2 * n] - ref[n:2 * n])) < 1e-7
    assert np.max(np.abs(h[2 * n:3 * n] - ref[2 * n:3 * n])) < 1e-7


def test_reference_angle_is_a_model_input_not_zero():
    net = load_case("case118")
    ac = ACModel(net)
    assert abs(ac.theta_ref - np.deg2rad(30.0)) < 1e-12  # pandapower's external grid is at 30 degrees


def test_rerating_sets_base_line_loading_and_keeps_flows():
    net = load_case("case14")
    loading = net.res_line.loading_percent
    assert np.allclose(loading[loading > 1e-3], 60.0, atol=1e-6)


# ---------------------------------------------------------------- Gauss-Newton and chi-squared test

@pytest.fixture(scope="module")
def case14_ac():
    net = load_case("case14")
    ac = ACModel(net)
    tel_sigma = np.array([telemetry.SIGMA[k] for k in
                          (["V"] * ac.n + ["P_inj"] * ac.n + ["Q_inj"] * ac.n
                           + ["P_flow"] * ac.nbr + ["Q_flow"] * ac.nbr)])
    return ac, tel_sigma


def test_gauss_newton_recovers_noise_free_state(case14_ac):
    ac, sigma = case14_ac
    x = ac.state_from_powerflow()
    xh, r, J, it = ac.estimate(ac.h(x), sigma)
    assert np.max(np.abs(xh - x)) < 1e-9
    assert J < 1e-12


def test_chi_squared_degrees_of_freedom_and_calibration(case14_ac):
    ac, sigma = case14_ac
    thr = ac.chi2_threshold(0.01)
    assert abs(thr - chi2.ppf(0.99, ac.m - ac.p)) < 1e-9
    rng = np.random.default_rng(7)
    z_true = ac.h(ac.state_from_powerflow())
    trials = 400
    x0 = ac.state_from_powerflow()
    alarms = 0
    for _ in range(trials):
        z = z_true + rng.normal(0, sigma)
        _, _, J, _ = ac.estimate(z, sigma, x0=x0)
        alarms += J > thr
    # Design false-alarm rate 1 %. The exact binomial 99.9 % interval for 400 trials must contain it.
    ci = binomtest(alarms, trials).proportion_ci(confidence_level=0.999)
    assert ci.low <= 0.01 <= ci.high


def test_observability_is_reported(case14_ac):
    ac, sigma = case14_ac
    observable, cond = ac.observable(sigma)
    assert observable and cond < 1e8


# ---------------------------------------------------------------- FDIA

def test_dc_stealthy_attack_leaves_residual_exactly_invariant():
    res = study.dc_invariance_check("case14")
    assert res["stealthy_feasible"] and res["attacked_rows"] > 0
    assert res["abs_change_J_stealthy"] < 1e-8
    assert res["bound_ok"]
    assert not res["stealthy_detected"]
    assert res["random_detected"]


def test_stealthy_attack_is_confined_to_compromised_rows_and_bound():
    s = study.setup("case14")
    ac, tel = s["ac"], s["telemetry"]
    comp = telemetry.compromised_mask(tel)
    z = ac.h(ac.state_from_powerflow())
    x0 = ac.state_from_powerflow()
    att = fdia.stealthy_attack(ac.jacobian(x0), z, comp)
    assert att.feasible
    assert np.all(att.a[~comp] == 0.0)
    assert fdia.bound_satisfied(att.a, z, comp, fdia.BUDGET)


def test_no_stealthy_direction_when_uncompromised_rows_determine_state():
    # Two uncompromised rows already pin both states, so no state change is invisible to them.
    H = np.array([[1.0, 0.0], [0.0, 1.0], [1.0, 1.0]])
    z = np.array([1.0, 1.0, 2.0])
    comp = np.array([True, False, False])
    att = fdia.stealthy_attack(H, z, comp)
    assert not att.feasible


def test_ac_stealthy_attack_is_nearly_invariant_and_bypasses():
    df, meta = study.ac_monte_carlo("case14", trials=25, seed=3)
    feas = df[df.stealthy_feasible]
    assert len(feas) == 25
    assert feas.J_change_over_threshold.median() < 1e-3
    assert feas.stealthy_bypass.mean() >= 0.9
    assert df.random_detected.mean() == 1.0


# ---------------------------------------------------------------- cyber graph and telemetry

def test_cyber_graph_reachability_matches_exploitable_links():
    model = cyber.build_cyber_model(4)
    assert model.compromised_rtus() == ["RTU-01", "RTU-02"]
    path = model.attack_path("RTU-01")
    assert path[0] == cyber.ENTRY_POINT and path[-1] == "RTU-01"
    assert model.attack_path("RTU-03") is None


def test_cyber_graph_carries_no_electrical_quantities():
    model = cyber.build_cyber_model(6)
    keys = {k for _, _, d in model.graph.edges(data=True) for k in d}
    assert keys <= {"exploitable", "label"}


def test_cutting_the_breach_point_removes_every_rtu():
    model = cyber.build_cyber_model(4)
    model.graph["IT-Email"]["IT-Historian"]["exploitable"] = False
    assert model.compromised_rtus() == []


def test_telemetry_table_is_consistent():
    s = study.setup("case30")
    tel, ac = s["telemetry"], s["ac"]
    assert len(tel) == ac.m
    assert tel.sensor_id.is_unique
    assert set(tel.compromised_flag) <= {True, False}
    assert (tel.compromised_flag == tel.rtu_id.isin(s["compromised"])).all()
    assert set(tel.measurement_type) == {"V", "P_inj", "Q_inj", "P_flow", "Q_flow"}
    assert (tel.noise_coefficient > 0).all()


# ---------------------------------------------------------------- operating points and continuation

def test_base_case_is_normal_and_divergence_is_not_a_physical_state():
    op = operating_point.classify(load_case("case14"))
    assert op.status == "S0" and abs(op.max_loading - 0.6) < 1e-6
    diverged = operating_point.OperatingPoint("SOLVER_DIVERGENCE", float("nan"), float("nan"))
    assert not diverged.physical


def test_classifier_separates_divergence_from_voltage_instability():
    net = load_case("case14")
    base = operating_point.scale_loads(net, 1.0)
    operating_point.scale_loads(net, 6.0, base)   # far beyond the nose: the solver must fail
    op = operating_point.classify(net)
    assert op.status == "SOLVER_DIVERGENCE"


def test_continuation_locates_voltage_limit_before_nose():
    net = load_case("case14")
    table, summary = operating_point.continuation(net, alpha_start=1.0, alpha_max=6.0, step=0.02)
    assert summary["voltage_limit_alpha"] is not None
    assert summary["nose_alpha"] is not None
    assert summary["voltage_limit_alpha"] < summary["nose_alpha"]
    # With generator reactive limits (headline): voltage limit 1.60, nose 1.78 on case14.
    assert abs(summary["voltage_limit_alpha"] - 1.60) < 0.02
    assert abs(summary["nose_alpha"] - 1.78) < 0.02


def test_unlimited_reactive_power_overstates_loadability():
    from backend.grid import cases
    limited = operating_point.continuation(load_case("case14"), alpha_start=1.0, alpha_max=6.0, step=0.02)[1]
    previous = cases.ENFORCE_Q_LIMS
    try:
        cases.ENFORCE_Q_LIMS = False
        free = operating_point.continuation(load_case("case14"), alpha_start=1.0, alpha_max=6.0, step=0.02)[1]
    finally:
        cases.ENFORCE_Q_LIMS = previous
    assert free["nose_alpha"] - limited["nose_alpha"] > 2.0   # 4.06 unlimited against 1.78 limited
    assert free["voltage_limit_alpha"] - limited["voltage_limit_alpha"] > 1.5


# ---------------------------------------------------------------- MDP

@pytest.fixture(scope="module")
def case14_mdp():
    cal = mdp.calibrate("case14")
    bus = mdp.most_critical_bus(load_case("case14"))
    outcomes = mdp.compute_outcomes("case14", cal, bus=bus)
    return cal, bus, outcomes


def test_transition_rows_are_probabilities(case14_mdp):
    cal, bus, outcomes = case14_mdp
    m = mdp.build_mdp("case14", cal, bus=bus, outcomes=outcomes)
    assert np.all(m.P >= -1e-12)
    assert np.allclose(m.P.sum(axis=2), 1.0)
    assert np.all(m.P[:, 3, 3] == 1.0)  # S3 absorbing


def test_s0_transition_matches_plan_formula(case14_mdp):
    cal, bus, outcomes = case14_mdp
    m = mdp.build_mdp("case14", cal, bus=bus, outcomes=outcomes)
    a = mdp.ACTIONS.index("DO_NOTHING")
    lam = outcomes[("S0", "DO_NOTHING")]["loading"]
    expected = 1 / (1 + np.exp(-10.0 * (lam - 0.80)))
    assert abs(m.P[a, 0, 1] - expected) < 1e-12


def test_reward_uses_plan_weights(case14_mdp):
    cal, bus, outcomes = case14_mdp
    m = mdp.build_mdp("case14", cal, bus=bus, outcomes=outcomes)
    a = mdp.ACTIONS.index("LOAD_SHED")
    res = outcomes[("S0", "LOAD_SHED")]
    overload = max(0.0, res["loading"] - 1.0)
    sag = max(0.0, mdp.V_REF - res["min_vm"])
    expected = -(10.0 * overload ** 2 + 5.0 * sag ** 2 + 1.0 * res["cost"])
    assert abs(m.R[0, a] - expected) < 1e-12


def test_isolation_cost_is_a_fraction_and_shedding_is_twenty_percent(case14_mdp):
    _, _, outcomes = case14_mdp
    assert abs(outcomes[("S1", "LOAD_SHED")]["cost"] - mdp.SHED_FRACTION) < 1e-12
    assert 0.0 < outcomes[("S1", "ISOLATE_NODE")]["cost"] <= 1.0


def test_value_iteration_converges_and_is_nonpositive(case14_mdp):
    cal, bus, outcomes = case14_mdp
    m = mdp.build_mdp("case14", cal, bus=bus, outcomes=outcomes)
    vi = mdp.value_iteration(m)
    assert vi["converged"]
    assert np.all(vi["V"] <= 1e-12)
    h = np.array(vi["history"])
    assert h[-1] < 1e-10


def test_finite_horizon_approaches_infinite_horizon(case14_mdp):
    cal, bus, outcomes = case14_mdp
    m = mdp.build_mdp("case14", cal, bus=bus, outcomes=outcomes)
    vi = mdp.value_iteration(m)
    errors = [np.max(np.abs(mdp.finite_horizon(m, T)["V"] - vi["V"])) for T in (5, 40, 160)]
    assert errors[0] > errors[1] > errors[2]
    assert errors[2] < 0.1


def test_plan_weights_keep_do_nothing_optimal_in_thermal_state(case14_mdp):
    cal, bus, outcomes = case14_mdp
    m = mdp.build_mdp("case14", cal, bus=bus, outcomes=outcomes, w=(10.0, 5.0, 1.0))
    vi = mdp.value_iteration(m)
    assert vi["policy"][2] == "DO_NOTHING"
    cheap = mdp.build_mdp("case14", cal, bus=bus, outcomes=outcomes, w=(10.0, 5.0, 0.01))
    assert mdp.value_iteration(cheap)["policy"][2] != "DO_NOTHING"
