"""Write one physics study run to PostgreSQL, and read runs back for the REST API.

Writing: `store_run(results, mode, settings)` takes the dictionary built by physics_study.run_study and
inserts one physics_runs row plus the rows of every results table, in a single transaction.
Reading:  the functions below return plain dictionaries and lists. They never write.
"""
import json
import math

import numpy as np
import pandas as pd

from ..db import connect
from .mdp import HEADLINE_W, PLAN_W


def _clean(value):
    """numpy and pandas scalars to Python; NaN and None to None."""
    if value is None:
        return None
    if isinstance(value, (np.bool_,)):
        return bool(value)
    if isinstance(value, np.generic):
        value = value.item()
    if isinstance(value, float) and math.isnan(value):
        return None
    if value is pd.NA or value is pd.NaT:
        return None
    return value


def _rows(frame, columns):
    """Rows of `frame` restricted to `columns`, cleaned for the database. Missing columns become None."""
    out = []
    for record in frame.to_dict("records"):
        out.append(tuple(_clean(record.get(c)) for c in columns))
    return out


def _metrics(record, exclude):
    return {k: _clean(v) if not isinstance(v, (list, dict)) else v
            for k, v in record.items() if k not in exclude}


def store_run(results, mode, settings):
    """Insert one run. Returns run_id. Everything is written in one transaction."""
    if mode not in ("full", "quick"):
        raise ValueError("mode must be 'full' or 'quick'")
    with connect() as conn:
        with conn.cursor() as cur:
            run_id = cur.execute(
                "INSERT INTO physics_runs(mode, headline_weights, plan_weights, settings) "
                "VALUES (%s, %s, %s, %s) RETURNING run_id",
                (mode, json.dumps(dict(zip(["w1", "w2", "w3"], HEADLINE_W))),
                 json.dumps(dict(zip(["w1", "w2", "w3"], PLAN_W))), json.dumps(settings, default=str)),
            ).fetchone()["run_id"]

            def put(sql, rows):
                if rows:
                    cur.executemany(sql, [(run_id, *r) for r in rows])

            put("INSERT INTO physics_validation(run_id, check_name, case_name, metric, value) "
                "VALUES (%s,%s,%s,%s,%s)",
                _rows(results["validation"], ["check_name", "case_name", "metric", "value"]))
            put("INSERT INTO physics_continuation(run_id, case_name, alpha, status, max_loading, min_vm) "
                "VALUES (%s,%s,%s,%s,%s,%s)",
                _rows(results["continuation_curves"].rename(columns={"case": "case_name"}),
                      ["case_name", "alpha", "status", "max_loading", "min_vm"]))
            put("INSERT INTO physics_continuation_summary(run_id, case_name, voltage_limit_alpha, nose_alpha, "
                "first_s2_alpha, first_s3_alpha, first_divergence_alpha, voltage_limit_alpha_free_q, "
                "nose_alpha_free_q) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                _rows(results["continuation_summary"].rename(columns={"case": "case_name"}),
                      ["case_name", "voltage_limit_alpha", "nose_alpha", "first_s2_alpha", "first_s3_alpha",
                       "first_divergence_alpha", "voltage_limit_alpha_free_q", "nose_alpha_free_q"]))
            for kind, key in [("dc", "fdia_dc_invariance"), ("ac", "fdia_ac_summary")]:
                summary_rows = []
                for record in results[key].to_dict("records"):
                    summary_rows.append((record["case"], kind, json.dumps(
                        _metrics(record, {"case"}), default=str)))
                put("INSERT INTO physics_fdia_summary(run_id, case_name, kind, metrics) VALUES (%s,%s,%s,%s)",
                    summary_rows)
            extra_frame = results.get("fdia_extra", pd.DataFrame(columns=["case", "kind", "metrics"]))
            extra = [(r["case"], r["kind"], json.dumps(r["metrics"], default=str))
                     for r in extra_frame.to_dict("records")]
            put("INSERT INTO physics_fdia_summary(run_id, case_name, kind, metrics) VALUES (%s,%s,%s,%s)", extra)
            trials = results["fdia_ac_trials"].rename(columns={"case": "case_name"})
            trial_cols = ["case_name", "trial", "J_clean", "clean_alarm", "stealthy_feasible",
                          "stealthy_bypass", "J_random", "random_detected"]
            put("INSERT INTO physics_fdia_trials(run_id, case_name, trial, j_clean, clean_alarm, "
                "stealthy_feasible, stealthy_bypass, j_random, random_detected) "
                "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)", _rows(trials, trial_cols))
            put("INSERT INTO physics_mdp_policy(run_id, case_name, stress_vector, weight_set, state, "
                "loading_target, min_vm, v_star, optimal_action, lambda_v, isolated_bus) "
                "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                _rows(results["mdp_policies"].rename(columns={"case": "case_name", "V_star": "v_star"}),
                      ["case_name", "stress_vector", "weight_set", "state", "loading_target", "min_vm",
                       "v_star", "optimal_action", "lambda_v", "isolated_bus"]))
            put("INSERT INTO physics_mdp_transitions(run_id, case_name, stress_vector, collapse_model, action, "
                "p_s3_given_s2, p_s1_given_s0, p_s2_given_s1) VALUES (%s,%s,%s,%s,%s,%s,%s,%s)",
                _rows(results["mdp_transition_probabilities"].rename(columns={"case": "case_name"}),
                      ["case_name", "stress_vector", "collapse_model", "action", "p_s3_given_s2",
                       "p_s1_given_s0", "p_s2_given_s1"]))
            sensitivity = results["sensitivity_grid"].copy()
            if "gamma" not in sensitivity:
                sensitivity["gamma"] = 0.95   # results from before the discount-factor sweep
            put("INSERT INTO physics_sensitivity(run_id, sweep, k, lambda0, w1, w3, k_voltage, gamma, v_star_s0, "
                "action_s1, action_s2, non_default_states, p_s3_given_s2) "
                "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                _rows(sensitivity.rename(columns={"V_star_S0": "v_star_s0",
                                                                  "action_S1": "action_s1",
                                                                  "action_S2": "action_s2"}),
                      ["sweep", "k", "lambda0", "w1", "w3", "k_voltage", "gamma", "v_star_s0", "action_s1",
                       "action_s2", "non_default_states", "p_s3_given_s2"]))
            put("INSERT INTO physics_convergence(run_id, case_name, stress_vector, method, step, max_abs_change) "
                "VALUES (%s,%s,%s,%s,%s,%s)",
                _rows(results["state_space_convergence"].rename(columns={"case": "case_name"}),
                      ["case_name", "stress_vector", "method", "step", "max_abs_change"]))
            cur.execute("INSERT INTO physics_figures(run_id, name, content_type, data) VALUES (%s,%s,%s,%s)",
                        (run_id, "sensitivity_heatmap", "image/png", results["sensitivity_heatmap_png"]))
    return run_id


# ---------------------------------------------------------------- reading (used by the API)

def _run_exists(conn, run_id):
    return conn.execute("SELECT 1 FROM physics_runs WHERE run_id=%s", (run_id,)).fetchone() is not None


def prune_runs(keep, only=None):
    """Delete all but the newest `keep` physics runs (their rows go with them). Returns the number removed.

    `only`, if given, restricts deletion to those run_ids, so a caller can clean up its own runs without
    touching anything else in the table.
    """
    if keep < 1:
        raise ValueError("keep must be at least 1")
    with connect() as conn:
        if only is None:
            rows = conn.execute("DELETE FROM physics_runs WHERE run_id NOT IN "
                                "(SELECT run_id FROM physics_runs ORDER BY run_id DESC LIMIT %s) "
                                "RETURNING run_id", (keep,)).fetchall()
        else:
            rows = conn.execute("DELETE FROM physics_runs WHERE run_id = ANY(%s) AND run_id NOT IN "
                                "(SELECT run_id FROM physics_runs ORDER BY run_id DESC LIMIT %s) "
                                "RETURNING run_id", (list(only), keep)).fetchall()
    return len(rows)


def list_runs(limit=50):
    with connect() as conn:
        rows = conn.execute(
            "SELECT run_id, created_at, created_by, mode, headline_weights, plan_weights "
            "FROM physics_runs ORDER BY run_id DESC LIMIT %s", (limit,)).fetchall()
    return [dict(r, created_at=r["created_at"].isoformat()) for r in rows]


def run_overview(run_id):
    """Everything the Physics tab shows at once, except the long tables (continuation curves, trials)."""
    with connect() as conn:
        if not _run_exists(conn, run_id):
            return None
        run = conn.execute("SELECT run_id, created_at, created_by, mode, headline_weights, plan_weights, "
                           "settings FROM physics_runs WHERE run_id=%s", (run_id,)).fetchone()
        validation = conn.execute("SELECT check_name, case_name, metric, value FROM physics_validation "
                                  "WHERE run_id=%s ORDER BY check_name, case_name, metric", (run_id,)).fetchall()
        continuation = conn.execute("SELECT * FROM physics_continuation_summary WHERE run_id=%s "
                                    "ORDER BY case_name", (run_id,)).fetchall()
        fdia = conn.execute("SELECT case_name, kind, metrics FROM physics_fdia_summary WHERE run_id=%s "
                            "ORDER BY kind, case_name", (run_id,)).fetchall()
        policy = conn.execute("SELECT case_name, stress_vector, weight_set, state, loading_target, min_vm, "
                              "v_star, optimal_action FROM physics_mdp_policy WHERE run_id=%s "
                              "ORDER BY case_name, stress_vector, weight_set, state", (run_id,)).fetchall()
        figures = [r["name"] for r in conn.execute("SELECT name FROM physics_figures WHERE run_id=%s",
                                                   (run_id,)).fetchall()]
    return {
        "run": dict(run, created_at=run["created_at"].isoformat()),
        "validation": [dict(r) for r in validation],
        "continuation_summary": [dict(r) for r in continuation],
        "fdia": [dict(r) for r in fdia],
        "mdp_policy": [dict(r) for r in policy],
        "figures": sorted(figures),
    }


def continuation_curve(run_id, case):
    with connect() as conn:
        if not _run_exists(conn, run_id):
            return None
        rows = conn.execute("SELECT alpha, status, max_loading, min_vm FROM physics_continuation "
                            "WHERE run_id=%s AND case_name=%s ORDER BY alpha", (run_id, case)).fetchall()
    return [dict(r) for r in rows]


def fdia_trials(run_id, case, limit=200, offset=0):
    with connect() as conn:
        if not _run_exists(conn, run_id):
            return None
        rows = conn.execute("SELECT trial, j_clean, clean_alarm, stealthy_feasible, stealthy_bypass, j_random, "
                            "random_detected FROM physics_fdia_trials WHERE run_id=%s AND case_name=%s "
                            "ORDER BY trial LIMIT %s OFFSET %s", (run_id, case, limit, offset)).fetchall()
    return [dict(r) for r in rows]


def mdp_detail(run_id, case, weight_set=None):
    with connect() as conn:
        if not _run_exists(conn, run_id):
            return None
        params = [run_id, case]
        extra = ""
        if weight_set:
            extra = " AND weight_set=%s"
            params.append(weight_set)
        policy = conn.execute(
            "SELECT stress_vector, weight_set, state, loading_target, min_vm, v_star, optimal_action, lambda_v, "
            "isolated_bus FROM physics_mdp_policy WHERE run_id=%s AND case_name=%s" + extra +
            " ORDER BY stress_vector, weight_set, state", params).fetchall()
        transitions = conn.execute(
            "SELECT stress_vector, collapse_model, action, p_s3_given_s2, p_s1_given_s0, p_s2_given_s1 "
            "FROM physics_mdp_transitions WHERE run_id=%s AND case_name=%s "
            "ORDER BY stress_vector, collapse_model, action", (run_id, case)).fetchall()
    return {"policy": [dict(r) for r in policy], "transitions": [dict(r) for r in transitions]}


def sensitivity(run_id):
    with connect() as conn:
        if not _run_exists(conn, run_id):
            return None
        rows = conn.execute("SELECT sweep, k, lambda0, w1, w3, k_voltage, gamma, v_star_s0, action_s1, action_s2, "
                            "non_default_states, p_s3_given_s2 FROM physics_sensitivity WHERE run_id=%s "
                            "ORDER BY sweep, k, lambda0, w1, w3, k_voltage, gamma", (run_id,)).fetchall()
    return [dict(r) for r in rows]


def convergence(run_id, case, stress_vector):
    with connect() as conn:
        if not _run_exists(conn, run_id):
            return None
        rows = conn.execute("SELECT method, step, max_abs_change FROM physics_convergence "
                            "WHERE run_id=%s AND case_name=%s AND stress_vector=%s ORDER BY method, step",
                            (run_id, case, stress_vector)).fetchall()
    return [dict(r) for r in rows]


def figure(run_id, name):
    with connect() as conn:
        row = conn.execute("SELECT content_type, data FROM physics_figures WHERE run_id=%s AND name=%s",
                           (run_id, name)).fetchone()
    return None if row is None else (row["content_type"], bytes(row["data"]))
