"""Newton power flow with generator Q-limit switching, and predictor-corrector continuation.

Unknowns: theta at all non-reference buses, and |V| at PQ buses. The reference bus has fixed |V| and angle;
PV buses have fixed |V|. Equations: P mismatch at every non-reference bus and Q mismatch at every PQ bus.

Load parameter lambda scales all loads (P and Q) and all non-reference generator P setpoints together
(proportional dispatch, as in operating_point.scale_loads). The reference bus absorbs the balance.

Q limits: when a PV bus's reactive output leaves [Qmin, Qmax] it is converted to PQ with its Q fixed at the
violated limit. The conversion is one-way during a trace (no return to PV), so the trace is exact only while
no bus returns to its setpoint. This is noted in docs/PHYSICS.md.

Continuation: pseudo-arc-length on z = (u, lambda). Predictor along the unit tangent, Newton corrector on
the augmented system, adaptive step. The nose is the turning point of lambda along the path, estimated
from the Hermite-type formula for the maximum of a quadratic through the two bracketing points.
"""
from dataclasses import dataclass, field

import numpy as np

from .cases import locate_branch


def _complex_derivatives(Y, V):
    """S = V conj(Y V) and its derivatives with respect to angle and magnitude (dense)."""
    Vn = V / np.abs(V)
    I = Y @ V
    S = V * np.conj(I)
    dS_dva = 1j * V[:, None] * np.conj(np.diag(I) - Y * V[None, :])
    dS_dvm = V[:, None] * np.conj(Y * Vn[None, :]) + np.diag(np.conj(I) * Vn)
    return S, dS_dva, dS_dvm


@dataclass
class Injections:
    """Specified quantities per ppc bus row, per unit on baseMVA (at lambda = 1)."""
    Pg: np.ndarray
    Pd: np.ndarray
    Qd: np.ndarray
    vset: np.ndarray          # voltage setpoint for PV and reference buses
    qmin: np.ndarray          # sum of generator minimum Q at the bus (-inf if none)
    qmax: np.ndarray          # sum of generator maximum Q at the bus (+inf if none)
    has_gen: np.ndarray       # bool per row (PV candidates)
    ref: int
    base: float


def injections_from_net(net, ac):
    """Read specified injections and setpoints from the pandapower network, in ppc row order."""
    n = ac.n
    base = ac.baseMVA
    row_of = {b: int(net._pd2ppc_lookups["bus"][b]) for b in net.bus.index}
    Pg, Pd, Qd = np.zeros(n), np.zeros(n), np.zeros(n)
    vset = np.ones(n)
    qmin = np.full(n, -np.inf)
    qmax = np.full(n, np.inf)
    has_gen = np.zeros(n, dtype=bool)
    ext_buses = set(net.ext_grid.bus.tolist())
    for _, ld in net.load[net.load.in_service].iterrows():
        r = row_of[ld.bus]
        Pd[r] += ld.p_mw / base
        Qd[r] += ld.q_mvar / base
    for idx, g in net.gen[net.gen.in_service].iterrows():
        r = row_of[g.bus]
        if g.bus in ext_buses:
            continue
        Pg[r] += g.p_mw / base
        has_gen[r] = True
        vset[r] = g.vm_pu
        qlo = g.min_q_mvar / base if "min_q_mvar" in net.gen.columns else -np.inf
        qhi = g.max_q_mvar / base if "max_q_mvar" in net.gen.columns else np.inf
        qmin[r] = (0.0 if qmin[r] == -np.inf else qmin[r]) + qlo
        qmax[r] = (0.0 if qmax[r] == np.inf else qmax[r]) + qhi
    ref_row = ac.ref
    for b in net.ext_grid.bus:
        vset[row_of[b]] = float(net.ext_grid.vm_pu[net.ext_grid.bus == b].iloc[0])
    return Injections(Pg=Pg, Pd=Pd, Qd=Qd, vset=vset, qmin=qmin, qmax=qmax, has_gen=has_gen,
                      ref=ref_row, base=base)


@dataclass
class State:
    theta: np.ndarray
    vm: np.ndarray
    pq: np.ndarray            # bool per row: PQ bus (magnitude unknown)
    qfix: np.ndarray          # per row: fixed generator Q when switched to PQ (nan if not switched)
    switched: list = field(default_factory=list)


class PowerFlow:
    def __init__(self, net, ac, inj):
        self.net, self.ac, self.inj = net, ac, inj
        self.Y = ac.Ybus
        self.Yf = ac.Yf
        self.f = ac.f
        self.n = ac.n
        self.ref = ac.ref
        self.nonref = np.array(ac.non_ref)

    # -------------------------------------------------------------- residual and Jacobian
    def _unknowns(self, st):
        pq_rows = np.where(st.pq)[0]
        return pq_rows

    def _spec(self, st, lam):
        inj = self.inj
        P = lam * (inj.Pg - inj.Pd)
        Q = -lam * inj.Qd
        fixed = ~np.isnan(st.qfix)
        Q = np.where(fixed, st.qfix - lam * inj.Qd, Q)
        return P, Q

    def _pack(self, st):
        return np.concatenate([st.theta[self.nonref], st.vm[self._unknowns(st)]])

    def _unpack(self, st, u):
        k = len(self.nonref)
        st.theta[self.nonref] = u[:k]
        pq_rows = self._unknowns(st)
        st.vm[pq_rows] = u[k:]
        return st

    def _mismatch(self, st, lam):
        V = st.vm * np.exp(1j * st.theta)
        S, _, _ = _complex_derivatives(self.Y, V)
        P_spec, Q_spec = self._spec(st, lam)
        pq_rows = self._unknowns(st)
        F = np.concatenate([S.real[self.nonref] - P_spec[self.nonref], S.imag[pq_rows] - Q_spec[pq_rows]])
        return F, S

    def _jacobian(self, st, lam):
        V = st.vm * np.exp(1j * st.theta)
        S, dS_dva, dS_dvm = _complex_derivatives(self.Y, V)
        pq_rows = self._unknowns(st)
        J = np.block([
            [dS_dva.real[np.ix_(self.nonref, self.nonref)], dS_dvm.real[np.ix_(self.nonref, pq_rows)]],
            [dS_dva.imag[np.ix_(pq_rows, self.nonref)], dS_dvm.imag[np.ix_(pq_rows, pq_rows)]],
        ])
        return J

    def dF_dlambda(self, st):
        inj = self.inj
        pq_rows = self._unknowns(st)
        return np.concatenate([-(inj.Pg - inj.Pd)[self.nonref], inj.Qd[pq_rows]])

    # -------------------------------------------------------------- Newton power flow
    def solve(self, st, lam, tol=1e-10, max_iter=40):
        """Newton iteration at fixed lambda, then Q-limit checks. Returns the converged state."""
        for _ in range(20):
            u = self._pack(st)
            for it in range(max_iter):
                F, _ = self._mismatch(st, lam)
                if np.max(np.abs(F)) < tol:
                    break
                J = self._jacobian(st, lam)
                u = u - np.linalg.solve(J, F)
                self._unpack(st, u)
            else:
                raise RuntimeError("Newton power flow did not converge")
            if not self.enforce_q(st, lam):
                return st
        raise RuntimeError("Q-limit switching did not settle")

    def generator_q(self, st, lam):
        """Reactive output of each generator bus (pu): net injection plus the load's Q."""
        V = st.vm * np.exp(1j * st.theta)
        S, _, _ = _complex_derivatives(self.Y, V)
        return S.imag + lam * self.inj.Qd

    def enforce_q(self, st, lam):
        """Switch PV buses whose Q is outside their limits to PQ at the violated limit. True if any switched."""
        from .cases import ENFORCE_Q_LIMS
        if not ENFORCE_Q_LIMS:
            return False
        qg = self.generator_q(st, lam)
        changed = False
        for r in np.where(self.inj.has_gen & ~st.pq & (np.arange(self.n) != self.ref))[0]:
            if qg[r] > self.inj.qmax[r]:
                st.qfix[r] = self.inj.qmax[r]
            elif qg[r] < self.inj.qmin[r]:
                st.qfix[r] = self.inj.qmin[r]
            else:
                continue
            st.pq[r] = True
            st.switched.append(int(r))
            changed = True
        return changed

    def try_reverse(self, st, lam):
        """Return a switched bus to PV if the solution with its voltage at setpoint keeps its Q inside limits.

        Tried one bus at a time on a copy of the state. Returns (new_state, returned_rows) and leaves the
        input untouched when nothing is returned.
        """
        returned = []
        for r in list(st.switched):
            if not st.pq[r] or np.isnan(st.qfix[r]):
                continue
            trial = State(theta=st.theta.copy(), vm=st.vm.copy(), pq=st.pq.copy(), qfix=st.qfix.copy(),
                          switched=list(st.switched))
            trial.pq[r] = False
            trial.qfix[r] = np.nan
            trial.vm[r] = self.inj.vset[r]
            try:
                trial = self.solve(trial, lam)
            except RuntimeError:
                continue
            if r in trial.switched:      # re-switched immediately: not a reverse
                continue
            if trial.pq[r] is False and not np.isnan(trial.qfix[r]):
                continue
            st = trial
            returned.append(int(r))
        return st, returned

    def base_state(self):
        """Initial state from pandapower's converged solution (ppc order), with its PV/PQ structure."""
        net = self.net
        n = self.n
        theta = np.zeros(n)
        vm = np.ones(n)
        for b in net.bus.index:
            r = int(net._pd2ppc_lookups["bus"][b])
            theta[r] = np.deg2rad(net.res_bus.va_degree.loc[b])
            vm[r] = net.res_bus.vm_pu.loc[b]
        pq = np.ones(n, dtype=bool)
        pq[self.ref] = False
        pq[self.inj.has_gen] = False
        return State(theta=theta, vm=vm, pq=pq, qfix=np.full(n, np.nan))

    def set_setpoints(self, st):
        """Fix |V| at PV and reference buses to their setpoints."""
        pv = ~st.pq
        st.vm[pv] = self.inj.vset[pv]
        st.theta[self.ref] = self.ac.theta_ref
        return st

    # -------------------------------------------------------------- loading and voltages
    def loadings(self, st):
        """Maximum branch loading (fraction of rating) and per-branch loading, using pandapower's current definition."""
        V = st.vm * np.exp(1j * st.theta)
        Sf = V[self.f] * np.conj(self.Yf @ V)
        loads = []
        for k, row in enumerate(self.ac.branch_rows):
            elm, loc = locate_branch(self.net, int(row))
            if elm == "line":
                vn = float(self.net.bus.vn_kv.loc[self.net.line.from_bus.iloc[loc]])
                i_ka = abs(Sf[k]) * self.inj.base / (np.sqrt(3) * vn * abs(V[self.f[k]]))
                loads.append(i_ka / float(self.net.line.max_i_ka.iloc[loc]))
            else:
                loads.append(abs(Sf[k]) * self.inj.base / float(self.net.trafo.sn_mva.iloc[loc]))
        return float(np.max(loads)) if loads else 0.0


def _map_tangent(t, pq_old, pq_new, nonref):
    """Map a tangent (theta rows, PQ-magnitude rows, lambda) onto a new PQ set. New PQ buses get zero."""
    k = len(nonref)
    theta_part = t[:k]
    old_rows = np.where(pq_old)[0]
    v_old = dict(zip(old_rows.tolist(), t[k:-1].tolist()))
    new_rows = np.where(pq_new)[0]
    v_new = np.array([v_old.get(int(r), 0.0) for r in new_rows])
    out = np.concatenate([theta_part, v_new, [t[-1]]])
    return out / np.linalg.norm(out)


# ---------------------------------------------------------------- continuation

def trace(pf, lam_start=1.0, lam_max=8.0, h0=0.05, h_min=1e-6, h_max=0.2, voltage_limit=0.85,
          max_points=4000, reverse_switching=False):
    """Pseudo-arc-length trace of the solution branch from lam_start upward.

    Returns (points, summary). points: list of dicts with lambda, min_vm, max_loading, status, and switched.
    summary: voltage_limit_alpha (first crossing of voltage_limit, interpolated), nose_alpha (turning point),
    first_s2_alpha (first loading >= 1, interpolated), switched_buses, and the number of corrector steps.
    """
    st = pf.set_setpoints(pf.base_state())
    st = pf.solve(st, lam_start)
    lam = lam_start
    u = pf._pack(st)
    z = np.concatenate([u, [lam]])
    tangent_prev = None
    h = h0
    points = []
    summary = {"voltage_limit_alpha": None, "nose_alpha": None, "first_s2_alpha": None,
               "switched_buses": [], "corrector_steps": 0}
    prev = None
    nose_pair = None   # (lambda_a, slope_a, s_a, lambda_b, slope_b, s_b) around the turning point
    s_arc = 0.0

    def record(st, lam):
        V = st.vm * np.exp(1j * st.theta)
        min_vm = float(np.min(st.vm))
        loading = pf.loadings(st)
        if min_vm < voltage_limit:
            status = "S3"
        elif loading >= 1.0:
            status = "S2"
        elif loading >= 0.8:
            status = "S1"
        else:
            status = "S0"
        return {"alpha": lam, "min_vm": min_vm, "max_loading": loading, "status": status}

    points.append(record(st, lam))
    last_ok_state = State(theta=st.theta.copy(), vm=st.vm.copy(), pq=st.pq.copy(),
                          qfix=st.qfix.copy(), switched=list(st.switched))
    last_ok_lam = lam
    nose_found_by_failure = False
    for _ in range(max_points):
        F, _ = pf._mismatch(st, lam)
        Ju = pf._jacobian(st, lam)
        dF = pf.dF_dlambda(st)
        v = np.linalg.solve(Ju, -dF)
        t = np.concatenate([v, [1.0]])
        t /= np.linalg.norm(t)
        if tangent_prev is not None and len(tangent_prev) == len(t):
            if np.dot(t, tangent_prev) < 0:
                t = -t
        elif t[-1] < 0:
            t = -t
        # predictor and corrector
        accepted = False
        for _try in range(60):
            z_pred = z + h * t
            zc = z_pred.copy()
            ok = False
            for it in range(8):
                u_c, lam_c = zc[:-1], zc[-1]
                st_c = State(theta=st.theta.copy(), vm=st.vm.copy(), pq=st.pq.copy(), qfix=st.qfix.copy(),
                             switched=list(st.switched))
                pf._unpack(st_c, u_c)
                F_c, _ = pf._mismatch(st_c, lam_c)
                summary["corrector_steps"] += 1
                G = np.concatenate([F_c, [np.dot(t, zc - z_pred)]])
                if np.max(np.abs(G)) < 1e-9:
                    ok = True
                    break
                Ju_c = pf._jacobian(st_c, lam_c)
                dF_c = pf.dF_dlambda(st_c)
                Jaug = np.block([[Ju_c, dF_c[:, None]], [t[None, :]]])
                try:
                    dz = np.linalg.solve(Jaug, -G)
                except np.linalg.LinAlgError:
                    break
                zc = zc + dz
            if ok:
                accepted = True
                st = st_c
                z = zc
                lam = float(z[-1])
                tangent_prev = t
                cap = h_max if abs(t[-1]) > 0.5 else 0.01   # short steps near the turning point
                h = min(h * 1.5, cap) if it <= 3 else h
                break
            h *= 0.5
            if h < h_min:
                break
        if not accepted:
            break
        s_arc += h
        # Q-limit switching at the accepted point
        if reverse_switching:
            # Off by default: on case118 it cost about 40x in time and did not change the nose.
            st, returned = pf.try_reverse(st, lam)
            if returned:
                z = np.concatenate([pf._pack(st), [lam]])
                tangent_prev = None
                summary.setdefault("returned_buses", []).extend(returned)
        before = len(st.switched)
        pq_before = st.pq.copy()
        if pf.enforce_q(st, lam):
            summary["switched_buses"].extend(st.switched[before:])
            try:
                st = pf.solve(st, lam)
            except RuntimeError:
                # After a reactive-limit switch no solution exists at this load factor: the branch ends here.
                # Refine the nose by bisection between the last traced solution and this failure.
                summary["switch_failure_at"] = lam
                lo_state, lo_lam = last_ok_state, last_ok_lam
                hi_lam = lam
                while hi_lam - lo_lam > 1e-6:
                    mid = 0.5 * (lo_lam + hi_lam)
                    trial = State(theta=lo_state.theta.copy(), vm=lo_state.vm.copy(), pq=lo_state.pq.copy(),
                                  qfix=lo_state.qfix.copy(), switched=list(lo_state.switched))
                    try:
                        lo_state = pf.solve(trial, mid)
                        lo_lam = mid
                    except RuntimeError:
                        hi_lam = mid
                summary["nose_alpha"] = float(lo_lam)
                nose_found_by_failure = True
                break
            z = np.concatenate([pf._pack(st), [lam]])
            # Carry the tangent across the switch: the new PQ bus adds one voltage unknown, whose tangent
            # component is zero (the voltage is continuous at the switch). Keeps the orientation continuous.
            if tangent_prev is not None:
                tangent_prev = _map_tangent(tangent_prev, pq_before, st.pq, pf.nonref)
        point = record(st, lam)
        point["slope"] = float(t[-1])
        points.append(point)
        last_ok_state = State(theta=st.theta.copy(), vm=st.vm.copy(), pq=st.pq.copy(),
                              qfix=st.qfix.copy(), switched=list(st.switched))
        last_ok_lam = lam
        # voltage-limit crossing
        if prev is not None and prev["min_vm"] >= voltage_limit > point["min_vm"] and summary["voltage_limit_alpha"] is None:
            a, b = prev["alpha"], point["alpha"]
            fa, fb = prev["min_vm"] - voltage_limit, point["min_vm"] - voltage_limit
            summary["voltage_limit_alpha"] = a + (b - a) * fa / (fa - fb)
        if prev is not None and prev["max_loading"] < 1.0 <= point["max_loading"] and summary["first_s2_alpha"] is None:
            a, b = prev["alpha"], point["alpha"]
            fa, fb = prev["max_loading"] - 1.0, point["max_loading"] - 1.0
            summary["first_s2_alpha"] = a + (b - a) * fa / (fa - fb)
        # turning point: slope of lambda along the arc changes sign
        if prev is not None and prev.get("slope", 1.0) > 0 and point["slope"] <= 0 and nose_pair is None:
            nose_pair = (prev["alpha"], prev["slope"], point["alpha"], point["slope"], h)
        if lam > lam_max:
            break
        if nose_pair is not None:
            break
        prev = point
    if nose_pair is not None and not nose_found_by_failure:
        la, ta, lb, tb, hh = nose_pair
        # lambda(s) ~ la + ta*x + (tb-ta)/(2h) x^2 on [0, h]; maximum where slope = 0: x* = ta*h/(ta-tb)
        x_star = ta * hh / (ta - tb) if ta != tb else 0.0
        summary["nose_alpha"] = float(la + ta * x_star + 0.5 * (tb - ta) / hh * x_star ** 2)
    summary["points"] = len(points)
    summary["switched_buses"] = sorted(set(summary["switched_buses"]))
    return points, summary
