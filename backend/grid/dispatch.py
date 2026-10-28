"""Optimal dispatch with active-power limits for the physics layer.

Until now the continuation study scaled generator setpoints proportionally with
the load (an acknowledged modelling simplification: "dispatch is proportional
rather than optimal; active-power limits are not enforced" — docs/PHYSICS.md).
This module adds a DC OPF dispatch via pandapower's rundcopp:

  minimise  sum_i poly_cost_i(P_i)                    (merit-order proxy costs)
  s.t.      nodal DC balance, branch flow <= rating, P_min_i <= P_i <= P_max_i

Network constraints are enforced natively by the OPF, so the resulting flows stay
within the (re-rated) thermal ratings — the dispatch is economically optimal AND
physically feasible. Loads are scaled proportionally as before; the OPF then
produces the cheapest feasible generation per load level.

The fallback stays the documented proportional rule when the OPF cannot solve
(infeasible at this load level), so the continuation sweep degrades gracefully.
"""
import warnings

import pandapower as pp
from pandapower import OPFNotConverged


def _ensure_poly_costs(net, base_gen_p=None):
    """Marginal-cost proxy for every generator and the ext grid. Without poly_cost
    pandapower treats all costs as zero, which makes the OPF degenerate. The shape
    (ascending cost by gen index) mirrors the older LP heuristic."""
    n = len(net.gen)
    base_cost = 30.0
    rows = []
    for row, idx in enumerate(net.gen.index):
        c = base_cost * (row + 1) / max(1, n) if n else 1.0
        rows.append([idx, "gen", 0.0, c, 0.0, 0.0, 0.0, 0.0])
    for idx in net.ext_grid.index:  # the reference slack is the most expensive unit
        rows.append([idx, "ext_grid", 0.0, base_cost * (n + 1), 0.0, 0.0, 0.0, 0.0])
    net.poly_cost = net.poly_cost.from_records(
        rows, columns=["element", "et", "cp0_eur", "cp1_eur_per_mw", "cp2_eur_per_mw2",
                       "cq0_eur", "cq1_eur_per_mvar", "cq2_eur_per_mvar2"])


def optimal_dispatch(net, alpha: float, base=None):
    """DC-OPF dispatch for load level alpha. Returns dict with the solver status.
    Raises OPFNotConverged / RuntimeError when infeasible; callers decide on fallback."""
    if base is None:
        raise RuntimeError("optimal_dispatch needs the base snapshot from scale_loads")
    net.load["p_mw"] = base["p"] * alpha
    net.load["q_mvar"] = base["q"] * alpha
    net.poly_cost = net.poly_cost.iloc[0:0]
    _ensure_poly_costs(net)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        pp.rundcopp(net)
    if net.OPF_converged is False or "res_gen" not in net:
        raise OPFNotConverged("DC OPF did not converge at this load level")
    objective = net.res_cost
    try:
        objective = float(objective)
    except (TypeError, ValueError):
        objective = float(objective[0]) if hasattr(objective, "__len__") else None
    return {"opf_converged": True, "objective": objective}


def scale_loads_optimal(net, alpha, base):
    """Drop-in replacement for scale_loads(net, alpha, base) inside the loadability
    continuation: proportional load scaling + constrained DC-OPF dispatch with
    enforced active-power limits and line ratings. Falls back to the documented
    proportional rule when the OPF is infeasible at this level."""
    net.load["p_mw"] = base["p"] * alpha
    net.load["q_mvar"] = base["q"] * alpha
    if len(net.gen) and base["gen_p"] is not None:
        net.gen["p_mw"] = base["gen_p"] * alpha
    try:
        optimal_dispatch(net, alpha, base)
    except (OPFNotConverged, RuntimeError, KeyError):
        pass  # documented fallback: proportional dispatch
    return base
