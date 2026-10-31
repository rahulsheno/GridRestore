"""DC power-flow model with PTDF and electrical centrality.

Formulation (bus injections P_r at non-slack buses, branch flows f = D * A * theta):
    A      branch-bus incidence, m x n: A[k, from] = +1, A[k, to] = -1
    A_r    A with the slack column removed, m x (n-1)
    D      diagonal of branch susceptances b_k = 1 / x_k (taps applied)
    B_r    A_r^T D A_r, the reduced bus susceptance matrix, (n-1) x (n-1), non-singular when connected
    theta_r = B_r^-1 P_r,  f = D A_r theta_r

    PTDF = D A_r B_r^-1   (m x (n-1)): flow change on branch k per MW injected at bus j, withdrawn at slack.

Note: the plan wrote PTDF = D A_r^T B_r^-1 with B_r = A_r D A_r^T. Those shapes do not conform
(A_r^T D A_r^T is undefined for m x (n-1) A_r); the form above is the standard one and is checked
against pandapower's own DC solver in tests/test_grid_physics.py.
"""
import numpy as np
import networkx as nx
import pandapower as pp

from .cases import locate_branch


class DCModel:
    """Built from the pandapower network after a power flow, using pandapower's internal ppc arrays
    so that taps and shifts match what pp.runpp uses."""

    def __init__(self, net):
        import warnings
        # The DC model needs only the branch parameters (taps, reactances) and the bus ordering from the ppc
        # arrays. Those do not depend on generator reactive limits, and a contingency that is solvable
        # without limits can fail with them, so this build always runs without Q limits.
        import warnings as _w
        with _w.catch_warnings():
            _w.simplefilter("ignore")
            pp.runpp(net, enforce_q_lims=False)
        ppc = net._ppc
        bus, branch = ppc["bus"], ppc["branch"]
        in_service = branch[:, 10].real > 0
        self.ppc_buses = bus[:, 0].real.astype(int)
        self.slack_row = int(np.where(bus[:, 1].real == 3)[0][0])
        self.from_row = np.searchsorted(self.ppc_buses, branch[in_service, 0].real.astype(int))
        self.to_row = np.searchsorted(self.ppc_buses, branch[in_service, 1].real.astype(int))
        tap = np.where(branch[in_service, 8].real == 0, 1.0, branch[in_service, 8].real)
        x = branch[in_service, 3].real
        self.b = 1.0 / (x * tap)                                # diagonal of D (MATPOWER makeBdc convention)
        self.branch_ids = np.where(in_service)[0]               # rows of ppc branch in the model
        self.n = len(self.ppc_buses)
        self.m = len(self.b)

        A = np.zeros((self.m, self.n))
        A[np.arange(self.m), self.from_row] = 1.0
        A[np.arange(self.m), self.to_row] = -1.0
        self.A = A
        keep = [i for i in range(self.n) if i != self.slack_row]
        self.keep = keep
        self.A_r = A[:, keep]
        self.D = np.diag(self.b)
        self.B_r = self.A_r.T @ self.D @ self.A_r
        if np.linalg.matrix_rank(self.B_r) < self.B_r.shape[0]:
            raise ValueError("network is islanded: reduced susceptance matrix is singular")
        self.PTDF = self.D @ self.A_r @ np.linalg.inv(self.B_r)  # m x (n-1)

    def flows_from_injections(self, p_inj_pu):
        """p_inj_pu: injections at every ppc bus (slack entry ignored), per unit on baseMVA.
        Returns branch flows (pu) in model branch order."""
        p_r = np.delete(np.asarray(p_inj_pu, dtype=float), self.slack_row)
        return self.PTDF @ p_r

    def branch_labels(self, net):
        """(element type, pandapower index) for each model branch, in model order."""
        return [self._locate(net, k) for k in self.branch_ids]

    def centrality(self, net):
        """Electrical criticality metrics (heuristic indices, documented in docs/PHYSICS.md).

        line_criticality_k = sum_j |PTDF_kj| * rating_k_mva / sum_k rating_k_mva  (sensitivity weighted by rating)
        node_criticality_j = sum_k |PTDF_kj| * rating_k_mva / sum_k rating_k_mva
        Both are normalised to [0, 1] by their maximum, so the highest-value element is 1.0.
        """
        rating = self._ratings_mva(net)
        weight = rating / rating.sum()
        absP = np.abs(self.PTDF)
        line_crit = absP.sum(axis=1)
        node_crit = (absP * weight[:, None]).sum(axis=0)
        node_crit_full = np.zeros(self.n)
        node_crit_full[self.keep] = node_crit
        return {
            "line_criticality": line_crit / line_crit.max(),
            "node_criticality": node_crit_full / node_crit_full.max(),
        }

    def _locate(self, net, ppc_row):
        return locate_branch(net, ppc_row)

    def _ratings_mva(self, net):
        rated = []
        for k in self.branch_ids:
            elm, local = self._locate(net, k)
            if elm == "line":
                vn = float(net.bus.vn_kv.loc[net.line.from_bus.iloc[local]])
                rated.append(float(net.line.max_i_ka.iloc[local]) * np.sqrt(3) * vn)
            else:
                rated.append(float(net.trafo.sn_mva.iloc[local]))
        return np.array(rated, dtype=float)

    def betweenness_reference(self, net):
        """Graph betweenness on the same connectivity, for comparison with electrical criticality."""
        g = nx.Graph()
        g.add_nodes_from(range(self.n))
        g.add_edges_from(zip(self.from_row.tolist(), self.to_row.tolist()))
        return nx.betweenness_centrality(g, normalized=True)
