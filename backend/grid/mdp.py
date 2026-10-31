"""Markov decision process over operating states, with states and action effects from the power flow.

States (representative operating points, calibrated from the network):
    S0 normal            max loading = 0.60  (the base case after re-rating)
    S1 stressed          max loading = 0.90
    S2 thermal overload  max loading = 1.05
    S3 voltage collapse  the load level at which min voltage reaches 0.85 pu (absorbing)

Actions:
    DO_NOTHING     no change
    ISOLATE_NODE   open every branch at the bus with the highest electrical node criticality
                   (DC PTDF metric) and disconnect its load and generation
    LOAD_SHED      disconnect 20 % of the load everywhere

Action cost w3 * cost is the fraction of total system load interrupted (unit-free, in [0, 1]).

Reward (plan): R = -(w1 * overload^2 + w2 * sag^2 + w3 * cost), with
    overload = max(0, max_loading - 1)            (fraction over 100 %)
    sag      = max(0, V_REF - min_vm)             (V_REF = 0.95 pu, planning lower bound)
    w1 = 10.0, w2 = 5.0, w3 = 1.0 (plan values)

Transitions (plan): from a state the next-state distribution depends on the post-action loading lambda:
    S0:  P(S1) = sigma(k (lambda - lambda0)),  k = 10, lambda0 = 0.80   (the plan's formula)
    S1:  P(S2) = sigma(k (lambda - 1.00));     P(S0) = (1 - P(S2)) (1 - sigma(k (lambda - lambda0)))
    S2:  P(S3) = sigma(k (lambda - lambda_V)); P(S1) = (1 - P(S3)) (1 - sigma(k (lambda - 1.00)))
    S3:  absorbing
where lambda_V is the loading at the voltage limit (0.85 pu) found by the continuation search.
The thresholds 1.00 and lambda_V for the higher states are our assumptions, not the plan's.

A power flow that does not converge after an action is treated as a collapse: lambda = lambda_V + 0.5 and
the reward uses the fixed penalty overload = 0.5, sag = V_REF. These cases are counted and reported.
"""
import warnings
from dataclasses import dataclass, field

import numpy as np
import pandapower as pp

from .cases import load_case, locate_branch
from .dc_model import DCModel
from .operating_point import LOAD_NORMAL, VOLTAGE_LIMIT, classify, scale_loads, solve

STATES = ["S0", "S1", "S2", "S3"]
ACTIONS = ["DO_NOTHING", "ISOLATE_NODE", "LOAD_SHED"]
TARGET_LOADING = {"S0": 0.60, "S1": 0.90, "S2": 1.05}
SHED_FRACTION = 0.20
V_REF = 0.95
W1, W2, W3 = 10.0, 5.0, 1.0
K_LOGISTIC, LAMBDA0 = 10.0, LOAD_NORMAL
GAMMA = 0.95
# Voltage-based collapse transition (headline model). The scale 0.01 pu is our assumption:
# P(S3 | S2) = sigmoid(K_VOLTAGE * (VOLTAGE_LIMIT - min_vm_after_action)).
# It is 0.5 at 0.85 pu, about 0.1 at 0.87 pu and about 1e-4 at 0.93 pu. It is swept in the study.
K_VOLTAGE = 100.0
# Headline reward weights. w1 and w2 are the plan's values. w3 is derived, not assumed:
# the decision rule is to take half of the smallest action-cost weight at which mitigation is optimal in the
# thermal state (S2), over every stress vector on both networks (docs/physics/w3_threshold_by_stress.csv).
# The smallest threshold is 0.2305 (case14, line 1 out), so w3 = 0.1153. The plan's w3 = 1 is reported alongside.
W3_HEADLINE = 0.1153
HEADLINE_W = (10.0, 5.0, W3_HEADLINE)
PLAN_W = (10.0, 5.0, 1.0)
# Voltage-based collapse (our choice, option (b)): P(S3 | S2, a) = sigmoid(K_VOLTAGE * (0.85 - min_vm_after_a)).
# K_VOLTAGE = 100 gives a voltage scale of 0.01 pu: the collapse probability is 0.5 at 0.85 pu, about 1e-4 at
# 0.92 pu and about 0.9 at 0.83 pu. It is an assumption and is swept in the sensitivity study.
K_VOLTAGE = 100.0
COLLAPSE_MODELS = ("voltage", "loading")


def sigmoid(x):
    return 1.0 / (1.0 + np.exp(-x))


# ---------------------------------------------------------------- calibration of states

@dataclass
class Calibration:
    alpha: dict
    loading: dict
    min_vm: dict
    lambda_v: float
    contingency: object = None


def _loading_and_vm(net, alpha, base):
    scale_loads(net, alpha, base)
    if not solve(net):
        return float("inf"), 0.0
    loading = float(net.res_line.loading_percent.max()) / 100.0
    if len(net.trafo):
        loading = max(loading, float(net.res_trafo.loading_percent.max()) / 100.0)
    return loading, float(net.res_bus.vm_pu.min())


def _bisect(f, lo, hi, target, tol=1e-5, max_iter=60):
    """Find alpha with f(alpha) = target for monotone f, returning the CONVERGED side of the bracket.

    f may return inf or 0 for a non-converged power flow. The returned alpha is always a point where the
    power flow converged, so its outcome can be used directly. (Returning the midpoint could land on the
    diverged side; that produced inf loadings in an earlier version.)
    """
    flo = f(lo)
    fhi = f(hi)
    if (flo - target) * (fhi - target) > 0:
        raise ValueError(f"target {target} not bracketed in [{lo}, {hi}]: f={flo:.3f}..{fhi:.3f}")
    for _ in range(max_iter):
        mid = 0.5 * (lo + hi)
        fm = f(mid)
        if (fm - target) * (flo - target) <= 0:
            hi = mid
        else:
            lo, flo = mid, fm
        if hi - lo < tol:
            break
    return lo


def calibrate(case, contingency_line=None):
    """Find the load level for each state and the voltage-limit loading for one stress vector."""
    net = load_case(case)
    if contingency_line is not None:
        net.line.at[contingency_line, "in_service"] = False
    base = scale_loads(net, 1.0)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        alpha, loading, vm = {}, {}, {}
        for s, target in TARGET_LOADING.items():
            a = _bisect(lambda al: _loading_and_vm(net, al, base)[0], 0.3, 4.0, target)
            alpha[s] = a
            loading[s], vm[s] = _loading_and_vm(net, a, base)
        # Voltage limit: minimum voltage falls through 0.85 pu. The converged side has vm >= 0.85.
        a_v = _bisect(lambda al: _loading_and_vm(net, al, base)[1], 0.3, 6.0, VOLTAGE_LIMIT)
        loading["S3"], vm["S3"] = _loading_and_vm(net, a_v, base)
        if not np.isfinite(loading["S3"]):
            raise RuntimeError("voltage-limit loading is not finite: the power flow diverged before the limit")
        alpha["S3"] = a_v
        scale_loads(net, 1.0, base)
    return Calibration(alpha=alpha, loading=loading, min_vm=vm, lambda_v=loading["S3"],
                       contingency=contingency_line)


# ---------------------------------------------------------------- action outcomes

def most_critical_bus(net):
    """Load-carrying, non-slack bus with the highest DC node criticality (PTDF electrical centrality).

    Only buses that carry load are candidates: isolating a bus with no load and no generation changes
    nothing, so it cannot be a meaningful repair action.
    """
    dc = DCModel(net)
    crit = dc.centrality(net)["node_criticality"]
    load_buses = set(net.load.bus[net.load.in_service])
    candidates = {}
    for pp_bus in net.bus.index:
        row = int(net._pd2ppc_lookups["bus"][pp_bus])
        if row == dc.slack_row or pp_bus not in load_buses:
            continue
        candidates[pp_bus] = crit[row]
    return max(candidates, key=candidates.get)


def apply_action(net, action, alpha, base, bus=None):
    """Put the network in the state's load level, then apply the action.

    Returns the action cost: MW of load and generation disconnected, divided by the total load plus
    total generation at base (unit-free, in [0, 1]).
    """
    scale_loads(net, alpha, base)
    total = float(base["p"].sum()) + (float(base["gen_p"].sum()) if base["gen_p"] is not None else 0.0)
    if action == "DO_NOTHING":
        return 0.0
    if action == "LOAD_SHED":
        scale_loads(net, alpha * (1 - SHED_FRACTION), base)
        return SHED_FRACTION
    if action == "ISOLATE_NODE":
        if bus is None:
            raise ValueError("ISOLATE_NODE needs a bus")
        net.bus.at[bus, "in_service"] = False
        net.line.loc[(net.line.from_bus == bus) | (net.line.to_bus == bus), "in_service"] = False
        net.trafo.loc[(net.trafo.hv_bus == bus) | (net.trafo.lv_bus == bus), "in_service"] = False
        for table in ("load", "gen", "sgen", "shunt", "ext_grid"):
            df = getattr(net, table)
            if len(df) and "bus" in df.columns:
                df.loc[df.bus == bus, "in_service"] = False
        lost = float(base["p"][net.load.bus == bus].sum())
        if base["gen_p"] is not None and len(net.gen):
            lost += float(base["gen_p"][net.gen.bus == bus].sum())
        return lost / total if total > 0 else 0.0
    raise ValueError(action)


def outcome(case, contingency_line, alpha, action, bus=None):
    """Post-action loading and minimum voltage from a real power flow."""
    net = load_case(case)
    if contingency_line is not None:
        net.line.at[contingency_line, "in_service"] = False
    base = scale_loads(net, 1.0)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        cost = apply_action(net, action, alpha, base, bus=bus)
        if not solve(net):
            return {"converged": False, "loading": float("inf"), "min_vm": 0.0, "cost": cost}
        loading = float(net.res_line.loading_percent.max()) / 100.0
        if len(net.trafo):
            loading = max(loading, float(net.res_trafo.loading_percent.max()) / 100.0)
        vm = float(net.res_bus.vm_pu[net.bus.in_service].min())
    return {"converged": True, "loading": loading, "min_vm": vm, "cost": cost}


# ---------------------------------------------------------------- MDP

@dataclass
class MDP:
    P: np.ndarray          # (actions, states, states)
    R: np.ndarray          # (states, actions)
    details: list = field(default_factory=list)


def compute_outcomes(case, cal, bus=None):
    """Power-flow outcome of every (state, action) pair. Independent of k, lambda0 and the weights,
    so sensitivity sweeps reuse this table."""
    table = {}
    for s in STATES:
        if s == "S3":
            continue
        for action in ACTIONS:
            table[(s, action)] = outcome(case, cal.contingency, cal.alpha[s], action, bus=bus)
    return table


def build_mdp(case, cal, k=K_LOGISTIC, lambda0=LAMBDA0, w=(W1, W2, W3), bus=None, outcomes=None,
              collapse="voltage", k_voltage=K_VOLTAGE):
    """Reward and transition tensors from physical outcomes of each (state, action).

    collapse="voltage" (default): S2 -> S3 probability depends on the post-action minimum voltage.
    collapse="loading": the plan-style loading threshold lambda_V (kept for comparison; practically zero).
    """
    if collapse not in COLLAPSE_MODELS:
        raise ValueError(f"collapse must be one of {COLLAPSE_MODELS}")
    if outcomes is None:
        outcomes = compute_outcomes(case, cal, bus=bus)
    w1, w2, w3 = w
    nS, nA = len(STATES), len(ACTIONS)
    P = np.zeros((nA, nS, nS))
    R = np.zeros((nS, nA))
    details = []
    lam_v = cal.lambda_v
    if not np.isfinite(lam_v):
        raise ValueError("lambda_v must be finite: the voltage-limit point must be a converged power flow")
    for a_idx, action in enumerate(ACTIONS):
        for s_idx, s in enumerate(STATES):
            if s == "S3":
                P[a_idx, s_idx, s_idx] = 1.0
                R[s_idx, a_idx] = -(w1 * 0.5 ** 2 + w2 * V_REF ** 2)  # absorbing collapse penalty, paid each step
                continue
            res = outcomes[(s, action)]
            if res["converged"]:
                lam = res["loading"]
                overload = max(0.0, lam - 1.0)
                sag = max(0.0, V_REF - res["min_vm"])
                lam_eff = lam
            else:
                lam_eff = lam_v + 0.5
                overload, sag = 0.5, V_REF
            R[s_idx, a_idx] = -(w1 * overload ** 2 + w2 * sag ** 2 + w3 * res["cost"])
            if s == "S0":
                p_s1 = sigmoid(k * (lam_eff - lambda0))
                P[a_idx, 0, 0] = 1 - p_s1
                P[a_idx, 0, 1] = p_s1
            elif s == "S1":
                p_up = sigmoid(k * (lam_eff - 1.0))
                p_down = 1 - sigmoid(k * (lam_eff - lambda0))
                P[a_idx, 1, 2] = p_up
                P[a_idx, 1, 0] = (1 - p_up) * p_down
                P[a_idx, 1, 1] = (1 - p_up) * (1 - p_down)
            elif s == "S2":
                if collapse == "voltage":
                    vm_eff = res["min_vm"] if res["converged"] else 0.0
                    p_v = sigmoid(k_voltage * (VOLTAGE_LIMIT - vm_eff))
                else:
                    p_v = sigmoid(k * (lam_eff - lam_v))
                p_recover = 1 - sigmoid(k * (lam_eff - 1.0))
                P[a_idx, 2, 3] = p_v
                P[a_idx, 2, 1] = (1 - p_v) * p_recover
                P[a_idx, 2, 2] = (1 - p_v) * (1 - p_recover)
            details.append({"state": s, "action": action, "converged": res["converged"],
                            "loading": res.get("loading"), "min_vm": res.get("min_vm"),
                            "cost": res["cost"], "reward": R[s_idx, a_idx]})
    if not np.allclose(P.sum(axis=2), 1.0):
        raise AssertionError("transition rows do not sum to 1")
    return MDP(P=P, R=R, details=details)


def value_iteration(mdp, gamma=GAMMA, tol=1e-10, max_iter=20000):
    """Infinite-horizon value iteration. Returns V, policy and the max-change history per iteration."""
    V = np.zeros(mdp.R.shape[0])
    history = []
    for it in range(1, max_iter + 1):
        Q = mdp.R + gamma * np.einsum("ast,t->sa", mdp.P, V)
        V_new = Q.max(axis=1)
        delta = float(np.max(np.abs(V_new - V)))
        history.append(delta)
        V = V_new
        if delta < tol:
            break
    Q = mdp.R + gamma * np.einsum("ast,t->sa", mdp.P, V)
    policy = [ACTIONS[i] for i in Q.argmax(axis=1)]
    return {"V": V, "policy": policy, "iterations": it, "history": history, "converged": delta < tol}


def finite_horizon(mdp, horizon, gamma=GAMMA):
    """Backward induction over T steps (V_T = 0). Returns V_0, policy at step 0 and the change per step."""
    V = np.zeros(mdp.R.shape[0])
    changes = []
    policy0 = None
    for t in range(horizon, 0, -1):
        Q = mdp.R + gamma * np.einsum("ast,t->sa", mdp.P, V)
        V_new = Q.max(axis=1)
        changes.append(float(np.max(np.abs(V_new - V))))
        if t == 1:
            policy0 = [ACTIONS[i] for i in Q.argmax(axis=1)]
        V = V_new
    return {"V": V, "policy": policy0, "changes": changes}


def simulate_policy(mdp, policy, start_state, gamma=GAMMA, episodes=20000, horizon=400, seed=20261018):
    """Monte Carlo check of a policy: average discounted return from `start_state`, with its standard error.

    This does not use the Bellman equations. It samples transitions from mdp.P and sums rewards, so it
    checks the solver (value iteration) against the transition and reward tensors independently.
    Truncating at `horizon` steps loses at most gamma^horizon times the largest reward.
    """
    rng = np.random.default_rng(seed)
    nS = mdp.R.shape[0]
    action_index = {a: i for i, a in enumerate(ACTIONS)}
    returns = np.zeros(episodes)
    for ep in range(episodes):
        s = start_state
        total, discount = 0.0, 1.0
        for _ in range(horizon):
            a = action_index[policy[s]]
            total += discount * mdp.R[s, a]
            s = rng.choice(nS, p=mdp.P[a, s])
            discount *= gamma
        returns[ep] = total
    return float(returns.mean()), float(returns.std(ddof=1) / np.sqrt(episodes))


# ================================ item 4: multi-step MDP with load growth
# Learning/cost-derived reward weights (previously a single derived constant):
def derive_action_cost_weight(mean_repair_cost: float, total_budget: float) -> float:
    """Action-cost weight derived from repair costs by a stated rule.

    Rule: a repair costing C against a scenario budget B consumes the budget
    share f = C / B. Money and the load-shed penalty are equated through that
    share against the demo reference share f_ref = 1,750 / 14,000 = 0.125
    (8 demo tasks, 14,000 budget): w3 = W3_HEADLINE * f / f_ref, clamped to
    [0.02, W3_PLAN] so it can neither vanish nor exceed the plan weight.
    Cheaper repairs relative to the budget therefore *lower* the weight placed
    on interruption costs, exactly as the economics imply.
    """
    f = max(float(mean_repair_cost), 1.0) / max(float(total_budget), 1.0)
    f_ref = 1750.0 / 14000.0
    return float(np.clip(W3_HEADLINE * (f / f_ref), 0.02, W3))


def _reward_components(mdp: MDP):
    """Decompose the recorded rewards back into overload, sag and action-cost
    parts (details carry loading / min_vm / cost per (state, action))."""
    ovl = np.zeros_like(mdp.R)
    sag = np.zeros_like(mdp.R)
    act = np.zeros_like(mdp.R)
    for d in mdp.details:
        a_idx = ACTIONS.index(d["action"])
        s_idx = STATES.index(d["state"])
        if d["converged"]:
            ovl[s_idx, a_idx] = max(0.0, float(d["loading"]) - 1.0) if np.isfinite(d["loading"]) else 0.5
            sag[s_idx, a_idx] = max(0.0, V_REF - float(d["min_vm"])) if np.isfinite(d["min_vm"]) else V_REF
        else:
            ovl[s_idx, a_idx] = 0.5
            sag[s_idx, a_idx] = V_REF
        act[s_idx, a_idx] = float(d["cost"])
    # The absorbing collapse state keeps its constant post-action penalty from R.
    ovl[STATES.index("S3"), :] = np.nan  # marked; overwritten below
    return ovl, sag, act, mdp.R[STATES.index("S3"), :].copy()


@dataclass
class MultiStepMDP:
    stage_mdps: list          # MDP per stage: same transitions, load-grown rewards
    growth: float             # per-stage load growth
    horizon: int
    derived_w3: float


def build_multistep(case, cal, horizon=5, growth=0.02, w=None, w3_repair_costs=None, **kwargs):
    """Time-expanded MDP: at stage t the system demand has grown by (1+g)^t, so the
    overload and sag penalties scale with that factor (the action interruption cost
    stays constant — documented choice). The w3 weight comes from repair costs via
    derive_action_cost_weight when w3_repair_costs=(mean_cost, budget) is given."""
    w = tuple(w) if w else HEADLINE_W
    w3 = w[2]
    if w3_repair_costs:
        w3 = derive_action_cost_weight(*w3_repair_costs)
    w = (w[0], w[1], w3)
    base = build_mdp(case, cal, w=w, **kwargs)
    ovl, sag, act, s3_row = _reward_components(base)
    ovl = np.nan_to_num(ovl, nan=0.0)
    sag = np.where(np.isnan(sag), 0.0, sag)
    stages = []
    for t in range(horizon):
        f = (1.0 + growth) ** t
        R = -(w[0] * f * ovl ** 2 + w[1] * f * sag ** 2 + w3 * act)
        R[STATES.index("S3"), :] = s3_row  # absorbing collapse penalty, constant per step
        stages.append(MDP(P=base.P, R=R, details=base.details))
    return MultiStepMDP(stage_mdps=stages, growth=growth, horizon=horizon, derived_w3=w3)


def multistep_solve(ms: MultiStepMDP, gamma=GAMMA, terminal_V=None):
    """Backward induction over the time-expanded model. Returns the per-stage
    optimal policies and stage-0 values; terminal_V (defaults 0) is the value at
    the end of the horizon."""
    V = np.zeros_like(ms.stage_mdps[-1].R[:, 0]) if terminal_V is None else np.asarray(terminal_V, dtype=float)
    values, policies = [], []
    for t in range(ms.horizon - 1, -1, -1):
        m = ms.stage_mdps[t]
        Q = m.R + gamma * np.einsum("ast,t->sa", m.P, V)
        V = Q.max(axis=1)
        policies.insert(0, [ACTIONS[i] for i in Q.argmax(axis=1)])
        values.insert(0, V.copy())
    return {"V0": values[0], "policy_by_stage": policies, "values_by_stage": values}
