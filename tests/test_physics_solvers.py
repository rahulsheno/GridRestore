"""Tests for the analytic Jacobian, the Newton power flow and the predictor-corrector continuation.

Each solver is checked against an independent reference: the numerical Jacobian, pandapower's own power
flow solved from a flat start, and pandapower's bisection on the load factor.
"""
import warnings

import numpy as np
import pytest

from backend.grid import pflow
from backend.grid.ac_se import ACModel
from backend.grid.cases import load_case
from backend.grid.operating_point import continuation

warnings.simplefilter("ignore")


@pytest.mark.parametrize("case", ["case9", "case14", "case30", "case57", "case118"])
def test_analytic_jacobian_matches_numerical(case):
    ac = ACModel(load_case(case))
    rng = np.random.default_rng(3)
    x = ac.state_from_powerflow() + rng.normal(0, 0.01, size=ac.p)
    Ha, Hn = ac.jacobian(x), ac.jacobian_numerical(x)
    assert np.max(np.abs(Ha - Hn)) / np.max(np.abs(Hn)) < 1e-7


def _flat_state(net, ac, inj):
    st = pflow.State(theta=np.zeros(ac.n), vm=np.ones(ac.n), pq=np.ones(ac.n, dtype=bool),
                     qfix=np.full(ac.n, np.nan))
    st.pq[ac.ref] = False
    st.pq[inj.has_gen] = False
    return st


@pytest.mark.parametrize("case", ["case9", "case14", "case30", "case118"])
def test_newton_from_flat_start_reproduces_pandapower(case):
    net = load_case(case)
    ac = ACModel(net)
    inj = pflow.injections_from_net(net, ac)
    pf = pflow.PowerFlow(net, ac, inj)
    st = pf.solve(pf.set_setpoints(_flat_state(net, ac, inj)), 1.0)
    rows = [int(net._pd2ppc_lookups["bus"][b]) for b in net.bus.index]
    vm_pp = np.array([net.res_bus.vm_pu.loc[b] for b in net.bus.index])
    va_pp = np.array([np.deg2rad(net.res_bus.va_degree.loc[b]) for b in net.bus.index])
    assert np.max(np.abs(st.vm[rows] - vm_pp)) < 1e-8
    assert np.max(np.abs(st.theta[rows] - va_pp)) < 1e-8


def test_base_case_reactive_limit_switches_match_pandapower_on_case118():
    net = load_case("case118")
    ac = ACModel(net)
    inj = pflow.injections_from_net(net, ac)
    pf = pflow.PowerFlow(net, ac, inj)
    st = pf.solve(pf.set_setpoints(_flat_state(net, ac, inj)), 1.0)
    # pandapower's enforce_q_lims converts the same generator buses to PQ (six of them on case118)
    qg = pf.generator_q(st, 1.0)
    assert len(st.switched) == 6
    assert np.all(qg[st.switched] <= inj.qmax[st.switched] + 1e-9) or np.all(qg[st.switched] >= inj.qmin[st.switched] - 1e-9)


def _trace(case):
    net = load_case(case)
    ac = ACModel(net)
    pf = pflow.PowerFlow(net, ac, pflow.injections_from_net(net, ac))
    return pflow.trace(pf, lam_start=1.0, lam_max=8.0)


@pytest.mark.parametrize("case,nose_ref,voltage_ref", [
    ("case9", 2.4673, 1.78), ("case14", 1.7780, 1.60), ("case30", 2.8538, 2.46),
])
def test_predictor_corrector_matches_fresh_start_bisection(case, nose_ref, voltage_ref):
    _, summary = _trace(case)
    assert summary["nose_alpha"] is not None
    assert abs(summary["nose_alpha"] - nose_ref) < 0.01
    # The voltage limit is interpolated between traced points, so it agrees to about 0.01.
    assert abs(summary["voltage_limit_alpha"] - voltage_ref) < 0.02


@pytest.mark.parametrize("case", ["case9", "case14", "case30", "case118"])
def test_bisection_is_path_independent_with_flat_start(case):
    """Bisection evaluated in opposite orders gives the same nose (warm starts used to make it path-dependent)."""
    net = load_case(case)
    table, summary = continuation(net, alpha_start=1.0, alpha_max=6.0, step=0.02)
    table_b, summary_b = continuation(load_case(case), alpha_start=1.0, alpha_max=6.0, step=0.02)
    assert summary["nose_alpha"] == pytest.approx(summary_b["nose_alpha"], abs=1e-6)


def test_case118_trace_follows_the_base_connected_branch():
    """The traced nose (2.1106) is the point where warm-started stepping from the base case also stops (2.110649)."""
    _, summary = _trace("case118")
    assert abs(summary["nose_alpha"] - 2.1106) < 0.002


def test_case118_bisection_reports_a_different_branch():
    """Documents the finding in docs/PHYSICS.md section 5.8: the flat-start bisection lands on another solution."""
    net = load_case("case118")
    _, bis = continuation(net, alpha_start=1.0, alpha_max=6.0, step=0.02)
    _, traced = _trace("case118")
    assert abs(bis["nose_alpha"] - 2.1401) < 0.01
    assert bis["nose_alpha"] - traced["nose_alpha"] > 0.02
