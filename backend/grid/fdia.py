"""False data injection attacks against WLS state estimation, and the chi-squared bad-data detector.

Adversary (as stated in the plan):
  * knows the topology, parameters and measurement Jacobian (H, or H(x0) locally in AC);
  * can change only measurements reported by the RTUs the cyber graph shows as compromised;
  * each change is bounded: |a_i| <= budget * |z_i| with budget = 15 %.

Stealthy attack construction:
  Let U be the uncompromised rows and C the compromised rows. An attack a with a_U = 0 must equal
  H c on C for some state change c with H_U c = 0. So c lies in the null space of H_U. Any c = N w in
  that null space leaves the uncompromised measurements exactly unchanged.

Linear (DC) case: the residual r = z - Hx_hat changes by a - H c = 0 for every attacked row, so
  J(z + a) = J(z) exactly. The check in the tests compares the two numbers to round-off.

AC case: a = H(x0) c is only a local approximation. J(z + a) differs from J(z) by a second-order
  term, so "residual invariance" is measured numerically, not assumed.
"""
from dataclasses import dataclass

import numpy as np
from scipy.linalg import null_space

BUDGET = 0.15          # |a_i| <= 15 % of |z_i|
MIN_ABS_Z = 1e-3       # measurements smaller than this cannot be scaled by a relative bound; they are left alone


@dataclass
class Attack:
    a: np.ndarray        # additive change to the measurement vector (zero outside the compromised set)
    c: np.ndarray        # state change the attack is built from
    rows: np.ndarray     # boolean mask of attacked rows
    feasible: bool
    note: str = ""


def stealthy_attack(H, z, compromised, budget=BUDGET, min_abs_z=MIN_ABS_Z, direction=None):
    """Maximum-energy stealthy attack inside the compromised rows, scaled to the bound.

    H: measurement Jacobian at the operating point (m x p). z: measurement vector. compromised: bool (m,).
    direction: optional state-space vector; if given the attack is the projection onto that direction.
    """
    z = np.asarray(z, float)
    rows = np.asarray(compromised, bool) & (np.abs(z) >= min_abs_z)
    uncompromised = ~rows
    if not rows.any():
        return Attack(np.zeros(len(z)), np.zeros(H.shape[1]), rows, False, "no attackable compromised measurement")
    N = null_space(H[uncompromised])           # p x k, columns span {c : H_U c = 0}
    if N.shape[1] == 0:
        return Attack(np.zeros(len(z)), np.zeros(H.shape[1]), rows, False,
                      "uncompromised measurements determine the state: no stealthy direction")
    M = H[rows] @ N                             # effect of each null-space direction on attacked rows
    if direction is None:
        _, s, vt = np.linalg.svd(M, full_matrices=False)
        w = vt[0]                               # direction with the largest effect on the attacked rows
    else:
        w = np.linalg.lstsq(N, direction, rcond=None)[0]
    a_rows = M @ w
    if np.max(np.abs(a_rows)) < 1e-12:
        return Attack(np.zeros(len(z)), np.zeros(H.shape[1]), rows, False, "attack has no effect")
    bound = budget * np.abs(z[rows])
    scale = np.min(bound / np.maximum(np.abs(a_rows), 1e-300))
    a = np.zeros(len(z))
    a[rows] = a_rows * scale
    c = (N @ w) * scale
    return Attack(a, c, rows, True, f"{N.shape[1]} stealthy directions; scaled to {budget:.0%} bound")


def random_attack(z, compromised, rng, budget=BUDGET, min_abs_z=MIN_ABS_Z):
    """Control attack: same compromised rows and same magnitude bound, random signs, no physics."""
    z = np.asarray(z, float)
    rows = np.asarray(compromised, bool) & (np.abs(z) >= min_abs_z)
    a = np.zeros(len(z))
    a[rows] = rng.choice([-1.0, 1.0], size=rows.sum()) * budget * np.abs(z[rows])
    return a


def bound_satisfied(a, z, compromised, budget=BUDGET, tol=1e-9):
    z = np.asarray(z, float)
    rows = np.asarray(compromised, bool)
    if np.any(np.abs(a[~rows]) > tol):
        return False
    return bool(np.all(np.abs(a[rows]) <= budget * np.abs(z[rows]) + tol))


def chi2_statistic(r, W):
    return float(np.sum(W * r * r))


def targeted_attack(H, z, compromised, target_row, budget=BUDGET, min_abs_z=MIN_ABS_Z):
    """Stealthy attack that maximises the change in one measurement's estimate, within the same bounds.

    Linearised: the estimate of measurement `target_row` moves by H[target_row] c with c = N w, so the attacker
    solves   max_w  g^T w   with  g = H[target_row] N,  subject to  |(H_C N w)_i| <= budget |z_i| for compromised i.
    This is a linear program. The sign of the optimum is chosen by solving for +g and -g and keeping the larger.
    """
    from scipy.optimize import linprog

    z = np.asarray(z, float)
    rows = np.asarray(compromised, bool) & (np.abs(z) >= min_abs_z)
    uncompromised = ~rows
    if not rows.any():
        return Attack(np.zeros(len(z)), np.zeros(H.shape[1]), rows, False, "no attackable measurement")
    N = null_space(H[uncompromised])
    if N.shape[1] == 0:
        return Attack(np.zeros(len(z)), np.zeros(H.shape[1]), rows, False,
                      "uncompromised measurements determine the state")
    M = H[rows] @ N
    bound = budget * np.abs(z[rows])
    g = H[target_row] @ N
    A = np.vstack([M, -M])
    b = np.concatenate([bound, bound])
    best = None
    for sign in (1.0, -1.0):
        res = linprog(-sign * g, A_ub=A, b_ub=b, bounds=[(None, None)] * N.shape[1], method="highs")
        if res.status == 0 and (best is None or -res.fun > best[0]):
            best = (-res.fun, res.x)
    if best is None or best[0] <= 1e-12:
        return Attack(np.zeros(len(z)), np.zeros(H.shape[1]), rows, False, "no effect on the target")
    w = best[1]
    a = np.zeros(len(z))
    a[rows] = M @ w
    return Attack(a, N @ w, rows, True, f"linear target effect {best[0]:.4g}")
