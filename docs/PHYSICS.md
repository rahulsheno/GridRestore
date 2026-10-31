# Physics layer: IEEE benchmarks, state estimation, FDIA, MDP

Code: `backend/grid/`. Tests: `tests/test_grid_physics.py`, `tests/test_physics_store.py`,
`tests/test_physics_extras.py`. Artifacts: `docs/physics/`. Stored run: the newest row of `physics_runs`
(run 93 at the time of writing). Reproduce: `python -m backend.grid.physics_study` (about 6 minutes;
`--quick` for a fast check; `--keep-runs N` to prune older stored runs).

Scope: the five IEEE test cases bundled with pandapower (case9, case14, case30, case57, case118).
Distribution networks (mv_oberrhein) are out of scope.

## 1. Headline settings

| Setting | Value | Why |
| --- | --- | --- |
| Generator reactive limits | enforced | Without them, generators supply any reactive power and loadability is overstated by up to 2x (section 2.9). |
| Line ratings | 60 % loaded in the base case | pandapower's bundled ratings are not usable (section 2.5). |
| Reward weights | w1 = 10, w2 = 5, w3 = 0.1153 (derived, section 5.2) | Half the smallest weight at which mitigation becomes optimal in the thermal state, over every stress vector. The plan's w3 = 1 is reported alongside. |
| Collapse transition | voltage-based, K_V = 100 | Assumption; swept in section 5.5. |
| Discount factor | gamma = 0.95 | Plan value; swept in section 5.5. |
| Continuation | bisection on the load factor, each solve from a flat start | Path-independent (section 2.11). A predictor-corrector trace is the cross-check (section 5.8). |
| LNR threshold | calibrated to 1 % clean false alarm (about 3.8) | A fixed 3.0 is not calibrated for 80 to 170 measurements (section 4.3). |

## 2. Corrections and fixes made during validation

Each was found by checking against an independent reference, not assumed.

**2.1 PTDF formula.** The plan writes `PTDF = D A_r^T B_r^-1` with `B_r = A_r D A_r^T`. The shapes do not
conform. The standard DC result is `PTDF = D A_r (A_r^T D A_r)^-1` (A_r: branch-bus incidence, slack column
removed). Validated against pandapower's DC solver: maximum error below 5e-12 MW on all five cases.

**2.2 Transformer susceptance.** Dividing the reactance by the tap before inverting gives tap/x instead of
1/(x tap). Three tap conventions were compared against pandapower's flows; only 1/(x tap) matches (0.000 MW).

**2.3 Reference angle.** case118's external grid is at 30 degrees. It is now a known model input
(`ACModel.theta_ref`), not assumed to be 0.

**2.4 Reactive injection.** pandapower's `res_bus.q_mvar` excludes shunts. The physical injection is
`-res_bus.q_mvar + res_shunt.q_mvar`.

**2.5 Re-rating.** pandapower's ratings give case14 lines at 1.5 % loading and case30 at 112 % before any
stress. Line ratings are scaled to 60 % base loading. Transformers are not re-rated, because `sn_mva` also
sets their per-unit impedance; re-rating them made the power flow diverge.

**2.6 Proportional dispatch.** Scaling only the loads makes the slack bus absorb the surplus (-69.5 MW on
case30 at half load). Loads and non-slack generator setpoints are scaled together.

**2.7 Bisection returned a diverged point.** The root finder could return the non-converged side of its
bracket, giving infinite loadings. It now returns the converged side.

**2.8 Isolation cost and node choice.** The first isolate action picked a bus with no load and counted zero
cost while removing a generator. Candidates are now load-carrying buses, and the cost is the MW of load and
generation disconnected divided by total load plus generation.

**2.9 Generator reactive limits (largest correction).** Enforcing them roughly halves the loadability:

| Case | Voltage limit, unlimited Q | Voltage limit, limited Q | Nose, unlimited Q | Nose, limited Q |
| --- | ---: | ---: | ---: | ---: |
| case9 | 1.78 | 1.78 | 2.49 | 2.47 |
| case14 | 3.36 | 1.60 | 4.06 | 1.78 |
| case30 | 3.04 | 2.46 | 5.48 | 2.85 |
| case118 | 2.66 | 1.78 | 3.19 | 2.14 |

The earlier figures in this document, and the first stored runs, used unlimited Q and overstated
loadability. Those runs were pruned. The switch is one module-level flag (`cases.ENFORCE_Q_LIMS`); every
power flow goes through `cases.run_powerflow`. The measurement model still matches pandapower's solution with
limits enforced (4.9e-11 pu).

**2.10 DC model build.** The DC model reads topology and branch parameters from pandapower's internal arrays.
Those do not depend on reactive limits, and some contingencies converge without limits but not with them. The
DC model therefore always builds from an unlimited-Q solve. The stress-vector calibrations all converge with
limits enforced (checked for every N-1 case).

**2.11 Warm-start bias in bisection.** pandapower's default starts each solve from the previous solution. The
continuation bisection therefore depended on the order of its evaluations: case9's nose moved by 0.02 between
orders. Every solve now starts from a flat point (`init="flat"`), and a test checks that the reversed order gives
the same nose. The case9 nose (2.4673) is now confirmed by fresh solves: a solve from a flat start converges at
2.4673 and fails at 2.47.

**2.12 Analytic Jacobian.** The measurement Jacobian is now closed-form (`ac_se.jacobian_analytic`), and the
numerical version is kept as the reference. They agree to about 1e-10 relative error on all five cases. The
analytic form is 5 to 8 times faster (case118: 2.3 ms against 18.8 ms), which speeds up every estimator and
Monte Carlo loop.

## 3. Validation

Measured against pandapower's own solutions (`ptdf_validation.csv`, `measurement_model_validation.csv`):

| Case | PTDF line flow error (MW) | Injection error, pu (V / P / Q) | Line flow error, MVA |
| --- | ---: | --- | ---: |
| case9 | 6e-14 | 0 / 6e-14 / 3e-14 | 7e-14 |
| case14 | 2e-13 | 0 / 3e-15 / 8e-15 | 9e-14 |
| case30 | 5e-14 | 0 / 1e-9 / 6e-10 | 4e-13 |
| case57 | 2e-13 | 0 / 7e-15 / 1e-14 | 3e-13 |
| case118 | 2e-12 | 0 / 5e-14 / 4e-14 | 1e-12 |

Gauss-Newton recovers the true state from noise-free measurements to better than 1e-9. The analytic Jacobian
agrees with the numerical one to about 1e-10 relative error.

**Newton power flow from a flat start** (`pflow.py`, own solver with generator Q-limit switching) reproduces
pandapower's solution to about 1e-11 rad on case9, case14, case30 and case118, including the six reactive-limit
switches on case118. The base solution is not taken from pandapower in this test, so the agreement is an
independent result.

**Chi-squared calibration.** The clean false-alarm rate is 1 % on case14 (2 of 200), 1 % on case30 (2 of 200)
and 0 % on case118 (0 of 50). The design rate is 1 %.

**Policy simulation.** Monte Carlo rollouts of the optimal policy (4000 episodes per state, case14, before the
Q-limit change) give discounted returns within 1.7 standard errors of the value-iteration values. The
positive deviations come from a single random stream, so this is consistent with a correct solver, not a proof.
The unit test re-checks the current model.

## 4. Attacks and detection

### 4.1 Stealthy attack, DC (exact)
The linear stealthy attack leaves the residual invariant: |J(z+a) - J(z)| is 4e-14 (case14), 9e-14 (case30),
3e-13 (case118). The chi-squared test does not detect it. A random attack of the same size is detected in
every case.

### 4.2 Stealthy attack, AC (approximate), 200 trials (case118: 50)

| Case | Clean false alarm | Stealthy bypass | Median J change / threshold | Median max flow shift (pu) | Random detected |
| --- | ---: | ---: | ---: | ---: | ---: |
| case14 | 1 % | 99 % | 2e-7 | 0.0026 | 100 % |
| case30 | 1 % | 99 % | 5e-9 | 0.0007 | 100 % |
| case118 | 0 % | 100 % | 4e-10 | 0.0009 | 100 % |

The 1 % of stealthy attacks flagged in case14 and case30 are exactly the trials in which the unattacked
measurements already crossed the threshold; the attack leaves J unchanged in those trials.

The stealthy attack moves the estimated flows by about 0.07 to 0.26 MW on a 100 MVA base (0.0007 to 0.0026 pu),
because the 15 % bound and the topology limit how far the estimate can move.

### 4.3 Largest normalised residual (LNR)

The threshold of 3.0 is not calibrated for this many measurements: on clean data it flags 15.5 % (case14, 82
measurements) and 36.5 % (case30, 172 measurements). Those are the numbers in `fdia_lnr_targeted.csv`, and
they cannot be used to judge detection.

With the threshold set to the 99th percentile of clean data (`lnr_calibration.csv`, produced by
`python -m backend.grid.calibrate_lnr`; 3.79 on case14, 3.74 on case30):

| Attack | Detection at 1 % clean false alarm |
| --- | ---: |
| Stealthy (case14, 200 trials) | 1 % |
| Targeted (case14, 200 trials) | 1 % |
| Targeted (case30, 100 trials) | 2 % |

**Correction.** An earlier version of this document said LNR detects targeted attacks. That came from a
small sample (8 trials) and an uncalibrated threshold. At a valid operating point, neither the stealthy nor
the targeted attack is detected.

### 4.4 Targeted stealthy attack
A linear programme chooses the stealthy state change that moves one branch flow estimate the most, within
the same bounds, for the branch the programme can move most. The AC re-estimate confirms the linear
prediction: median achieved shift 0.1282 pu against a predicted 0.1282 pu (case14, 100 trials); 0.0224 pu
against 0.0225 pu (case30, 100 trials). The max-energy attack moves the same flows by 2.1e-5 pu (case14) and
1.4e-5 pu (case30), so the targeted attack is about 6000 times stronger on case14 and about 1600 times on case30.

Bypass: 100 % (case14), 97 % (case30) of trials. The targeted attack's detection rate under LNR at the uncalibrated
threshold of 3.0 is 15 % (case14) and 34 % (case30), which is no higher than the clean false-alarm rate at that
threshold (15.5 % and 36.5 %; section 4.3).

## 5. MDP and operating points

### 5.1 Definitions
- Loading is the maximum branch loading as a fraction of rating (1.0 = 100 %). Voltage is per unit.
- overload = max(0, loading - 1); sag = max(0, 0.95 - minimum voltage).
- Action cost = MW of load and generation disconnected, divided by total load plus total generation.
  Shedding 20 % of load costs 0.2 times the load share.
- Reward R = -(10 overload^2 + 5 sag^2 + w3 cost), with w3 = 0.1153 (headline) or 1 (plan).

### 5.2 Weights (derived)
The action-cost weight needs a value, and no dollar cost model is available to set it. The headline uses a
stated decision rule instead:

> w3 = half of the smallest action-cost weight at which mitigation becomes optimal in the thermal state (S2),
> taken over every stress vector on both networks.

"Mitigation" means any action other than doing nothing. The halving is a safety margin: it keeps the choice
clear of the boundary. Thresholds were found by bisection under the limited-Q model:

| Case | Stress vector | Threshold |
| --- | --- | ---: |
| case14 | base | 0.4482 |
| case14 | N-1 line 0 | 0.4105 |
| case14 | N-1 line 1 | **0.2305** (smallest) |
| case30 | base | 0.7309 |
| case30 | N-1 line 0 | 0.2478 |
| case30 | N-1 line 3 | 0.2396 |

Smallest threshold 0.2305, so w3 = 0.1153 (`w3_choice.csv`; the thresholds are saved to four decimals, so half
of 0.2305 is rounded half up here). The rule is a choice of decision criterion. It is not derived from a cost
model, so a different rule would give a different value. The plan's w3 = 1 is reported alongside.

On case14 with line 0 out, the thermal-state action at w3 = 0.1153 is isolate node, not load shedding. That is
why the rule counts any mitigation, not load shedding specifically.

**Corrections.** Earlier versions gave 0.26 and 0.57, and called w3 = 0.1 the threshold itself. Those values
came from the unlimited-Q model, and 0.1 was never the boundary. An earlier version of this rule also required
load shedding specifically, which has no threshold on case14 with line 0 out.

### 5.3 Collapse transition
    P(S3 | S2, a) = sigmoid( K_V (0.85 - min voltage after a) ),  K_V = 100

It is 0.5 at 0.85 pu and about 3e-4 at 0.93 pu. Divergence after an action counts as collapse.

Probability of collapse from the thermal state S2 (base stress vector, headline weights):

| Case | Do nothing | Load shed | Isolate node |
| --- | ---: | ---: | ---: |
| case14 | 1.6e-4 | 1.1e-7 | 0.82 |
| case30 | 4.2e-4 | 6.8e-5 | 3.2e-4 |

Isolating the chosen node makes collapse likely on case14. The policy avoids it, so the headline result is
unaffected, but any study that allows isolation has to report this. Under the contingency stress vectors,
collapse probabilities for every action (isolation included) range from 3e-8 to 1.5e-5.

### 5.4 Policies (headline weights, base stress vector)

| Case | S0 | S1 | S2 (thermal) | S3 |
| --- | --- | --- | --- | --- |
| case14 | do nothing (V* = -0.0377) | do nothing (-0.0543) | load shed (-0.0771) | absorbing (-140.25) |
| case30 | do nothing (-0.0564) | do nothing (-0.0813) | load shed (-0.1138) | absorbing (-140.25) |

Under the N-1 outage of line 0 on case14, the optimal thermal action is isolate node (not load shed). With
the plan's weights (w3 = 1), do nothing is optimal in every state of every stress vector.

### 5.5 Sensitivity (case30 base, `sensitivity_grid.csv`, `sensitivity_heatmap.png`)

- **Steepness (k) and normal limit (lambda0).** V*(S0) runs from -0.152 (k = 5, lambda0 = 0.70) to -2e-7
  (k = 40, lambda0 = 0.90). Load shedding is optimal in S2 across the whole grid.
- **Weights.** At w1 = 10, do nothing is optimal in S2 at w3 = 1 and load shedding at w3 = 0.1 and 0.01.
  At w3 = 0.1, load shedding is optimal for every w1 tested (10 to 10000).
- **Voltage scale (K_V).** P(S3 | S2) under do nothing is 2.0e-2 at K_V = 50, 4.2e-4 at 100 and 1.8e-7 at
  200. V*(S0) is -0.208, -0.056 and -0.041. The policy in S2 does not change.
- **Discount factor (gamma).** V*(S0) is -0.0195 (gamma = 0.90), -0.0564 (0.95) and -0.377 (0.99). The policy
  does not change.

### 5.6 Continuation (load scaling with bisection)
`operating_point.continuation` scales loads and non-slack generator setpoints together, under the headline
Q-limit setting, and records the operating status at each step. It reports the voltage limit (first
minimum voltage below 0.85 pu) and the nose (last converged point before divergence, by bisection to 1e-4).
This is a load-scaling sweep, not a predictor-corrector method.

| Case | Voltage limit | Nose | First thermal overload |
| --- | ---: | ---: | ---: |
| case9 | 1.78 | 2.47 | 1.42 |
| case14 | 1.60 | 1.78 | 1.40 |
| case30 | 2.46 | 2.85 | 1.56 |
| case57 | below base (base minimum voltage 0.72) | 1.41 | not reached |
| case118 | 1.78 | 2.14 | 1.22 |

case57 is excluded from the MDP for that reason. Divergence (SOLVER_DIVERGENCE) is kept separate from the
physical states throughout.

### 5.7 Convergence
Infinite-horizon value iteration (gamma = 0.95, tolerance 1e-10) takes 488 iterations on every case; the rate
depends on gamma, not on the network. Finite-horizon values approach the infinite-horizon ones. The error is
reported separately for the thermal states S0 to S2 and the absorbing state S3, because S3's constant
reward (-140) converges slowly and would otherwise hide the thermal convergence.

| Case | S0 to S2 error at T = 5 / 40 / 160 | S3 error at T = 5 / 40 / 160 |
| --- | --- | --- |
| case14 | 0.040 / 0.0061 / 1.3e-5 | 109 / 18.0 / 0.038 |
| case30 | 0.072 / 0.016 / 6.7e-5 | 109 / 18.0 / 0.038 |

### 5.8 Predictor-corrector continuation (cross-check)

`pflow.trace` follows the solution branch with pseudo-arc-length continuation: a predictor along the unit tangent,
a Newton corrector on the augmented system, and step control that shortens steps near the turning point. Generator
Q limits switch buses to PQ during the trace, and the tangent is carried across each switch. The nose is found as
the turning point (interpolated) or, after a switch, by bisection between the last traced state and the failed
solve.

| Case | Trace nose | Bisection nose | Difference | Trace voltage limit | Bisection voltage limit |
| --- | ---: | ---: | ---: | ---: | ---: |
| case9 | 2.46731 | 2.46727 | 4e-5 | 1.790 | 1.78 |
| case14 | 1.77800 | 1.77797 | 3e-5 | 1.607 | 1.60 |
| case30 | 2.85386 | 2.85383 | 3e-5 | 2.473 | 2.46 |
| case57 | 1.41478 | 1.41469 | 9e-5 | not reached | not reached |
| case118 | 2.11065 | 2.14008 | 0.03 | 1.777 | 1.78 |

The two methods agree on the nose to about 1e-4 on case9, case14, case30 and case57. The voltage limit is
interpolated between traced points, so it is accurate to about 0.01; the bisection is exact to its tolerance.

**case118: the tracer is right and the bisection is on a different branch.** A warm-started continuation along
the branch that starts at the base case (small steps, each solved from the previous solution) stops at
lambda = 2.110649, the same point the trace finds (2.11065). Comparing the warm path with flat-start solves at the
same load factors shows why the bisection disagrees: the two solutions already differ at lambda = 1.88 (angle
difference 0.019 rad), so the flat-start solver lands on a different solution of the same equations somewhere
between lambda = 1.0 and 1.88. The bisection solves every point from a flat start and therefore follows that other
branch, which folds at 2.14. Both values are real solutions of the power-flow equations; the one connected to the
base operating point is the 2.11 branch.

So on case118 the trace is correct, and the bisection's 2.14 is the loadability of a different branch, not of the
operating point. The bisection is accurate where the flat-start and warm-start branches coincide (case9, case14,
case30, case57), and is not the right method on case118.

The trace agrees with warm-started stepping on case118 and with the bisection on case9, case14, case30 and case57.
It follows the branch connected to the operating point, so it is the more faithful method, but it is still a
cross-check here: the headline decision was taken on the basis of the bisection, and changing it is a decision for
the project owner (section 8).

**Status of the headline (bisection).** The bisection is the headline as decided. Its accuracy is established only
where it can be checked:
- On case9, case14, case30 and case57 it agrees with the warm-start branch (trace) to about 1e-4.
- On case118 it reports a different solution branch (2.14) from the base operating point's branch (2.11). It is
  therefore not an accurate loadability for that network, and the earlier statement that it is accurate on every case
  was wrong.
A decision is needed: use the branch-following value (the trace, 2.11 on case118) as the headline, or keep the
bisection and state that it reports the flat-start branch. Section 8 records the choice.

## 6. Limitations
- **Scope:** IEEE cases only; no distribution networks.
- **Ratings:** line ratings are a modelling choice (60 % base loading). Loadability depends on it.
- **Dispatch:** proportional scaling; no redispatch by optimal power flow; generator Q limits are enforced,
  but not active-power limits.
- **Thresholds:** 80 %, 100 %, 0.85 pu and 0.95 pu are assumptions. So are the state representatives
  (loading 0.60, 0.90, 1.05) and the voltage scale K_V.
- **MDP:** one-step transitions from the post-action state; no multi-step load growth. The headline w3 comes
  from a stated decision rule (section 5.2), not a cost model; the plan's w3 = 1 is reported alongside it.
- **Continuation:** the headline is a bisection on the load factor, which is exact to its tolerance but does not
  trace the curve. The predictor-corrector trace follows the curve, but is unreliable on case118 (section 5.8). The
  trace's one-way Q-limit switching (no return to PV by default) is a further limit.
- **Estimator:** own Gauss-Newton with the analytic Jacobian, checked against a numerical reference (section 2.12).
- **AC attacks:** invariance is approximate; attacks are built from the Jacobian at the clean estimate.
- **Targeted attack:** does not account for the LNR test; an attacker who knew about it would add that constraint.
- **Cyber:** the four-tier topology (`data/cyber_topology.json`) is stylised, not a vulnerability assessment,
  and the RTU-to-bus assignment is a graph-distance partition, not a real substation map.
- **Study driver:** `physics_study.py` runs in about 6 minutes and is not part of the automated test suite
  (coverage 0 %); its components are tested individually.

## 7. Database, REST API and Physics tab

**Storage.** Migration `006_physics.sql` creates eleven `physics_*` tables keyed by `run_id`; migration
`007_physics_extensions.sql` adds the unlimited-Q comparison columns, the LNR and targeted FDIA kinds, and the
discount-factor sweep. `backend/grid/store.py` writes a run in one transaction from the same results dictionary
that produces the CSV files, and provides `prune_runs(keep, only=None)`.

**REST (read-only, both roles, `backend/physics_api.py`).** `GET /api/physics/runs`,
`/runs/{id}` (overview), `/runs/{id}/continuation/{case}`, `/runs/{id}/fdia/{case}/trials`,
`/runs/{id}/mdp/{case}?weight_set=headline|plan`, `/runs/{id}/sensitivity`,
`/runs/{id}/convergence/{case}/{stress}`, `/runs/{id}/figures/{name}`. Unknown runs return 404; a missing
token returns 401.

**Physics tab (`frontend/components/PhysicsPanel.tsx`).** Run and case selectors; validation table; the
continuation chart with the 0.85 pu limit and the voltage-limit and nose markers, plus the unlimited-Q
comparison in the caption; FDIA summaries (including LNR and targeted rows); the policy table with a
headline/plan switch; the sensitivity heatmap. Loading and per-section error states are shown.

**Browser check.** Driven in Chromium (puppeteer-core with a bundled Chromium build): admin sees all nine tabs
with no console errors; the operator sees the "Not allowed" messages on the audit and data tabs. The Physics
tab renders the continuation chart and the heatmap for both roles.

## 8. Revision log (this document)
- Generator reactive limits enforced; unlimited-Q values kept as a comparison (section 2.9).
- Collapse transition changed from loading-based to voltage-based (headline).
- Headline w3 changed from the plan's 1 to a derived value, 0.1153, by the rule in section 5.2 (replaces an
  earlier arbitrary 0.1 and a load-shed-only rule).
- LNR threshold calibrated; earlier claim about LNR detection withdrawn (section 4.3).
- Targeted attack added; earlier LNR-detection claim withdrawn.
- Discount-factor and voltage-scale sweeps added.
- DC model builds without reactive limits (section 2.10).
- Continuation solves start from a flat point; bisection is path-independent (section 2.11). On case118 the
  flat-start branch differs from the base-connected branch (section 5.8).
- Analytic Jacobian adopted; numerical kept as the reference (section 2.12).
- Case118: the bisection's value is a different solution branch; the base-connected branch nose is 2.1106 (section 5.8).
- Own Newton power flow and predictor-corrector trace added as a cross-check (section 5.8); the case118 trace
  limitation is recorded as an expected failure.
- Case118 investigated: the trace and warm-started stepping agree at 2.1106 on the base-connected branch; the
  bisection's 2.14 is a different solution branch. Headline choice left to the project owner.
- Reproducibility: the LNR calibration (`backend/grid/calibrate_lnr.py`) and the weight derivation
  (`backend/grid/calibrate_w3.py`) are now repository modules. Targeted-attack detection at the calibrated threshold
  is 1 % (case14) and 2 % (case30) on the current code.
