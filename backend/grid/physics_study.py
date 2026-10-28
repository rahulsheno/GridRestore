"""Produce the physics-layer results: CSV artifacts in docs/physics/ and one database run.

Run:   python -m backend.grid.physics_study            (about 6 minutes; stores the run in PostgreSQL)
       python -m backend.grid.physics_study --quick    (40 trials, for a fast check; stored as mode 'quick')
       python -m backend.grid.physics_study --no-db    (artifacts only)

Headline reward weights are optimal for decision support (see mdp.HEADLINE_W); the plan's weights are
computed alongside and labelled 'plan'. Voltage collapse uses the voltage-based transition (mdp.K_VOLTAGE);
the loading-based transition is reported for comparison.
"""
import argparse
import io
import os
import time
import warnings

import numpy as np
import pandas as pd
import pandapower as pp

from .ac_se import ACModel
from .cases import load_case
from .dc_model import DCModel
from .mdp import (ACTIONS, GAMMA as GAMMA_DEFAULT, HEADLINE_W, K_VOLTAGE, PLAN_W, STATES, build_mdp,
                  calibrate, compute_outcomes, finite_horizon, most_critical_bus, value_iteration)
from . import cases as _cases
from .operating_point import continuation
from .study import (ac_monte_carlo, dc_invariance_check, lnr_summary, summarise,
                    targeted_monte_carlo)

OUT = os.path.join("docs", "physics")
IEEE = ["case9", "case14", "case30", "case57", "case118"]
MDP_CASES = ["case14", "case30"]   # case57's base case is below the 0.85 pu voltage limit (see docs)
WEIGHT_SETS = {"headline": HEADLINE_W, "plan": PLAN_W}


def _log(msg):
    """Structured log line (JSON, via backend.logging_config) so the study can be followed like the API."""
    from ..logging_config import log
    log.info(msg, extra={"event": "physics_study_step"})


# ---------------------------------------------------------------- validation

def ptdf_validation():
    rows = []
    for case in IEEE:
        net = load_case(case)
        dc = DCModel(net)
        pp.rundcpp(net)
        full = np.zeros(dc.n)
        for pp_bus in net.bus.index:
            full[int(net._pd2ppc_lookups["bus"][pp_bus])] = -net.res_bus.p_mw.loc[pp_bus] / net.sn_mva
        flows = dc.flows_from_injections(full) * net.sn_mva
        line_err, trafo_err = [], []
        for (elm, loc), f in zip(dc.branch_labels(net), flows):
            (line_err if elm == "line" else trafo_err).append(
                abs(f - (net.res_line.p_from_mw.iloc[loc] if elm == "line" else net.res_trafo.p_hv_mw.iloc[loc])))
        rows.append({"case": case, "buses": dc.n, "branches": dc.m,
                     "max_line_flow_error_MW": max(line_err) if line_err else None,
                     "max_trafo_flow_error_MW": max(trafo_err) if trafo_err else None})
    return pd.DataFrame(rows)


def measurement_model_validation():
    rows = []
    for case in IEEE:
        net = load_case(case)
        ac = ACModel(net)
        n, nb = ac.n, ac.nbr
        h = ac.h(ac.state_from_powerflow())
        ref, _ = ac.pandapower_reference()
        line_err, trafo_err = [], []
        for k, row in enumerate(ac.branch_rows):
            elm, loc = ac._locate(net, row)
            pf = h[3 * n + k] * ac.baseMVA
            if elm == "line":
                line_err.append(abs(pf - net.res_line.p_from_mw.iloc[loc]))
            else:
                trafo_err.append(abs(pf - net.res_trafo.p_hv_mw.iloc[loc]))
        rows.append({"case": case, "buses": n, "branches": nb, "measurements": ac.m, "states": ac.p,
                     "max_V_error_pu": float(np.max(np.abs(h[:n] - ref[:n]))),
                     "max_P_injection_error_pu": float(np.max(np.abs(h[n:2 * n] - ref[n:2 * n]))),
                     "max_Q_injection_error_pu": float(np.max(np.abs(h[2 * n:3 * n] - ref[2 * n:3 * n]))),
                     "max_line_flow_error_MVA": max(line_err) if line_err else None,
                     "max_trafo_flow_error_MVA": max(trafo_err) if trafo_err else None})
    return pd.DataFrame(rows)


def validation_long(ptdf, meas):
    """One row per (check, case, metric) for the database."""
    out = []
    for name, frame in [("ptdf_dc_flow", ptdf), ("ac_measurement_model", meas)]:
        for _, r in frame.iterrows():
            for metric, value in r.items():
                if metric in ("case", "buses", "branches", "measurements", "states"):
                    continue
                out.append({"check_name": name, "case_name": r["case"], "metric": metric,
                            "value": None if pd.isna(value) else float(value)})
    return pd.DataFrame(out)


# ---------------------------------------------------------------- continuation

def continuation_outputs():
    """Headline continuation uses generator reactive limits. The unlimited-Q values are kept as a comparison,
    because they overstate the loadability (see docs/PHYSICS.md)."""
    curves, summaries = [], []
    for case in IEEE:
        net = load_case(case)
        table, summary = continuation(net, alpha_start=1.0, alpha_max=6.0, step=0.02)
        table.insert(0, "case", case)
        curves.append(table)
        previous = _cases.ENFORCE_Q_LIMS
        try:
            _cases.ENFORCE_Q_LIMS = False
            _, free = continuation(load_case(case), alpha_start=1.0, alpha_max=6.0, step=0.02)
        finally:
            _cases.ENFORCE_Q_LIMS = previous
        summaries.append({"case": case, "voltage_limit_alpha": summary["voltage_limit_alpha"],
                          "nose_alpha": summary["nose_alpha"],
                          "first_s2_alpha": summary["first_alpha_by_status"]["S2"],
                          "first_s3_alpha": summary["first_alpha_by_status"]["S3"],
                          "first_divergence_alpha": summary["first_alpha_by_status"]["SOLVER_DIVERGENCE"],
                          "voltage_limit_alpha_free_q": free["voltage_limit_alpha"],
                          "nose_alpha_free_q": free["nose_alpha"]})
        _log(f"continuation {case}: voltage limit {summary['voltage_limit_alpha']}, nose {summary['nose_alpha']} "
             f"(unlimited Q: {free['voltage_limit_alpha']}, {free['nose_alpha']})")
    return pd.concat(curves, ignore_index=True), pd.DataFrame(summaries)


def continuation_trace_outputs():
    """Predictor-corrector trace of the solution branch next to the bisection values, for comparison.

    Validated on case9, case14 and case30. On case118 the trace stalls at a turning point near 2.11 that a
    Newton solve does not confirm (the bisection gives 2.14). The headline is the bisection; see docs/PHYSICS.md.
    """
    from . import pflow
    from .ac_se import ACModel
    rows = []
    for case in IEEE:
        net = load_case(case)
        ac = ACModel(net)
        pf = pflow.PowerFlow(net, ac, pflow.injections_from_net(net, ac))
        _, trace_summary = pflow.trace(pf, lam_start=1.0, lam_max=8.0)
        _, bis = continuation(load_case(case), alpha_start=1.0, alpha_max=6.0, step=0.02)
        rows.append({"case": case,
                     "trace_voltage_limit_alpha": trace_summary["voltage_limit_alpha"],
                     "trace_nose_alpha": trace_summary["nose_alpha"],
                     "bisection_voltage_limit_alpha": bis["voltage_limit_alpha"],
                     "bisection_nose_alpha": bis["nose_alpha"],
                     "switched_generator_buses": len(trace_summary["switched_buses"]),
                     "corrector_steps": trace_summary["corrector_steps"]})
        _log(f"trace {case}: nose {trace_summary['nose_alpha']} vs bisection {bis['nose_alpha']}")
    return pd.DataFrame(rows)


def stealth_detection_outputs(trials):
    """LNR detection of random and stealthy attacks, and the targeted attack, on the two meshed cases."""
    rows = []
    for case in ["case14", "case30"]:
        _log(f"LNR and targeted attacks {case}")
        lnr = lnr_summary(case, trials=trials)
        rows.append({"case": case, "kind": "lnr", "metrics": {k: v for k, v in lnr.items() if k != "case"}})
        tgt_trials = max(trials // 2, 20)
        _, tgt = targeted_monte_carlo(case, trials=tgt_trials)
        rows.append({"case": case, "kind": "targeted", "metrics": {k: v for k, v in tgt.items() if k != "case"}})
    return pd.DataFrame(rows)


# ---------------------------------------------------------------- FDIA

def fdia_outputs(trials):
    dc_rows, ac_summaries, ac_trials = [], [], []
    for case in ["case14", "case30", "case118"]:
        dc_rows.append(dc_invariance_check(case))
    for case, n in [("case14", trials), ("case30", trials), ("case118", max(trials // 4, 20))]:
        _log(f"FDIA AC Monte Carlo {case}, {n} trials")
        df, meta = ac_monte_carlo(case, trials=n)
        df.insert(0, "case", case)
        ac_trials.append(df)
        ac_summaries.append(summarise(df, meta))
    return pd.DataFrame(dc_rows), pd.DataFrame(ac_summaries), pd.concat(ac_trials, ignore_index=True)


# ---------------------------------------------------------------- MDP

def stress_vectors(case):
    """Multi-vector stress: base (no outage) and N-1 outages of the two most critical lines (DC PTDF)."""
    net = load_case(case)
    dc = DCModel(net)
    crit = dc.centrality(net)["line_criticality"]
    labels = dc.branch_labels(net)
    lines = [(crit[k], labels[k][1]) for k in range(dc.m) if labels[k][0] == "line"]
    top = [idx for _, idx in sorted(lines, reverse=True)[:2]]
    return [("base", None)] + [(f"N-1 line {idx}", idx) for idx in top]


def mdp_outputs():
    policy_rows, conv_rows, collapse_rows = [], [], []
    base_outcomes = {}
    for case in MDP_CASES:
        for name, line in stress_vectors(case):
            _log(f"MDP {case} / {name}")
            cal = calibrate(case, contingency_line=line)
            net = load_case(case)
            if line is not None:
                net.line.at[line, "in_service"] = False
            bus = most_critical_bus(net)
            outcomes = compute_outcomes(case, cal, bus=bus)
            base_outcomes[(case, name)] = (cal, bus, outcomes)
            for weight_name, w in WEIGHT_SETS.items():
                mdp = build_mdp(case, cal, bus=bus, outcomes=outcomes, w=w)
                vi = value_iteration(mdp)
                for s, v in zip(STATES, vi["V"]):
                    policy_rows.append({"case": case, "stress_vector": name, "weight_set": weight_name,
                                        "state": s,
                                        "loading_target": round(cal.loading[s], 4),
                                        "min_vm": round(cal.min_vm[s], 4), "V_star": round(float(v), 6),
                                        "optimal_action": vi["policy"][STATES.index(s)],
                                        "isolated_bus": bus, "lambda_v": round(cal.lambda_v, 4)})
                if weight_name == "headline":
                    for it, delta in enumerate(vi["history"], start=1):
                        conv_rows.append({"case": case, "stress_vector": name,
                                          "method": "infinite_horizon_VI", "step": it,
                                          "max_abs_change": delta})
                    for T in [5, 10, 20, 40, 80, 160]:
                        diff = np.abs(finite_horizon(mdp, T)["V"] - vi["V"])
                        conv_rows.append({"case": case, "stress_vector": name,
                                          "method": "finite_horizon_error_S0_S2", "step": T,
                                          "max_abs_change": float(np.max(diff[:3]))})
                        conv_rows.append({"case": case, "stress_vector": name,
                                          "method": "finite_horizon_error_S3", "step": T,
                                          "max_abs_change": float(diff[3])})
            for collapse in ["voltage", "loading"]:
                mdp = build_mdp(case, cal, bus=bus, outcomes=outcomes, w=HEADLINE_W, collapse=collapse)
                for a_idx, action in enumerate(ACTIONS):
                    collapse_rows.append({"case": case, "stress_vector": name, "collapse_model": collapse,
                                          "action": action, "p_s3_given_s2": float(mdp.P[a_idx, 2, 3]),
                                          "p_s1_given_s0": float(mdp.P[a_idx, 0, 1]),
                                          "p_s2_given_s1": float(mdp.P[a_idx, 1, 2])})
    return (pd.DataFrame(policy_rows), pd.DataFrame(conv_rows), base_outcomes,
            pd.DataFrame(collapse_rows))


def sensitivity(base_outcomes):
    cal, bus, outcomes = base_outcomes[("case30", "base")]
    rows = []

    def record(sweep, k, lam0, w, kv, gamma=GAMMA_DEFAULT):
        mdp = build_mdp("case30", cal, k=k, lambda0=lam0, w=w, bus=bus, outcomes=outcomes, k_voltage=kv)
        vi = value_iteration(mdp, gamma=gamma)
        rows.append({"sweep": sweep, "k": k, "lambda0": lam0, "w1": w[0], "w3": w[2], "k_voltage": kv,
                     "gamma": gamma,
                     "V_star_S0": float(vi["V"][0]), "action_S1": vi["policy"][1],
                     "action_S2": vi["policy"][2],
                     "non_default_states": sum(a != "DO_NOTHING" for a in vi["policy"]),
                     "p_s3_given_s2": float(mdp.P[0, 2, 3])})

    for k in [5.0, 10.0, 20.0, 40.0]:
        for lam0 in [0.70, 0.80, 0.90]:
            record("k_x_lambda0", k, lam0, HEADLINE_W, K_VOLTAGE)
    for w1 in [10.0, 100.0, 1000.0, 10000.0]:
        for w3 in [1.0, 0.1, 0.01]:
            record("w1_x_w3", 10.0, 0.80, (w1, 5.0, w3), K_VOLTAGE)
    for kv in [50.0, 100.0, 200.0]:
        record("k_voltage", 10.0, 0.80, HEADLINE_W, kv)
    for gamma in [0.90, 0.95, 0.99]:
        record("gamma", 10.0, 0.80, HEADLINE_W, K_VOLTAGE, gamma=gamma)
    return pd.DataFrame(rows)


def heatmap_png(sens):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.colors import ListedColormap

    fig, axes = plt.subplots(1, 2, figsize=(12, 4.8))
    kl = sens[sens.sweep == "k_x_lambda0"]
    ks = sorted(kl.k.unique())
    lams = sorted(kl.lambda0.unique())
    grid = np.array([[kl[(kl.k == k) & (kl.lambda0 == l)].V_star_S0.iloc[0] for l in lams] for k in ks])
    im = axes[0].imshow(grid, origin="lower", aspect="auto", cmap="viridis")
    axes[0].set_xticks(range(len(lams)), [f"{l:.2f}" for l in lams])
    axes[0].set_yticks(range(len(ks)), [f"{k:g}" for k in ks])
    mid = (grid.max() + grid.min()) / 2
    for i in range(len(ks)):
        for j in range(len(lams)):
            colour = "black" if grid[i, j] > mid else "white"
            axes[0].text(j, i, f"{grid[i, j]:.3f}", ha="center", va="center", color=colour, fontsize=9)
    axes[0].set(xlabel="lambda0 (normal limit)", ylabel="k (logistic steepness)",
                title="V*(S0) on case30 base (headline weights)")
    fig.colorbar(im, ax=axes[0], shrink=0.8)

    wl = sens[sens.sweep == "w1_x_w3"]
    w1s = sorted(wl.w1.unique())
    w3s = sorted(wl.w3.unique())
    code = {a: i for i, a in enumerate(ACTIONS)}
    cat = np.array([[code[wl[(wl.w1 == a) & (wl.w3 == b)].action_S2.iloc[0]] for b in w3s] for a in w1s])
    cmap = ListedColormap(["#c8d6e5", "#f0a500", "#d1495b"])
    axes[1].imshow(cat, origin="lower", aspect="auto", cmap=cmap, vmin=-0.5, vmax=2.5)
    axes[1].set_xticks(range(len(w3s)), [f"{b:g}" for b in w3s])
    axes[1].set_yticks(range(len(w1s)), [f"{a:g}" for a in w1s])
    for i in range(len(w1s)):
        for j in range(len(w3s)):
            axes[1].text(j, i, ACTIONS[cat[i, j]].replace("_", "\n"), ha="center", va="center", fontsize=8)
    axes[1].set(xlabel="w3 (action cost weight)", ylabel="w1 (overload weight)",
                title="Optimal action in S2 (thermal overload), case30")
    fig.tight_layout()
    buf = io.BytesIO()
    fig.savefig(buf, dpi=130, format="png")
    plt.close(fig)
    return buf.getvalue()


# ---------------------------------------------------------------- driver

def run_study(trials):
    warnings.simplefilter("ignore")
    results = {}
    _log("PTDF and measurement-model validation")
    ptdf = ptdf_validation()
    meas = measurement_model_validation()
    results["validation"] = validation_long(ptdf, meas)
    results["ptdf_validation"] = ptdf
    results["measurement_model_validation"] = meas
    results["continuation_curves"], results["continuation_summary"] = continuation_outputs()
    results["continuation_trace"] = continuation_trace_outputs()
    results["fdia_extra"] = stealth_detection_outputs(trials)
    dc, ac_summary, ac_trials = fdia_outputs(trials)
    results["fdia_dc_invariance"] = dc
    results["fdia_ac_summary"] = ac_summary
    results["fdia_ac_trials"] = ac_trials
    (results["mdp_policies"], results["state_space_convergence"], base_outcomes,
     results["mdp_transition_probabilities"]) = mdp_outputs()
    _log("sensitivity sweeps")
    results["sensitivity_grid"] = sensitivity(base_outcomes)
    results["sensitivity_heatmap_png"] = heatmap_png(results["sensitivity_grid"])
    return results


CSV_NAMES = {
    "ptdf_validation": "ptdf_validation.csv",
    "measurement_model_validation": "measurement_model_validation.csv",
    "continuation_curves": "continuation_curves.csv",
    "continuation_summary": "continuation_summary.csv",
    "fdia_dc_invariance": "fdia_dc_invariance.csv",
    "fdia_ac_summary": "fdia_ac_summary.csv",
    "fdia_ac_trials": "fdia_ac_trials.csv",
    "mdp_policies": "mdp_policies.csv",
    "mdp_transition_probabilities": "mdp_transition_probabilities.csv",
    "state_space_convergence": "state_space_convergence.csv",
    "sensitivity_grid": "sensitivity_grid.csv",
    "fdia_extra": "fdia_lnr_targeted.csv",
    "continuation_trace": "continuation_predictor_corrector.csv",
}


def write_csv(results, out_dir=OUT):
    os.makedirs(out_dir, exist_ok=True)
    for key, fname in CSV_NAMES.items():
        frame = results[key]
        if key == "fdia_extra":
            frame = pd.json_normalize(frame.to_dict("records"), sep="_")
        frame.to_csv(os.path.join(out_dir, fname), index=False)
    with open(os.path.join(out_dir, "sensitivity_heatmap.png"), "wb") as fh:
        fh.write(results["sensitivity_heatmap_png"])


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--quick", action="store_true")
    parser.add_argument("--no-db", action="store_true")
    parser.add_argument("--keep-runs", type=int, default=None,
                        help="after storing, delete all but the newest N physics runs")
    args = parser.parse_args(argv)
    trials = 40 if args.quick else 200
    results = run_study(trials)
    write_csv(results)
    _log("CSV artifacts written to " + OUT)
    if not args.no_db:
        from .store import store_run
        run_id = store_run(results, mode="quick" if args.quick else "full",
                           settings={"trials": trials, "k_voltage": K_VOLTAGE, "cases": IEEE,
                                     "mdp_cases": MDP_CASES, "enforce_q_lims": _cases.ENFORCE_Q_LIMS,
                                     "lnr_threshold": 3.0})
        _log(f"stored physics run {run_id} in the database")
        if args.keep_runs is not None:
            from .store import prune_runs
            removed = prune_runs(keep=args.keep_runs)
            _log(f"pruned {removed} old physics run(s), keeping the newest {args.keep_runs}")


if __name__ == "__main__":
    main()
