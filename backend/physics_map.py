"""Bridge between the scheduling half and the physics half of GridRestore.

Every synthetic grid edge is mapped deterministically to an element of an IEEE
benchmark case (the hash is seeded by edge_id, so the mapping is reproducible),
and mapped edges inherit a *voltage risk* score derived from that case's
continuation margins: a low loadability margin (e.g. case14, 1.60) means the
element sits in a voltage-weak area, so repairs on it boost the schedule
priority. When the physics study has stored per-case results in
physics_continuation_summary, the live values are used instead of the defaults.

The scheduler consumes these as multiplicative bonuses on service_weight, so
the effect is visible, bounded and explainable in the UI.
"""
import hashlib

from .db import connect

# Continuation nose (reactive limits enforced), from docs/PHYSICS.md — the
# default reference values used until a stored physics run overrides them.
_DEFAULT_NOSE = {"case9": 2.47, "case14": 3.36, "case30": 2.85, "case57": 2.85, "case118": 2.14}
_CASES = tuple(_DEFAULT_NOSE)
_PHI = 0.25  # max bonus fraction when risk is highest


def voltage_risk_for(case_name: str, nose: float) -> float:
    """Risk in (0, 1]: inverse of the loadability nose, squashed and scaled."""
    return round(min(1.0, (1.0 / nose) ** 0.5), 4)


def ensure_map():
    """Populate element_physics_map deterministically; count edges mapped."""
    with connect() as conn:
        edges = conn.execute("SELECT edge_id FROM grid_edges ORDER BY edge_id").fetchall()
        for row in edges:
            edge_id = row["edge_id"]
            case = _CASES[int(hashlib.sha256(f"case:{edge_id}".encode()).hexdigest(), 16) % len(_CASES)]
            idx = int(hashlib.sha256(f"elem:{edge_id}".encode()).hexdigest(), 16) % 30
            nose = _nose_from_storage(conn, case) or _DEFAULT_NOSE[case]
            risk = voltage_risk_for(case, nose)
            conn.execute(
                "INSERT INTO element_physics_map (edge_id, case_name, element_type, element_index, voltage_risk) "
                "VALUES (%s,%s,%s,%s,%s) ON CONFLICT (edge_id) DO UPDATE "
                "SET case_name=EXCLUDED.case_name, element_index=EXCLUDED.element_index, "
                "voltage_risk=EXCLUDED.voltage_risk, updated_at=now()",
                (edge_id, case, "line", idx, risk))
        return len(edges)


def _nose_from_storage(conn, case: str):
    rows = conn.execute(
        "SELECT nose_alpha_free_q, nose_alpha_free_q AS nose FROM physics_continuation_summary "
        "WHERE case_name=%s ORDER BY run_id DESC LIMIT 1", (case,)).fetchone()
    if not rows or not rows["nose"]:
        return None
    try:
        return float(rows["nose"])
    except (TypeError, ValueError):
        return None


def task_weights(scenario_id: int, refresh: bool = False, phi: float = _PHI) -> dict:
    """Per-task physics bonus: {task_id: bonus_fraction} to multiply service_weight."""
    if refresh:
        ensure_map()
    with connect() as conn:
        rows = conn.execute(
            "SELECT t.task_id, m.voltage_risk FROM repair_tasks t "
            "JOIN element_physics_map m ON m.edge_id = t.edge_id "
            "WHERE t.scenario_id=%s", (scenario_id,)).fetchall()
    weights = {}
    for row in rows:
        weights[row["task_id"]] = round(1.0 + phi * (float(row["voltage_risk"]) or 0.0), 4)
    return weights


def map_rows(scenario_id: int):
    with connect() as conn:
        return [dict(r) for r in conn.execute(
            "SELECT t.task_id, t.component_name, m.edge_id, m.case_name, m.element_type, "
            "m.element_index, m.voltage_risk "
            "FROM repair_tasks t LEFT JOIN element_physics_map m ON m.edge_id = t.edge_id "
            "WHERE t.scenario_id=%s ORDER BY t.task_id", (scenario_id,)).fetchall()]
