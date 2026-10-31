"""Calibrate the largest-normalised-residual threshold to a 1 % clean false-alarm rate, and measure the
detection of stealthy and targeted attacks against that threshold. Writes docs/physics/lnr_calibration.csv.

Run:  python -m backend.grid.calibrate_lnr
"""
import os
import warnings

import numpy as np
import pandas as pd

from .ac_se import normalized_residuals
from .fdia import random_attack, stealthy_attack, targeted_attack
from .study import setup
from . import telemetry

OUT = os.path.join("docs", "physics", "lnr_calibration.csv")
CASES = [("case14", 200), ("case30", 100)]


def calibrate_case(case, trials, seed=20261018):
    warnings.simplefilter("ignore")
    s = setup(case)
    ac, tel = s["ac"], s["telemetry"]
    sigma = telemetry.sigma_vector(tel)
    comp = telemetry.compromised_mask(tel)
    rng = np.random.default_rng(seed)
    z_true = ac.h(ac.state_from_powerflow())
    clean, stealth, targ = [], [], []
    for _ in range(trials):
        z = z_true + rng.normal(0, sigma)
        x0, _, _, _ = ac.estimate(z, sigma)
        clean.append(normalized_residuals(ac, z, x0, sigma).max())
        H0 = ac.jacobian(x0)
        st = stealthy_attack(H0, z, comp)
        if st.feasible:
            xs, _, _, _ = ac.estimate(z + st.a, sigma, x0=x0)
            stealth.append(normalized_residuals(ac, z + st.a, xs, sigma).max())
        best = None
        for k in range(ac.nbr):
            row = 3 * ac.n + k
            t = targeted_attack(H0, z, comp, row)
            if t.feasible:
                lin = abs(float(H0[row] @ t.c))
                if best is None or lin > best[1]:
                    best = (k, lin, t)
        if best is not None:
            xt, _, _, _ = ac.estimate(z + best[2].a, sigma, x0=x0)
            targ.append(normalized_residuals(ac, z + best[2].a, xt, sigma).max())
    clean, stealth, targ = map(np.array, (clean, stealth, targ))
    thr = float(np.quantile(clean, 0.99))
    return {"case": case, "clean_trials": len(clean), "lnr_threshold_99pct_clean": round(thr, 3),
            "lnr_threshold_3": 3.0,
            "clean_rate_at_99pct": float((clean > thr).mean()),
            "stealthy_detection_at_99pct": float((stealth > thr).mean()) if len(stealth) else None,
            "targeted_detection_at_99pct": float((targ > thr).mean()) if len(targ) else None,
            "targeted_detection_at_3": float((targ > 3.0).mean()) if len(targ) else None}


def main():
    rows = [calibrate_case(case, trials) for case, trials in CASES]
    df = pd.DataFrame(rows)
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    df.to_csv(OUT, index=False)
    print(df.T.to_string())


if __name__ == "__main__":
    main()
