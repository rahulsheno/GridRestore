"""Telemetry mapping: one row per measurement, linking the physical model to the cyber attack.

Columns:
    sensor_id          unique measurement ID (M000, M001, ...), same order as ACModel.meas
    measurement_type   V (voltage magnitude), P_inj, Q_inj (bus injections), P_flow, Q_flow (branch, from end)
    pp_bus             pandapower bus index for V / P_inj / Q_inj, else NaN
    pp_branch          "line" or "trafo" for flows, else None
    pp_branch_idx      pandapower element index for flows, else NaN
    ppc_row            row in the ppc bus or branch table (used by the estimator)
    rtu_id             field RTU that reports the measurement (from the bus assignment)
    noise_coefficient  standard deviation sigma in per unit (the diagonal of R, square-rooted)
    compromised_flag   True if the RTU is compromised by the cyber attack
    z_true             noise-free value from the power-flow solution (per unit)
"""
import numpy as np
import pandas as pd

from .cases import locate_branch

SIGMA = {"V": 0.004, "P_inj": 0.02, "Q_inj": 0.02, "P_flow": 0.02, "Q_flow": 0.02}


def build_telemetry(ac, bus_rtu, compromised_rtus, sigma=SIGMA):
    """ac: ACModel; bus_rtu: list of RTU names per ppc bus row; compromised_rtus: iterable of RTU names."""
    net = ac.net
    n, nb = ac.n, ac.nbr
    comp = set(compromised_rtus)
    z = ac.h(ac.state_from_powerflow())
    rows = []
    kinds = (["V"] * n) + (["P_inj"] * n) + (["Q_inj"] * n) + (["P_flow"] * nb) + (["Q_flow"] * nb)
    for i, meas in enumerate(ac.meas):
        kind = kinds[i]
        if meas.kind in ("V", "P", "Q"):
            ppc_row = meas.index
            pp_bus = int(_pp_bus_of_row(net, ppc_row))
            rtu = bus_rtu[ppc_row]
            pp_branch, pp_branch_idx = None, np.nan
        else:
            ppc_row = int(ac.branch_rows[meas.index])
            pp_branch, local = locate_branch(net, ppc_row)
            pp_bus = np.nan
            # the RTU that owns a flow is the one owning its from-bus
            from_row = int(ac.f[meas.index])
            rtu = bus_rtu[from_row]
            pp_branch_idx = local
        rows.append({
            "sensor_id": f"M{i:03d}",
            "measurement_type": kind,
            "pp_bus": pp_bus,
            "pp_branch": pp_branch,
            "pp_branch_idx": pp_branch_idx,
            "ppc_row": ppc_row,
            "rtu_id": rtu,
            "noise_coefficient": sigma[kind],
            "compromised_flag": rtu in comp,
            "z_true": float(z[i]),
        })
    return pd.DataFrame(rows)


def _pp_bus_of_row(net, ppc_row):
    for pp_bus in net.bus.index:
        if int(net._pd2ppc_lookups["bus"][pp_bus]) == ppc_row:
            return pp_bus
    raise KeyError(ppc_row)


def sigma_vector(telemetry):
    return telemetry["noise_coefficient"].to_numpy(dtype=float)


def compromised_mask(telemetry):
    return telemetry["compromised_flag"].to_numpy(dtype=bool)
