"""Benchmark networks for the physics layer.

Only the IEEE test cases bundled with pandapower are used (case9 ... case118). Distribution
networks (e.g. mv_oberrhein) are out of scope for this physics layer.

Rating assumption (explicit, see docs/PHYSICS.md):
  pandapower's bundled thermal ratings are not usable for loading studies. case14 lines run at
  1.5 % loading, and case30 already has a line at 111.8 % before any stress. We therefore re-rate every
  LINE (max_i_ka; transformers keep their ratings because sn_mva also sets their impedance) so that the base case sits at BASE_LOADING (60 %). Stress tests then move the system toward the
  80 % normal thermal limit (lambda_0 in the MDP) and beyond. The ratings are a modelling choice, not data.
"""
import warnings

import pandapower as pp
import pandapower.networks as pn

BASE_LOADING = 0.60  # base-case loading after re-rating (fraction of rating)
# Generator reactive limits. When True, pandapower's power flow holds each generator's Q within its
# min/max and lets the bus voltage float once a limit binds. Without it, generators supply any reactive
# power needed, which overstates the loadability (case14 voltage limit 3.36 unlimited vs 1.60 limited).
# Every power-flow call in backend/grid goes through run_powerflow(), so this switch changes everything.
ENFORCE_Q_LIMS = True


def run_powerflow(net):
    """AC power flow with the module-wide generator reactive-limit setting. Raises LoadflowNotConverged."""
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        # init="flat": every solve starts from the same point, so the result does not depend on the
        # sequence of earlier solves. pandapower's default warm start made bisection on the load factor
        # path-dependent (case9's nose moved by 0.02 with the order of evaluation).
        pp.runpp(net, enforce_q_lims=ENFORCE_Q_LIMS, init="flat")
CASES = ("case9", "case14", "case30", "case57", "case118")


def load_case(name, rerate=True):
    if name not in CASES:
        raise ValueError(f"unknown case {name!r}; choose from {CASES}")
    net = getattr(pn, name)()
    run_powerflow(net)
    if rerate:
        rerate_to_base_loading(net)
    return net


def rerate_to_base_loading(net, base_loading=BASE_LOADING):
    """Scale line ratings so every line is at `base_loading` in the base case."""
    run_powerflow(net)
    for idx, loading in net.res_line.loading_percent.items():
        if loading > 1e-3:
            net.line.at[idx, "max_i_ka"] = net.line.at[idx, "max_i_ka"] * (loading / 100.0) / base_loading
    # Transformers are NOT re-rated: their per-unit impedance is defined on sn_mva, so changing the
    # rating changes the electrical model (verified: the power flow diverges). Transformer loading is
    # reported as-is in base_summary.
    run_powerflow(net)
    return net


def base_summary(net):
    trafo_max = float(net.res_trafo.loading_percent.max()) if len(net.trafo) else 0.0
    return {
        "buses": len(net.bus),
        "branches": len(net.line) + len(net.trafo),
        "max_line_loading_pct": float(net.res_line.loading_percent.max()),
        "max_trafo_loading_pct": trafo_max,
        "min_vm_pu": float(net.res_bus.vm_pu.min()),
    }


def locate_branch(net, ppc_row):
    """Return (element type, pandapower index) for a row of the ppc branch table."""
    for name, (start, end) in net._pd2ppc_lookups["branch"].items():
        if start <= ppc_row < end:
            return name, int(ppc_row - start)
    raise KeyError(f"ppc branch row {ppc_row} has no pandapower element")
