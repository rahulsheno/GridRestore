"""Multi-tier cyber communication graph, decoupled from the electrical model.

Tiers (directed graph; an edge means "an attacker with access to the source can reach the target"):

    IT enterprise zone  ->  firewall  ->  SCADA DMZ  ->  firewall  ->  SCADA control  ->  field RTUs

The graph contains no electrical quantity. Its only output is a set of compromised RTUs. The mapping
from RTU to physical sensors is a separate table (telemetry.py), so the cyber model cannot change
power-flow equations, and the power model cannot change which paths exist.

Edge attribute `exploitable`: True means the attacker can traverse that link with the credentials
or exploits they hold. Stylised, not a vulnerability assessment.
"""
import json
import math
import os
from dataclasses import dataclass, field

import networkx as nx
import numpy as np

ENTRY_POINT = "IT-Email"   # default; overwritten from the topology file when a model is built


@dataclass
class CyberModel:
    graph: nx.DiGraph
    rtus: list
    rtu_zone: dict = field(default_factory=dict)

    def reachable_from_entry(self):
        """Nodes the attacker reaches using only exploitable links."""
        exploitable = nx.DiGraph()
        exploitable.add_nodes_from(self.graph.nodes)
        exploitable.add_edges_from((u, v) for u, v, d in self.graph.edges(data=True) if d["exploitable"])
        return nx.descendants(exploitable, ENTRY_POINT) | {ENTRY_POINT}

    def compromised_rtus(self, extra_breaches=()):
        """RTUs compromised by the attack; `extra_breaches` adds further starting points (e.g. a stolen VPN)."""
        reached = set()
        starts = [ENTRY_POINT, *extra_breaches]
        for start in starts:
            reached |= nx.descendants(self._exploitable(), start) | {start}
        return sorted(r for r in self.rtus if r in reached)

    def _exploitable(self):
        g = nx.DiGraph()
        g.add_nodes_from(self.graph.nodes)
        g.add_edges_from((u, v) for u, v, d in self.graph.edges(data=True) if d["exploitable"])
        return g

    def attack_path(self, rtu):
        """Shortest exploitable path from the entry point to an RTU (for reporting), or None."""
        try:
            return nx.shortest_path(self._exploitable(), ENTRY_POINT, rtu)
        except nx.NetworkXNoPath:
            return None


DEFAULT_TOPOLOGY = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "cyber_topology.json")


def load_topology(path=DEFAULT_TOPOLOGY):
    """Read the static part of the cyber topology (tiers, links, entry point) from a JSON file."""
    with open(path, encoding="utf-8") as fh:
        spec = json.load(fh)
    for key in ("entry_point", "static_edges", "rtu_attach_node", "rtu_prefix", "exposed_fraction", "rtu_links"):
        if key not in spec:
            raise ValueError(f"cyber topology file {path} is missing '{key}'")
    return spec


def build_cyber_model(n_rtus, exposed_rtus=None, topology_file=None):
    """Build the cyber graph for `n_rtus` field RTUs from the topology file.

    The first `exposed_rtus` RTUs (default: exposed_fraction of them, rounded up) sit on the polling network
    that the attacker can reach from the front end; the rest are behind the secure radio link.
    """
    if n_rtus < 1:
        raise ValueError("n_rtus must be at least 1")
    spec = load_topology(topology_file or DEFAULT_TOPOLOGY)
    global ENTRY_POINT
    ENTRY_POINT = spec["entry_point"]
    if exposed_rtus is None:
        exposed_rtus = math.ceil(n_rtus * spec["exposed_fraction"])
    g = nx.DiGraph()
    for edge in spec["static_edges"]:
        g.add_edge(edge["source"], edge["target"], exploitable=bool(edge["exploitable"]), label=edge["label"])
    rtus = [f"{spec['rtu_prefix']}{i:02d}" for i in range(1, n_rtus + 1)]
    zone = {}
    for i, rtu in enumerate(rtus):
        exposed = i < exposed_rtus
        link = spec["rtu_links"]["polling" if exposed else "radio"]
        g.add_edge(spec["rtu_attach_node"], rtu, exploitable=bool(link["exploitable"]) and exposed, label=link["label"])
        zone[rtu] = "polling" if exposed else "radio"
    return CyberModel(graph=g, rtus=rtus, rtu_zone=zone)


def assign_buses_to_rtus(ppc_adjacency, n_buses, n_rtus):
    """Partition buses into n_rtus contiguous regions by graph distance from evenly spaced seed buses.

    `ppc_adjacency` is an undirected networkx Graph over bus rows. Returns a length-n_buses list of RTU names.
    """
    if n_rtus > n_buses:
        raise ValueError("more RTUs than buses")
    seeds = [int(round(i * (n_buses - 1) / max(n_rtus - 1, 1))) for i in range(n_rtus)]
    seeds = list(dict.fromkeys(seeds))
    labels = {}
    for k, seed in enumerate(seeds):
        dist = nx.single_source_shortest_path_length(ppc_adjacency, seed)
        for bus, d in dist.items():
            if bus not in labels or d < labels[bus][1] or (d == labels[bus][1] and k < labels[bus][0]):
                labels[bus] = (k, d)
    out = []
    for bus in range(n_buses):
        k = labels.get(bus, (0, 0))[0]
        out.append(f"RTU-{k + 1:02d}")
    return out
