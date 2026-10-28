"""Derive the headline action-cost weight by the rule in docs/PHYSICS.md section 5.2.

For every stress vector on every case, bisect (log scale) for the largest w3 at which mitigation (any action
other than doing nothing) is optimal in the thermal state S2. The headline w3 is half the smallest such
threshold, rounded half up to four decimals.

Writes docs/physics/w3_threshold_by_stress.csv and docs/physics/w3_choice.csv.
Run:  python -m backend.grid.calibrate_w3
"""
import math
import os
import warnings
from decimal import ROUND_HALF_UP, Decimal

import pandas as pd

from .cases import load_case
from .mdp import HEADLINE_W, build_mdp, calibrate, compute_outcomes, most_critical_bus, value_iteration
from .physics_study import MDP_CASES, stress_vectors

OUT = os.path.join("docs", "physics")


def s2_mitigates(case, cal, bus, outcomes, w3):
    m = build_mdp(case, cal, bus=bus, outcomes=outcomes, w=(HEADLINE_W[0], HEADLINE_W[1], w3))
    return value_iteration(m)["policy"][2] != "DO_NOTHING"


def threshold(case, cal, bus, outcomes, lo=1e-4, hi=10.0):
    if not s2_mitigates(case, cal, bus, outcomes, lo) or s2_mitigates(case, cal, bus, outcomes, hi):
        return None
    for _ in range(40):
        mid = math.sqrt(lo * hi)
        if s2_mitigates(case, cal, bus, outcomes, mid):
            lo = mid
        else:
            hi = mid
        if hi / lo < 1.001:
            break
    return lo


def main():
    warnings.simplefilter("ignore")
    rows = []
    for case in MDP_CASES:
        for name, line in stress_vectors(case):
            cal = calibrate(case, contingency_line=line)
            net = load_case(case)
            if line is not None:
                net.line.at[line, "in_service"] = False
            bus = most_critical_bus(net)
            outcomes = compute_outcomes(case, cal, bus=bus)
            t = threshold(case, cal, bus, outcomes)
            rows.append({"case": case, "stress_vector": name,
                         "threshold": None if t is None else round(t, 4),
                         "note": "" if t is not None else "no bracket: mitigation not optimal at the bracket ends"})
            print(case, name, rows[-1]["threshold"], flush=True)
    df = pd.DataFrame(rows)
    os.makedirs(OUT, exist_ok=True)
    df.to_csv(os.path.join(OUT, "w3_threshold_by_stress.csv"), index=False)
    smallest = df.dropna(subset=["threshold"]).threshold.min()
    chosen = float(Decimal(str(smallest / 2)).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP))
    pd.DataFrame([{"robust_threshold": smallest, "chosen_w3": chosen,
                   "rule": "half of the minimum threshold over all stress vectors and cases, rounded half up"}]
                 ).to_csv(os.path.join(OUT, "w3_choice.csv"), index=False)
    print("robust threshold", smallest, "chosen w3", chosen)


if __name__ == "__main__":
    main()
