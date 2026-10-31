"""AC state estimation (WLS, Gauss-Newton) with chi-squared bad-data detection, written out explicitly.

State vector (per unit, ppc bus order):  x = [theta_1 .. theta_{n-1}, V_1 .. V_n]   (theta of the slack fixed to 0)
Measurements (all in per unit on baseMVA):
    V_i        voltage magnitude at each bus
    P_i, Q_i   net bus injections
    Pf_k, Qf_k active/reactive power flow at the from-end of each in-service branch k
Measurement model   z = h(x) + e,   e ~ N(0, R),   R = diag(sigma_i^2)
Gauss-Newton WLS:   x_{j+1} = x_j + (H^T W H)^-1 H^T W (z - h(x_j)),   W = R^-1
Bad-data test:      J(x_hat) = r^T W r  compared with  chi2_{m-p, 1-alpha}   (p = number of states)

No pandapower state estimator is used. pandapower supplies only the admittance matrix (through its
internal ppc arrays, via makeYbus) and the power-flow solution used to generate and check measurements.
"""
from dataclasses import dataclass

import numpy as np
import pandapower as pp
from pandapower.pypower.makeYbus import makeYbus
from scipy.stats import chi2
import warnings

from .cases import locate_branch


@dataclass
class Measurement:
    kind: str    # "V", "P", "Q", "Pf", "Qf"
    index: int   # ppc bus row for V/P/Q, ppc branch row for Pf/Qf


class ACModel:
    def __init__(self, net):
        from .cases import run_powerflow
        run_powerflow(net)
        ppc = net._ppc
        self.net = net
        self.baseMVA = float(ppc["baseMVA"].real) if np.ndim(ppc["baseMVA"]) == 0 else float(ppc["baseMVA"])
        bus = np.asarray(ppc["bus"].real, dtype=float)
        branch = np.asarray(ppc["branch"].real, dtype=float)
        self.bus_ids = bus[:, 0].astype(int)
        self.ref = int(np.where(bus[:, 1] == 3)[0][0])
        self.n = len(bus)
        in_service = branch[:, 10] > 0
        self.branch_rows = np.where(in_service)[0]          # ppc rows of model branches
        branch_in = branch[in_service]
        self.f = np.searchsorted(self.bus_ids, branch_in[:, 0].astype(int))
        self.t = np.searchsorted(self.bus_ids, branch_in[:, 1].astype(int))
        self.nbr = len(branch_in)
        Ybus, Yf, Yt = makeYbus(self.baseMVA, bus, branch_in)
        self.Ybus = Ybus.toarray() if hasattr(Ybus, "toarray") else np.asarray(Ybus)
        self.Yf = Yf.toarray() if hasattr(Yf, "toarray") else np.asarray(Yf)
        self.non_ref = [i for i in range(self.n) if i != self.ref]
        # The reference angle is a known input, not a state: pandapower's external grid may be
        # at a non-zero angle (case118: 30 degrees). The estimator takes it from the network.
        self.theta_ref = float(np.deg2rad(net.ext_grid.va_degree.iloc[0]))
        self.p = len(self.non_ref) + self.n                 # number of states

        # Measurement list: V, P, Q for every bus; Pf, Qf for every branch.
        self.meas = ([Measurement("V", i) for i in range(self.n)]
                     + [Measurement("P", i) for i in range(self.n)]
                     + [Measurement("Q", i) for i in range(self.n)]
                     + [Measurement("Pf", k) for k in range(self.nbr)]
                     + [Measurement("Qf", k) for k in range(self.nbr)])
        self.m = len(self.meas)

    def _locate(self, net, ppc_row):
        return locate_branch(net, ppc_row)

    # ---------------------------------------------------------------- state <-> complex voltage
    def split(self, x):
        theta = np.full(self.n, self.theta_ref)
        theta[self.non_ref] = x[:len(self.non_ref)]
        vm = x[len(self.non_ref):]
        return theta, vm

    def state_from_powerflow(self):
        """Ground-truth state from pandapower's own solution (ppc order)."""
        va = np.zeros(self.n)
        vm = np.zeros(self.n)
        for pp_bus in self.net.bus.index:
            row = int(self.net._pd2ppc_lookups["bus"][pp_bus])
            va[row] = np.deg2rad(self.net.res_bus.va_degree.loc[pp_bus])
            vm[row] = self.net.res_bus.vm_pu.loc[pp_bus]
        return np.concatenate([va[self.non_ref], vm])

    # ---------------------------------------------------------------- measurement model h(x)
    def h(self, x):
        theta, vm = self.split(x)
        V = vm * np.exp(1j * theta)
        S_bus = V * np.conj(self.Ybus @ V)
        S_f = V[self.f] * np.conj(self.Yf @ V)
        out = np.empty(self.m)
        n, nb = self.n, self.nbr
        out[:n] = vm
        out[n:2 * n] = S_bus.real
        out[2 * n:3 * n] = S_bus.imag
        out[3 * n:3 * n + nb] = S_f.real
        out[3 * n + nb:3 * n + 2 * nb] = S_f.imag
        return out

    def jacobian(self, x):
        """Analytic Jacobian dh/dx (jacobian_analytic). The numerical version is kept as the reference."""
        return jacobian_analytic(self, x)

    def jacobian_numerical(self, x, step=1e-6):
        """Numerical Jacobian dh/dx by central differences. Reference for testing jacobian_analytic."""
        H = np.zeros((self.m, self.p))
        for j in range(self.p):
            dx = np.zeros(self.p)
            dx[j] = step
            H[:, j] = (self.h(x + dx) - self.h(x - dx)) / (2 * step)
        return H

    # ---------------------------------------------------------------- measurement vector from pandapower
    def measurement_truth(self):
        """Measurement values implied by pandapower's solution (noise free), in per unit."""
        return self.h(self.state_from_powerflow())

    def pandapower_reference(self):
        """Pandapower's own bus and branch results, mapped to the model's measurement ordering.
        Used only to validate h(x): these are not inputs to the estimator."""
        net = self.net
        ref = np.zeros(self.m)
        vm = net.res_bus.vm_pu.values
        n = self.n
        # pandapower's res_bus.p_mw / q_mvar are load-positive and EXCLUDE shunts (shunt power is in
        # res_shunt), so the physical injection is -res_bus + res_shunt.
        shunt_q = {}
        shunt_p = {}
        if len(net.res_shunt):
            for idx, row_s in net.shunt.iterrows():
                shunt_q[row_s.bus] = shunt_q.get(row_s.bus, 0.0) + net.res_shunt.q_mvar.loc[idx]
                shunt_p[row_s.bus] = shunt_p.get(row_s.bus, 0.0) + net.res_shunt.p_mw.loc[idx]
        for pp_bus in net.bus.index:
            row = int(net._pd2ppc_lookups["bus"][pp_bus])
            ref[row] = net.res_bus.vm_pu.loc[pp_bus]
            p_inj = -net.res_bus.p_mw.loc[pp_bus] + shunt_p.get(pp_bus, 0.0)
            q_inj = -net.res_bus.q_mvar.loc[pp_bus] + shunt_q.get(pp_bus, 0.0)
            ref[n + row] = p_inj / self.baseMVA
            ref[2 * n + row] = q_inj / self.baseMVA
        return ref, vm

    # ---------------------------------------------------------------- Gauss-Newton WLS
    def estimate(self, z, sigma, x0=None, tol=1e-9, max_iter=50):
        """Weighted least squares by Gauss-Newton. Returns (x_hat, residual, J, iterations)."""
        W = 1.0 / np.asarray(sigma, dtype=float) ** 2
        x = np.concatenate([np.zeros(len(self.non_ref)), np.ones(self.n)]) if x0 is None else np.array(x0, float)
        for it in range(1, max_iter + 1):
            r = z - self.h(x)
            H = self.jacobian(x)
            G = H.T @ (W[:, None] * H)
            g = H.T @ (W * r)
            try:
                dx = np.linalg.solve(G, g)
            except np.linalg.LinAlgError as exc:
                raise RuntimeError("gain matrix singular: the measurement set is not observable") from exc
            x = x + dx
            if np.max(np.abs(dx)) < tol:
                break
        else:
            raise RuntimeError(f"Gauss-Newton did not converge in {max_iter} iterations")
        r = z - self.h(x)
        H = self.jacobian(x)
        J = float(np.sum(W * r * r))
        return x, r, J, it

    def observable(self, sigma):
        W = 1.0 / np.asarray(sigma, float) ** 2
        H = self.jacobian(self.state_from_powerflow())
        G = H.T @ (W[:, None] * H)
        return np.linalg.matrix_rank(G) == self.p, float(np.linalg.cond(G))

    def chi2_threshold(self, alpha=0.01):
        """Bad-data threshold: chi-square quantile with m - p degrees of freedom at significance alpha."""
        return float(chi2.ppf(1 - alpha, self.m - self.p))


def normalized_residuals(model, z, x_hat, sigma):
    """Largest-normalised-residual inputs: r_N = |r_i| / sqrt(Omega_ii), with Omega = R - H (H^T W H)^-1 H^T.

    Returns the vector of normalised residuals. Omega_ii is the residual covariance; measurements with a
    tiny Omega_ii (critical measurements) cannot be checked, so they are given a normalised residual of 0.
    """
    W = 1.0 / np.asarray(sigma, float) ** 2
    H = model.jacobian(x_hat)
    G = H.T @ (W[:, None] * H)
    S = H @ np.linalg.solve(G, H.T)
    # Omega = R - H G^-1 H^T with R = diag(sigma^2)
    omega = np.diag(np.asarray(sigma, float) ** 2) - S
    diag = np.diag(omega)
    r = np.asarray(z, float) - model.h(x_hat)
    out = np.zeros(len(r))
    ok = diag > 1e-12
    out[ok] = np.abs(r[ok]) / np.sqrt(diag[ok])
    return out


def jacobian_analytic(model, x):
    """Closed-form dh/dx for the measurement model (same ordering as ACModel.h).

    Bus injections:  S = V conj(Y V)
        dS/dVa = j diag(V) conj(diag(I) - Y diag(V)),       I = Y V
        dS/dVm = diag(V) conj(Y diag(V/|V|)) + diag(conj(I)) diag(V/|V|)
    Branch flow at the from end:  Sf = V_f conj(Yf V),  If = Yf V
        dSf/dVa = j ( diag(conj(If)) C_f diag(V) - diag(V_f) conj(Yf diag(V)) )
        dSf/dVm = diag(V_f) conj(Yf diag(V/|V|)) + diag(conj(If)) C_f diag(V/|V|)
    with C_f the from-bus selector. Measurements: V (dVm), P = Re S, Q = Im S, Pf = Re Sf, Qf = Im Sf.
    Columns are then reordered to the state [theta (non-reference), V (all)].
    """
    theta, vm = model.split(x)
    V = vm * np.exp(1j * theta)
    Vn = V / np.abs(V)
    n, nb = model.n, model.nbr
    Y, Yf = model.Ybus, model.Yf
    I = Y @ V
    If = Yf @ V
    f = model.f
    # Bus injections
    YV = Y * V[None, :]            # Y diag(V)
    YVn = Y * Vn[None, :]          # Y diag(V/|V|)
    dS_dva = 1j * V[:, None] * np.conj(np.diag(I) - YV)
    dS_dvm = V[:, None] * np.conj(YVn) + np.diag(np.conj(I) * Vn)
    # Branch flows (from end)
    Vf = V[f]
    C_diag_V = np.zeros((nb, n), dtype=complex)
    C_diag_V[np.arange(nb), f] = np.conj(If) * V[f]
    C_diag_Vn = np.zeros((nb, n), dtype=complex)
    C_diag_Vn[np.arange(nb), f] = np.conj(If) * Vn[f]
    YfV = Yf * V[None, :]
    YfVn = Yf * Vn[None, :]
    dSf_dva = 1j * (C_diag_V - Vf[:, None] * np.conj(YfV))
    dSf_dvm = Vf[:, None] * np.conj(YfVn) + C_diag_Vn

    m = model.m
    dh_dva = np.zeros((m, n))
    dh_dvm = np.zeros((m, n))
    dh_dvm[np.arange(n), np.arange(n)] = 1.0          # |V| measurements
    dh_dva[n:2 * n] = dS_dva.real                      # P
    dh_dva[2 * n:3 * n] = dS_dva.imag                  # Q
    dh_dvm[n:2 * n] = dS_dvm.real
    dh_dvm[2 * n:3 * n] = dS_dvm.imag
    dh_dva[3 * n:3 * n + nb] = dSf_dva.real            # Pf
    dh_dva[3 * n + nb:] = dSf_dva.imag                 # Qf
    dh_dvm[3 * n:3 * n + nb] = dSf_dvm.real
    dh_dvm[3 * n + nb:] = dSf_dvm.imag
    # state ordering: theta for non-reference buses, then all magnitudes
    return np.hstack([dh_dva[:, model.non_ref], dh_dvm])
