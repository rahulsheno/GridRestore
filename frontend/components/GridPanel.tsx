"use client";
import { useState } from "react";
import { api, ApiClientError } from "../lib/api-client";
import type { EdgeStatus, GridView, Scenario } from "../lib/api-types";
import { Alert, Card, Empty, Field } from "./ui";
import { IconNetwork } from "./icons";

const EDGE_COLOUR: Record<EdgeStatus, string> = {
  restored: "#22a06b", unscheduled: "#e0a100", blocked: "#e5484d", clear: "#8a94a6",
};
const NODE_COLOUR: Record<string, string> = {
  substation: "#1f4e79", bus: "#2e86ab", hospital: "#c0392b", water_facility: "#16a085",
  residential: "#7f8c8d", industrial: "#8e44ad",
};
const WIDTH = 640, HEIGHT = 420, RADIUS = 170;

// Circular layout keeps the picture stable across reloads; fine for a demo-sized grid.
function layout(count: number) {
  return Array.from({ length: count }, (_, i) => {
    const angle = (2 * Math.PI * i) / Math.max(count, 1) - Math.PI / 2;
    return { x: WIDTH / 2 + RADIUS * Math.cos(angle), y: HEIGHT / 2 + RADIUS * Math.sin(angle) };
  });
}

export default function GridPanel({ token, scenarios, scenarioId, setScenarioId }: {
  token: string; scenarios: Scenario[]; scenarioId: number; setScenarioId: (id: number) => void;
}) {
  const [view, setView] = useState<GridView | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  async function load() {
    setError(""); setLoading(true);
    try { setView(await api.grid(token, scenarioId)); }
    catch (e) { setError(e instanceof ApiClientError ? e.message : "Could not load the grid."); }
    finally { setLoading(false); }
  }

  const positions = new Map<string, { x: number; y: number }>();
  view?.nodes.forEach((n, i) => positions.set(n.node_id, layout(view.nodes.length)[i]));
  const blocked = view?.blocked_task_ids ?? [];
  const counts = view ? Object.fromEntries(
    (Object.keys(EDGE_COLOUR) as EdgeStatus[]).map(s => [s, view.edges.filter(e => e.status === s).length]),
  ) as Record<EdgeStatus, number> : null;

  return (
    <div className="stack">
      <Card title="Grid map" sub="Nodes are coloured by type; edges show restoration status from the latest saved run. Dashed red edges lead to tasks blocked by an unscheduled prerequisite.">
        <div className="row gap-12" style={{ alignItems: "flex-end" }}>
          <div style={{ flex: "1 1 260px", minWidth: 0 }}>
            <Field label="Scenario">
              <select className="select" value={scenarioId} onChange={(e) => setScenarioId(Number(e.target.value))}>
                {scenarios.map(s => <option key={s.scenario_id} value={s.scenario_id}>{s.scenario_id} — {s.scenario_name}</option>)}
              </select>
            </Field>
          </div>
          <button className="btn btn-primary" onClick={load} disabled={loading}>
            {loading ? <><span className="spinner" /> Drawing…</> : <><IconNetwork size={15} /> Draw grid</>}
          </button>
        </div>
        {error && <div className="mt-16"><Alert kind="danger">{error}</Alert></div>}
      </Card>

      {!view ? (
        <Empty icon={<IconNetwork size={18} />} title="Nothing drawn yet">
          Choose a scenario and draw the grid to inspect the topology and restoration status.
        </Empty>
      ) : (
        <Card title={scenarios.find(s => s.scenario_id === view.scenario_id)?.scenario_name ?? `Scenario ${view.scenario_id}`}
          sub={view.latest_run_id ? `Scenario ${view.scenario_id} · status from run #${view.latest_run_id}` : "No saved run yet: every task is unscheduled"}
          actions={
            <div className="row gap-6">
              {(["restored", "unscheduled", "blocked"] as EdgeStatus[]).map(s => (
                <span className={`badge ${s === "restored" ? "badge-success" : s === "blocked" ? "badge-danger" : "badge-warn"}`} key={s}>
                  {counts?.[s] ?? 0} {s}
                </span>
              ))}
            </div>
          }>
          <svg viewBox={`0 0 ${WIDTH} ${HEIGHT}`} role="img" aria-label="Grid network map" className="grid-canvas">
            {view.edges.map(e => {
              const a = positions.get(e.from_node_id), b = positions.get(e.to_node_id);
              if (!a || !b) return null;
              return (
                <line key={e.edge_id} x1={a.x} y1={a.y} x2={b.x} y2={b.y}
                  stroke={EDGE_COLOUR[e.status]} strokeWidth={e.status === "clear" ? 1.5 : 3}
                  strokeLinecap="round" strokeDasharray={e.status === "blocked" ? "8 6" : undefined}>
                  <title>{`${e.edge_id} (${e.component_type}): ${e.status}`}</title>
                </line>
              );
            })}
            {view.nodes.map(n => {
              const p = positions.get(n.node_id)!;
              const r = 6 + Number(n.criticality) * 0.6;
              return (
                <g key={n.node_id}>
                  <circle cx={p.x} cy={p.y} r={r} fill={NODE_COLOUR[n.node_type] ?? "#555"} stroke="rgba(255,255,255,.55)" strokeWidth={1.5}>
                    <title>{`${n.node_name} (${n.node_type}, criticality ${n.criticality})`}</title>
                  </circle>
                  {view.nodes.length <= 30 && (
                    <text x={p.x + r + 4} y={p.y + 4} fontSize={11} fill="currentColor" style={{ color: "var(--text-2)" }}>
                      {n.node_name}
                    </text>
                  )}
                </g>
              );
            })}
          </svg>

          <div className="legend">
            {(Object.keys(EDGE_COLOUR) as EdgeStatus[]).map(s => (
              <span className="legend-item" key={s}>
                <span className="legend-swatch" style={{ width: 18, height: 4, background: EDGE_COLOUR[s] }} /> {s}
              </span>
            ))}
            <span style={{ width: 1, height: 12, background: "var(--border)" }} />
            {Object.keys(NODE_COLOUR).map(t => (
              <span className="legend-item" key={t}>
                <span className="legend-swatch" style={{ width: 9, height: 9, borderRadius: 5, background: NODE_COLOUR[t] }} /> {t}
              </span>
            ))}
          </div>

          {blocked.length > 0 && (
            <div className="mt-16">
              <Alert kind="warn"><strong>Blocked tasks:</strong> {blocked.join(", ")}</Alert>
            </div>
          )}
        </Card>
      )}
    </div>
  );
}
