"""Experiments: DC invariance check and AC Monte Carlo for stealthy FDIA versus the chi-squared test."""
import warnings

import numpy as np
import pandas as pd
import networkx as nx
from scipy.stats import chi2

from .ac_se import ACModel
from .cases import load_case
from .cyber import assign_buses_to_rtus, build_cyber_model
from .dc_model import DCModel
from .fdia import BUDGET, bound_satisfied, random_attack, stealthy_attack
from .telemetry import build_telemetry, compromised_mask, sigma_vector


def setup(case, n_rtus=4, exposed_rtus=None):
    """Network, AC model, cyber graph, RTU assignment and telemetry table for one IEEE case."""
    net = load_case(case)
    ac = ACModel(net)
    cyber = build_cyber_model(n_rtus, exposed_rtus)
    g = nx.Graph()
    g.add_nodes_from(range(ac.n))
    g.add_edges_from(zip(ac.f.tolist(), ac.t.tolist()))
    bus_rtu = assign_buses_to_rtus(g, ac.n, n_rtus)
    compromised = cyber.compromised_rtus()
    telemetry = build_telemetry(ac, bus_rtu, compromised)
    return {"net": net, "ac": ac, "cyber": cyber, "bus_rtu": bus_rtu,
            "compromised": compromised, "telemetry": telemetry}


def dc_invariance_check(case, n_rtus=4, seed=20261018, sigma=0.02):
    """Linear-model check: a = H c with H_U c = 0 must leave J exactly unchanged."""
    warnings.simplefilter("ignore")
    rng = np.random.default_rng(seed)
    s = setup(case, n_rtus)
    net = s["net"]
    dc = DCModel(net)
    p = dc.n - 1
    # DC measurement matrix: branch flows (m rows) then non-slack injections (p rows)
    H_flow = dc.D @ dc.A_r
    H_inj = dc.B_r
    H = np.vstack([H_flow, H_inj])
    # compromised flags for these rows, taken from the AC telemetry (flow from-bus RTU, injection bus RTU)
    tel = s["telemetry"]
    flow_rows = tel[tel.measurement_type == "P_flow"].sort_values("ppc_row")
    flag_flow = flow_rows.compromised_flag.to_numpy(bool)
    inj_rows = tel[tel.measurement_type == "P_inj"].sort_values("ppc_row")
    flag_inj = inj_rows.compromised_flag.to_numpy(bool)[np.isin(inj_rows.ppc_row.to_numpy(), [r for r in range(dc.n) if r != dc.slack_row])]
    comp = np.concatenate([flag_flow, flag_inj])
    theta = rng.normal(0, 0.05, size=p)
    z = H @ theta
    z = z + rng.normal(0, sigma, size=len(z))
    W = np.full(len(z), 1 / sigma ** 2)

    def wls(zv):
        G = H.T @ (W[:, None] * H)
        th = np.linalg.solve(G, H.T @ (W * zv))
        r = zv - H @ th
        return float(np.sum(W * r * r))

    J0 = wls(z)
    att = stealthy_attack(H, z, comp)
    J1 = wls(z + att.a)
    rnd = random_attack(z, comp, rng)
    J2 = wls(z + rnd)
    thr = float(chi2.ppf(0.99, len(z) - p))
    return {"case": case, "measurements": len(z), "states": p, "attacked_rows": int(att.rows.sum()),
            "stealthy_feasible": att.feasible, "J_clean": J0, "J_stealthy": J1,
            "abs_change_J_stealthy": abs(J1 - J0), "J_random": J2, "chi2_threshold": thr,
            "stealthy_detected": J1 > thr, "random_detected": J2 > thr,
            "bound_ok": bound_satisfied(att.a, z, comp, BUDGET) if att.feasible else None}


def ac_monte_carlo(case, trials=100, n_rtus=4, seed=20261018, exposed_rtus=None):
    """Per-trial AC results: clean false alarm, stealthy bypass, and random-attack detection."""
    warnings.simplefilter("ignore")
    rng = np.random.default_rng(seed)
    s = setup(case, n_rtus, exposed_rtus)
    ac, tel = s["ac"], s["telemetry"]
    sigma = sigma_vector(tel)
    comp = compromised_mask(tel)
    x_true = ac.state_from_powerflow()
    z_true = ac.h(x_true)
    thr = ac.chi2_threshold(0.01)
    rows = []
    for t in range(trials):
        z = z_true + rng.normal(0, sigma)
        x0, _, J0, _ = ac.estimate(z, sigma)
        H0 = ac.jacobian(x0)
        att = stealthy_attack(H0, z, comp)
        row = {"trial": t, "J_clean": J0, "clean_alarm": J0 > thr, "stealthy_feasible": att.feasible,
               "attacked_rows": int(att.rows.sum()), "threshold": thr}
        if att.feasible:
            xa, _, Ja, _ = ac.estimate(z + att.a, sigma, x0=x0)
            hx0, hxa = ac.h(x0), ac.h(xa)
            # Largest change in an estimated branch flow or voltage that the operator would see
            shift_flow = float(np.max(np.abs(hxa[3 * ac.n:] - hx0[3 * ac.n:])))
            row.update({"J_stealthy": Ja, "stealthy_bypass": Ja <= thr,
                        "J_change_over_threshold": abs(Ja - J0) / thr,
                        "state_shift_inf": float(np.max(np.abs(xa - x0))),
                        "max_estimate_flow_shift_pu": shift_flow,
                        "attack_max_abs_pu": float(np.max(np.abs(att.a))),
                        "bound_ok": bound_satisfied(att.a, z, comp)})
        a_rand = random_attack(z, comp, rng)
        _, _, Jr, _ = ac.estimate(z + a_rand, sigma, x0=x0)
        row.update({"J_random": Jr, "random_detected": Jr > thr})
        rows.append(row)
    return pd.DataFrame(rows), {"case": case, "buses": ac.n, "measurements": ac.m, "states": ac.p,
                                "compromised_rtus": s["compromised"], "rtus": n_rtus, "threshold": thr}


def summarise(df, meta):
    feas = df[df.stealthy_feasible]
    out = dict(meta)
    out.update({
        "trials": len(df),
        "clean_false_alarm_rate": float(df.clean_alarm.mean()),
        "stealthy_feasible_rate": float(df.stealthy_feasible.mean()),
        "stealthy_bypass_rate": float(feas.stealthy_bypass.mean()) if len(feas) else None,
        "median_J_change_over_threshold": float(feas.J_change_over_threshold.median()) if len(feas) else None,
        "median_state_shift_rad_or_pu": float(feas.state_shift_inf.median()) if len(feas) else None,
        "median_flow_shift_pu": float(feas.max_estimate_flow_shift_pu.median()) if len(feas) else None,
        "random_attack_detection_rate": float(df.random_detected.mean()),
    })
    return out


LNR_THRESHOLD = 3.0   # standard largest-normalised-residual threshold


def _lnr_flags(ac, z, x, sigma):
    from .ac_se import normalized_residuals
    return float(normalized_residuals(ac, z, x, sigma).max())


def targeted_monte_carlo(case, trials=50, n_rtus=4, seed=20261018, exposed_rtus=None):
    """Per trial: pick the branch flow the targeted attack can move most (linear programme for each branch),
    apply the attack, re-estimate with Gauss-Newton and record the achieved shift against the prediction.
    Also records the effect of the max-energy attack on the same branch, for comparison."""
    from .fdia import targeted_attack
    warnings.simplefilter("ignore")
    rng = np.random.default_rng(seed)
    s = setup(case, n_rtus, exposed_rtus)
    ac, tel = s["ac"], s["telemetry"]
    sigma = sigma_vector(tel)
    comp = compromised_mask(tel)
    z_true = ac.h(ac.state_from_powerflow())
    thr = ac.chi2_threshold(0.01)
    rows = []
    for t in range(trials):
        z = z_true + rng.normal(0, sigma)
        x0, _, J0, _ = ac.estimate(z, sigma)
        H0 = ac.jacobian(x0)
        best = None
        for k in range(ac.nbr):
            row = 3 * ac.n + k
            att = targeted_attack(H0, z, comp, row)
            if att.feasible:
                lin = abs(float(H0[row] @ att.c))
                if best is None or lin > best[1]:
                    best = (k, lin, att)
        if best is None:
            rows.append({"trial": t, "feasible": False})
            continue
        k, lin, att = best
        row = 3 * ac.n + k
        xa, _, Ja, _ = ac.estimate(z + att.a, sigma, x0=x0)
        h0, ha = ac.h(x0), ac.h(xa)
        ms = stealthy_attack(H0, z, comp)
        xm, _, _, _ = ac.estimate(z + ms.a, sigma, x0=x0)
        hm = ac.h(xm)
        rows.append({"trial": t, "feasible": True, "target_branch": k,
                     "linear_prediction_pu": lin, "achieved_shift_pu": float(ha[row] - h0[row]),
                     "max_energy_shift_pu": float(hm[row] - h0[row]),
                     "J_targeted": Ja, "targeted_bypass": Ja <= thr,
                     "lnr_targeted": _lnr_flags(ac, z + att.a, xa, sigma),
                     "lnr_detected": _lnr_flags(ac, z + att.a, xa, sigma) > LNR_THRESHOLD})
    df = pd.DataFrame(rows)
    feas = df[df.feasible.astype(bool)] if len(df) else df
    summary = {"case": case, "trials": trials, "feasible": int(len(feas)),
               "median_linear_prediction_pu": float(feas.linear_prediction_pu.median()) if len(feas) else None,
               "median_achieved_shift_pu": float(feas.achieved_shift_pu.abs().median()) if len(feas) else None,
               "median_max_energy_shift_pu": float(feas.max_energy_shift_pu.abs().median()) if len(feas) else None,
               "targeted_bypass_rate": float(feas.targeted_bypass.mean()) if len(feas) else None,
               "targeted_lnr_detection_rate": float(feas.lnr_detected.mean()) if len(feas) else None}
    return df, summary


def lnr_summary(case, trials=50, n_rtus=4, seed=20261018):
    """Largest-normalised-residual detection of random and stealthy attacks, against the 3.0 threshold."""
    warnings.simplefilter("ignore")
    rng = np.random.default_rng(seed)
    s = setup(case, n_rtus)
    ac, tel = s["ac"], s["telemetry"]
    sigma = sigma_vector(tel)
    comp = compromised_mask(tel)
    z_true = ac.h(ac.state_from_powerflow())
    clean, stealth, rand = [], [], []
    for _ in range(trials):
        z = z_true + rng.normal(0, sigma)
        x0, _, _, _ = ac.estimate(z, sigma)
        clean.append(_lnr_flags(ac, z, x0, sigma))
        att = stealthy_attack(ac.jacobian(x0), z, comp)
        if att.feasible:
            xa, _, _, _ = ac.estimate(z + att.a, sigma, x0=x0)
            stealth.append(_lnr_flags(ac, z + att.a, xa, sigma))
        a_r = random_attack(z, comp, rng)
        xr, _, _, _ = ac.estimate(z + a_r, sigma, x0=x0)
        rand.append(_lnr_flags(ac, z + a_r, xr, sigma))
    clean, stealth, rand = map(np.array, (clean, stealth, rand))
    return {"case": case, "trials": trials, "lnr_threshold": LNR_THRESHOLD,
            "lnr_false_alarm_rate_clean": float((clean > LNR_THRESHOLD).mean()),
            "lnr_detection_rate_stealthy": float((stealth > LNR_THRESHOLD).mean()) if len(stealth) else None,
            "lnr_detection_rate_random": float((rand > LNR_THRESHOLD).mean()),
            "median_lnr_stealthy": float(np.median(stealth)) if len(stealth) else None,
            "median_lnr_random": float(np.median(rand))}
