"use client";
import { useEffect, useState } from "react";
import { physicsApi, ApiClientError } from "../lib/api-client";
import type {
  PhysicsCurvePoint, PhysicsMdpDetail, PhysicsOverview, PhysicsRun,
} from "../lib/api-types";
import { Alert, Card, Field, Spinner } from "./ui";

const CASES = ["case9", "case14", "case30", "case57", "case118"];
const STATUS_COLOUR: Record<string, string> = {
  S0: "#22a06b", S1: "#e0a100", S2: "#e5780a", S3: "#e5484d", SOLVER_DIVERGENCE: "#98a2b3",
};
const fmt = (v: number | null | undefined, digits = 4) => (v === null || v === undefined ? "—" : Number(v).toPrecision(digits));

function ContinuationChart({ points, voltageLimitAlpha, noseAlpha }: {
  points: PhysicsCurvePoint[]; voltageLimitAlpha: number | null; noseAlpha: number | null;
}) {
  const W = 660, H = 280, PAD = 46;
  const alphas = points.map(p => p.alpha);
  if (!alphas.length) return <p className="muted small">No continuation points stored for this case.</p>;
  const x0 = Math.min(...alphas), x1 = Math.max(...alphas);
  const vms = points.map(p => p.min_vm).filter((v): v is number => v !== null);
  const yLo = Math.min(0.8, ...vms), yHi = Math.max(1.05, ...vms);
  const X = (a: number) => PAD + ((a - x0) / (x1 - x0 || 1)) * (W - 2 * PAD);
  const Y = (v: number) => H - PAD - ((v - yLo) / (yHi - yLo || 1)) * (H - 2 * PAD);
  const limitY = Y(0.85);
  const gridValues = [yLo, (yLo + yHi) / 2, yHi];
  return (
    <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label="Minimum voltage against load factor" className="chart">
      {gridValues.map(v => (
        <g key={v}>
          <line x1={PAD} x2={W - PAD} y1={Y(v)} y2={Y(v)} stroke="#98a2b3" strokeOpacity={0.18} strokeWidth={1} />
          <text x={8} y={Y(v) + 4} fontSize={10.5} fill="#98a2b3">{v.toFixed(2)}</text>
        </g>
      ))}
      <line x1={PAD} x2={W - PAD} y1={limitY} y2={limitY} stroke="#e5484d" strokeDasharray="6 4" strokeWidth={1.5} />
      <text x={W - PAD} y={limitY - 6} fontSize={10.5} textAnchor="end" fill="#e5484d">0.85 pu voltage limit</text>
      {voltageLimitAlpha !== null && (
        <line x1={X(voltageLimitAlpha)} x2={X(voltageLimitAlpha)} y1={PAD} y2={H - PAD}
          stroke="#e0a100" strokeDasharray="3 3" strokeWidth={1.2}>
          <title>{`voltage limit at alpha ${fmt(voltageLimitAlpha, 4)}`}</title>
        </line>
      )}
      {noseAlpha !== null && (
        <line x1={X(noseAlpha)} x2={X(noseAlpha)} y1={PAD} y2={H - PAD}
          stroke="#667085" strokeDasharray="2 3" strokeWidth={1.2}>
          <title>{`nose at alpha ${fmt(noseAlpha, 4)}`}</title>
        </line>
      )}
      {points.filter(p => p.min_vm !== null).map((p, i) => (
        <circle key={i} cx={X(p.alpha)} cy={Y(p.min_vm as number)} r={2.6}
          fill={STATUS_COLOUR[p.status] ?? "#667085"} stroke="rgba(255,255,255,.6)" strokeWidth={0.6}>
          <title>{`alpha ${p.alpha}: ${p.status}, min voltage ${fmt(p.min_vm, 4)}, max loading ${fmt(p.max_loading, 3)}`}</title>
        </circle>
      ))}
      <text x={PAD} y={H - 14} fontSize={10.5} fill="#98a2b3">load factor α · {x0} → {x1}</text>
    </svg>
  );
}

export default function PhysicsPanel({ token }: { token: string }) {
  const [runs, setRuns] = useState<PhysicsRun[]>([]);
  const [runId, setRunId] = useState<number | null>(null);
  const [overview, setOverview] = useState<PhysicsOverview | null>(null);
  const [caseName, setCaseName] = useState("case30");
  const [curve, setCurve] = useState<PhysicsCurvePoint[]>([]);
  const [mdp, setMdp] = useState<PhysicsMdpDetail | null>(null);
  const [figure, setFigure] = useState("");
  const [weightSet, setWeightSet] = useState<"headline" | "plan">("headline");
  const [error, setError] = useState("");
  const [loadingRun, setLoadingRun] = useState(false);
  const [curveError, setCurveError] = useState("");
  const [mdpError, setMdpError] = useState("");

  useEffect(() => {
    physicsApi.runs(token).then(list => {
      setRuns(list);
      if (list.length) setRunId(list[0].run_id);
    }).catch(e => setError(e instanceof ApiClientError ? e.message : "Could not load physics runs."));
  }, [token]);

  useEffect(() => {
    if (runId === null) return;
    setError("");
    setLoadingRun(true);
    physicsApi.overview(token, runId).then(setOverview)
      .catch(e => setError(e instanceof ApiClientError ? e.message : "Could not load the run."))
      .finally(() => setLoadingRun(false));
    physicsApi.figure(token, runId, "sensitivity_heatmap")
      .then(f => setFigure(`data:${f.content_type};base64,${f.data_base64}`)).catch(() => setFigure(""));
  }, [token, runId]);

  useEffect(() => {
    if (runId === null) return;
    setCurveError(""); setMdpError("");
    physicsApi.continuation(token, runId, caseName).then(setCurve)
      .catch(e => { setCurve([]); setCurveError(e instanceof ApiClientError ? e.message : "Could not load the curve."); });
    physicsApi.mdp(token, runId, caseName).then(setMdp)
      .catch(e => { setMdp(null); setMdpError(e instanceof ApiClientError ? e.message : "Could not load the policies."); });
  }, [token, runId, caseName]);

  if (!runs.length) {
    return (
      <Card title="Physics study" sub="Read-only results on IEEE benchmark cases">
        <Alert kind="info">
          No physics study has been stored yet. Run <code>python -m backend.grid.physics_study</code> to create one,
          then reload this page.
        </Alert>
      </Card>
    );
  }

  const summary = overview?.continuation_summary.find(s => s.case_name === caseName);
  const policies = (mdp?.policy ?? []).filter(p => p.weight_set === weightSet);

  return (
    <div className="stack">
      <Card title="Study" sub="Power-flow validation, load continuation, stealthy false-data injection and the operating-state MDP.">
        <div className="row gap-12" style={{ alignItems: "flex-end" }}>
          <div style={{ flex: "1 1 320px", minWidth: 0 }}>
            <Field label="Stored run">
              <select className="select" value={runId ?? ""} onChange={(e) => setRunId(Number(e.target.value))}>
                {runs.map(r => <option key={r.run_id} value={r.run_id}>#{r.run_id} · {r.mode} · {r.created_at.slice(0, 16).replace("T", " ")}</option>)}
              </select>
            </Field>
          </div>
          <div style={{ flex: "0 1 200px" }}>
            <Field label="Benchmark case">
              <select className="select" value={caseName} onChange={(e) => setCaseName(e.target.value)}>
                {CASES.map(c => <option key={c} value={c}>{c}</option>)}
              </select>
            </Field>
          </div>
          {loadingRun && <Spinner label="Loading run…" />}
        </div>

        {overview && (
          <div className="row gap-6 mt-16">
            <span className="chip">w₁ {overview.run.headline_weights.w1}</span>
            <span className="chip">w₂ {overview.run.headline_weights.w2}</span>
            <span className="chip">w₃ {overview.run.headline_weights.w3}</span>
            <span className="badge badge-success">reactive limits enforced</span>
            <span className="small muted">Headline weights (mitigation chosen); plan w₃ {overview.run.plan_weights.w3}.</span>
          </div>
        )}
        {error && <div className="mt-16"><Alert kind="danger">{error}</Alert></div>}
      </Card>

      {overview && (
        <Card title="Power-flow validation" sub="Our DC and AC models compared with pandapower's own solvers. Errors are absolute." flush>
          <div className="table-wrap">
            <table className="table table-compact">
              <thead><tr><th>Check</th><th>Case</th><th>Metric</th><th className="num">Error</th></tr></thead>
              <tbody>
                {overview.validation.filter(v => v.case_name === caseName).map((v, i) => (
                  <tr key={i}>
                    <td className="strong">{v.check_name}</td>
                    <td className="mono">{v.case_name}</td>
                    <td>{v.metric}</td>
                    <td className="num mono">{fmt(v.value, 3)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Card>
      )}

      <Card title={`Load continuation · ${caseName}`} sub="Minimum voltage as load scales; the sweep stops at solver divergence.">
        {curveError && <div style={{ marginBottom: 16 }}><Alert kind="danger">{curveError}</Alert></div>}
        <ContinuationChart points={curve} voltageLimitAlpha={summary?.voltage_limit_alpha ?? null}
          noseAlpha={summary?.nose_alpha ?? null} />
        <div className="legend">
          {["S0", "S1", "S2", "S3"].map(s => (
            <span className="legend-item" key={s}>
              <span className="legend-swatch" style={{ width: 8, height: 8, borderRadius: 4, background: STATUS_COLOUR[s] }} />
              {s} {s === "S0" ? "normal" : s === "S1" ? "stressed" : s === "S2" ? "thermal" : "voltage"}
            </span>
          ))}
          <span className="legend-item"><span className="legend-swatch" style={{ width: 16, height: 2, background: "#e0a100" }} /> voltage-limit α</span>
          <span className="legend-item"><span className="legend-swatch" style={{ width: 16, height: 2, background: "#667085" }} /> nose α</span>
        </div>
        <p className="small muted mt-16" style={{ lineHeight: 1.65 }}>
          Voltage limit (0.85 pu) at load factor {fmt(summary?.voltage_limit_alpha ?? null, 4)}; nose
          (solver divergence) at {fmt(summary?.nose_alpha ?? null, 4)}; first thermal overload
          at {fmt(summary?.first_s2_alpha ?? null, 4)}. Without generator reactive limits the same case
          would reach {fmt(summary?.voltage_limit_alpha_free_q ?? null, 4)} (voltage)
          and {fmt(summary?.nose_alpha_free_q ?? null, 4)} (nose), which overstates loadability.
          This is a load-scaling sweep, not a predictor–corrector method.
        </p>
      </Card>

      {overview && (
        <Card title="Stealthy false data injection" sub="Attacks confined to compromised RTUs, bounded to 15% of each measurement; χ² test at α = 0.01." flush>
          <div className="table-wrap">
            <table className="table table-compact">
              <thead><tr><th>Case</th><th>Kind</th><th>Metrics</th></tr></thead>
              <tbody>
                {overview.fdia.map((f, i) => (
                  <tr key={i}>
                    <td className="mono">{f.case_name}</td>
                    <td>{f.kind === "dc" ? <span className="badge badge-accent">DC exact</span> : <span className="badge badge-neutral">AC Monte Carlo</span>}</td>
                    <td>
                      <div className="row gap-6">
                        {Object.entries(f.metrics).map(([k, v]) => (
                          <span className="chip" key={k}>{k}: <span className="mono">{typeof v === "number" ? fmt(v, 3) : String(v)}</span></span>
                        ))}
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Card>
      )}

      <Card title={`Operating-state policies · ${caseName}`}
        sub="Optimal action per calibrated state under each weight set."
        actions={
          <div className="seg" role="group" aria-label="Weight set">
            <button className={weightSet === "headline" ? "active" : ""} onClick={() => setWeightSet("headline")}>Headline</button>
            <button className={weightSet === "plan" ? "active" : ""} onClick={() => setWeightSet("plan")}>Plan</button>
          </div>
        }>
        {mdpError && <div style={{ marginBottom: 16 }}><Alert kind="danger">{mdpError}</Alert></div>}
        <div className="table-wrap" style={{ border: "1px solid var(--border)", borderRadius: 10 }}>
          <table className="table table-compact">
            <thead>
              <tr><th>Stress vector</th><th>State</th><th className="num">Loading</th>
                <th className="num">Min voltage</th><th className="num">Value</th><th>Optimal action</th></tr>
            </thead>
            <tbody>
              {policies.map((p, i) => (
                <tr key={i}>
                  <td>{p.stress_vector}</td>
                  <td><span className={`badge ${p.state === "S3" ? "badge-danger" : p.state === "S2" ? "badge-warn" : "badge-neutral"}`}>{p.state}</span></td>
                  <td className="num">{fmt(p.loading_target, 3)}</td>
                  <td className="num">{fmt(p.min_vm, 3)}</td>
                  <td className="num mono">{fmt(p.v_star, 3)}</td>
                  <td>
                    {p.optimal_action === "DO_NOTHING"
                      ? <span className="badge badge-neutral">DO_NOTHING</span>
                      : <span className="badge badge-accent">{p.optimal_action}</span>}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <p className="small muted mt-12">
          Collapse (S3) probability from S2, by action, is in the transition table returned by the API. With the
          voltage-based transition it is small at normal voltages and rises as minimum voltage falls.
        </p>
      </Card>

      <Card title="Sensitivity" sub="Steepness and normal limit, plus weight sweeps.">
        {!figure && runId !== null && <Spinner label="Loading figure…" />}
        {figure
          ? <img src={figure} alt="Sensitivity heatmap: steepness and normal limit, and weight sweeps"
              style={{ width: "100%", maxWidth: 960, borderRadius: 10, border: "1px solid var(--border)" }} />
          : <p className="muted small">No sensitivity figure stored for this run.</p>}
      </Card>
    </div>
  );
}
