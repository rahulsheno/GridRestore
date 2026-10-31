"""Operating-point classification and loadability limits.

Failure modes are kept apart on purpose:

  SOLVER_DIVERGENCE  pandapower's Newton-Raphson did not converge (LoadflowNotConverged). This is a
                     numerical outcome, not a statement about the physical system. It is never
                     counted as a physical state.
  S0  normal         converged, max branch loading < 80 %, minimum voltage >= 0.85 pu
  S1  stressed       converged, 80 % <= max loading < 100 %, and voltage >= 0.85 pu
  S2  thermal        converged, max loading >= 100 % (branch overload), voltage >= 0.85 pu
  S3  voltage        converged, minimum voltage < 0.85 pu (voltage instability limit)

Priority when a converged point meets several conditions: S3 > S2 > S1 > S0. The 0.85 pu voltage
limit and the 80 % / 100 % loading limits are modelling assumptions set by the plan; they are not
quoted from a regulation.

Loadability limit: `continuation` scales all loads by a factor alpha and records the state at each
step. It locates the boundary by bisection. This is a load-scaling sweep, not a predictor-corrector
continuation power flow, so it approximates the PV-curve nose point rather than tracing it exactly.
"""
import warnings
from dataclasses import dataclass

import numpy as np
import pandas as pd
import pandapower as pp
from pandapower.auxiliary import LoadflowNotConverged

from .cases import run_powerflow

LOAD_NORMAL = 0.80
LOAD_OVERLOAD = 1.00
VOLTAGE_LIMIT = 0.85
STATE_NAMES = {"S0": "normal", "S1": "stressed", "S2": "thermal overload", "S3": "voltage instability",
               "SOLVER_DIVERGENCE": "numerical non-convergence"}


@dataclass
class OperatingPoint:
    status: str
    max_loading: float   # fraction of rating (1.0 = 100 %)
    min_vm: float        # per unit

    @property
    def physical(self):
        return self.status in ("S0", "S1", "S2", "S3")


def solve(net):
    """Run AC power flow (with the module-wide Q-limit setting); True if converged. Never raises."""
    try:
        run_powerflow(net)
        return True
    except LoadflowNotConverged:
        return False


def classify(net):
    if not solve(net):
        return OperatingPoint("SOLVER_DIVERGENCE", float("nan"), float("nan"))
    loading = float(net.res_line.loading_percent.max()) / 100.0
    if len(net.trafo):
        loading = max(loading, float(net.res_trafo.loading_percent.max()) / 100.0)
    vm_min = float(net.res_bus.vm_pu[net.bus.in_service].min())
    if vm_min < VOLTAGE_LIMIT:
        status = "S3"
    elif loading >= LOAD_OVERLOAD:
        status = "S2"
    elif loading >= LOAD_NORMAL:
        status = "S1"
    else:
        status = "S0"
    return OperatingPoint(status, loading, vm_min)


def scale_loads(net, alpha, base=None):
    """Proportional scaling: loads (P and Q) and non-slack generator P setpoints are all multiplied by alpha
    relative to the base values stored in `base`. The slack bus then supplies only the losses.

    Scaling only the loads (generator setpoints fixed) makes the slack absorb the surplus. On case30 at
    alpha = 0.5 that gave -69.5 MW through the slack and a reverse-flow line at 485 % loading: a
    dispatch artifact, not physical stress.
    """
    if base is None:
        base = {"p": net.load.p_mw.copy(), "q": net.load.q_mvar.copy(),
                "gen_p": net.gen.p_mw.copy() if len(net.gen) else None}
    net.load["p_mw"] = base["p"] * alpha
    net.load["q_mvar"] = base["q"] * alpha
    if len(net.gen) and base["gen_p"] is not None:
        net.gen["p_mw"] = base["gen_p"] * alpha
    return base


def continuation(net, alpha_start=1.0, alpha_max=6.0, step=0.02, tol=1e-4, dispatch="proportional"):
    """Load-scaling sweep from alpha_start upward. Returns (table, summary).

    dispatch: "proportional" (default, historical behaviour) or "optimal"
    (constrained DC-OPF via backend/grid/dispatch.py: merit-order costs with
    generator P limits and line ratings enforced; falls back to proportional
    when the OPF is infeasible at a level).

    The sweep continues past the voltage limit until pandapower no longer converges, so both points
    are located:
      voltage_limit_alpha  last alpha before min voltage first drops below 0.85 pu (S3 threshold)
      nose_alpha           last alpha with a converged solution, before the first divergence
                           (the PV-curve nose, to within `tol`, by bisection)
    The table records every evaluated point, so the curve can be plotted.
    """
    from .dispatch import scale_loads_optimal
    if dispatch not in ("proportional", "optimal"):
        raise ValueError(f"Unknown dispatch mode: {dispatch!r}")
    scale = scale_loads_optimal if dispatch == "optimal" else scale_loads
    base = scale_loads(net, 1.0)
    rows = []

    def evaluate(alpha):
        scale(net, alpha, base)
        op = classify(net)
        rows.append({"alpha": round(alpha, 6), "status": op.status,
                     "max_loading": op.max_loading, "min_vm": op.min_vm})
        return op

    def converged(op):
        return op.status != "SOLVER_DIVERGENCE"

    alpha = alpha_start
    last_converged = None
    first_divergence = None
    while alpha <= alpha_max + 1e-12:
        op = evaluate(alpha)
        if converged(op):
            last_converged = alpha
        else:
            first_divergence = alpha
            break
        alpha = round(alpha + step, 6)
    nose = None
    if first_divergence is not None and last_converged is not None:
        lo, hi = last_converged, first_divergence
        while hi - lo > tol:
            mid = 0.5 * (lo + hi)
            if converged(evaluate(mid)):
                lo = mid
            else:
                hi = mid
        nose = lo
    table = pd.DataFrame(rows).sort_values("alpha").drop_duplicates("alpha").reset_index(drop=True)
    scale_loads(net, 1.0, base)  # restore the base snapshot (always the proportional rule)
    first = {}
    for status in ["S2", "S3", "SOLVER_DIVERGENCE"]:
        hit = table[table.status == status]
        first[status] = float(hit.alpha.min()) if len(hit) else None
    voltage_limit = None
    if first["S3"] is not None:
        ok_before = table[(table.alpha < first["S3"]) & (table.status != "SOLVER_DIVERGENCE")]
        voltage_limit = float(ok_before.alpha.max()) if len(ok_before) else None
    summary = {
        "dispatch": dispatch,
        "voltage_limit_alpha": voltage_limit,
        "nose_alpha": nose,
        "first_alpha_by_status": first,
    }
    return table, summary
