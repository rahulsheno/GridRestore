"""Tests for the fast parts of the physics study driver, and for the headline weight rule.

The full study takes about six minutes and is run from the command line, so these tests cover the pieces
that can run in a second: flattening validation results, writing artifacts, drawing the heatmap, and checking
that the headline weight still follows the documented rule.
"""
import os

import numpy as np
import pandas as pd

from backend.grid import mdp, physics_study
from backend.grid.mdp import ACTIONS

OUT_CSV_KEYS = list(physics_study.CSV_NAMES)


def _sensitivity_frame():
    rows = []
    for k in [5.0, 10.0, 20.0, 40.0]:
        for lam0 in [0.70, 0.80, 0.90]:
            rows.append({"sweep": "k_x_lambda0", "k": k, "lambda0": lam0, "w1": 10.0, "w3": 0.1,
                         "k_voltage": 100.0, "gamma": 0.95, "V_star_S0": -0.1 * k / 10 - lam0 / 10,
                         "action_S1": "DO_NOTHING", "action_S2": "LOAD_SHED", "non_default_states": 1,
                         "p_s3_given_s2": 1e-4})
    for w1 in [10.0, 100.0, 1000.0, 10000.0]:
        for w3 in [1.0, 0.1, 0.01]:
            rows.append({"sweep": "w1_x_w3", "k": 10.0, "lambda0": 0.8, "w1": w1, "w3": w3, "k_voltage": 100.0,
                         "gamma": 0.95, "V_star_S0": -0.05, "action_S1": "DO_NOTHING",
                         "action_S2": ACTIONS[0 if w3 == 1.0 and w1 == 10.0 else 2], "non_default_states": 1,
                         "p_s3_given_s2": 1e-4})
    return pd.DataFrame(rows)


def test_validation_long_has_one_row_per_check_case_and_metric():
    ptdf = pd.DataFrame([{"case": "case14", "buses": 14, "branches": 20,
                          "max_line_flow_error_MW": 1e-13, "max_trafo_flow_error_MW": 4e-14}])
    meas = pd.DataFrame([{"case": "case14", "buses": 14, "branches": 20, "measurements": 82, "states": 27,
                          "max_V_error_pu": 0.0, "max_P_injection_error_pu": 5e-11,
                          "max_Q_injection_error_pu": 9e-11, "max_line_flow_error_MVA": 2e-13,
                          "max_trafo_flow_error_MVA": None}])
    out = physics_study.validation_long(ptdf, meas)
    assert set(out.check_name) == {"ptdf_dc_flow", "ac_measurement_model"}
    assert len(out) == 2 + 5  # two PTDF metrics, five measurement metrics
    assert "buses" not in set(out.metric)
    assert out[out.metric == "max_trafo_flow_error_MVA"].value.isna().all()


def test_heatmap_png_is_a_png():
    png = physics_study.heatmap_png(_sensitivity_frame())
    assert png.startswith(b"\x89PNG\r\n\x1a\n") and len(png) > 1000


def test_write_csv_writes_every_artifact(tmp_path):
    results = {key: pd.DataFrame([{"x": 1}]) for key in OUT_CSV_KEYS}
    results["fdia_extra"] = pd.DataFrame([{"case": "case14", "kind": "lnr", "metrics": {"detection": 0.01}}])
    results["sensitivity_heatmap_png"] = b"\x89PNG\r\n\x1a\nxx"
    physics_study.write_csv(results, out_dir=str(tmp_path))
    written = set(os.listdir(tmp_path))
    assert set(physics_study.CSV_NAMES.values()) <= written
    assert "sensitivity_heatmap.png" in written
    flat = pd.read_csv(tmp_path / "fdia_lnr_targeted.csv")
    assert "metrics_detection" in flat.columns


def test_headline_weight_follows_the_documented_rule():
    """w3 = half the smallest threshold over every stress vector and case, as saved in docs/physics."""
    path = os.path.join("docs", "physics", "w3_threshold_by_stress.csv")
    thresholds = pd.read_csv(path).dropna(subset=["threshold"]).threshold
    assert abs(mdp.W3_HEADLINE - thresholds.min() / 2) <= 5.1e-5   # thresholds are saved to 4 decimals
    # The headline is inside the mitigation region everywhere it was measured.
    assert (mdp.W3_HEADLINE < thresholds).all()
