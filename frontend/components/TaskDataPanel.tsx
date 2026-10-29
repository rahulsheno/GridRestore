"use client";
import { useState } from "react";
import { api, ApiClientError } from "../lib/api-client";
import type { ImportResult, Role, Scenario } from "../lib/api-types";
import { Alert, Card, Field } from "./ui";
import { IconCheck, IconDownload, IconUpload } from "./icons";

export default function TaskDataPanel({ token, role, scenarios, scenarioId, setScenarioId }: {
  token: string; role: Role; scenarios: Scenario[]; scenarioId: number; setScenarioId: (id: number) => void;
}) {
  const [csv, setCsv] = useState("");
  const [checked, setChecked] = useState<ImportResult | null>(null);
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");
  const admin = role === "admin";

  async function exportCsv() {
    setError("");
    try {
      const text = await api.exportTasksCsv(token, scenarioId);
      const url = URL.createObjectURL(new Blob([text], { type: "text/csv" }));
      const a = document.createElement("a");
      a.href = url; a.download = `repair-tasks-scenario-${scenarioId}.csv`; a.click();
      URL.revokeObjectURL(url);
    } catch (e) { setError(e instanceof ApiClientError ? e.message : "Export failed."); }
  }

  async function loadFile(file: File) {
    setCsv(await file.text()); setChecked(null); setMessage("");
  }

  // Dry run first: the server validates every row and reports all errors without writing anything.
  async function check() {
    setError(""); setMessage("");
    try { setChecked(await api.importTasks(token, scenarioId, { csv, commit: false })); }
    catch (e) { setError(e instanceof ApiClientError ? e.message : "Check failed."); }
  }

  async function importNow() {
    setError("");
    try {
      const result = await api.importTasks(token, scenarioId, { csv, commit: true, note: "CSV import from the UI" });
      setChecked(result);
      setMessage(result.committed ? `Imported ${result.inserted} tasks as version ${result.version_no}.` : result.message ?? "Not imported.");
    } catch (e) { setError(e instanceof ApiClientError ? e.message : "Import failed."); }
  }

  return (
    <div className="stack">
      <Card title="Export tasks" sub="Downloads the current scenario tasks as a UTF-8 CSV file.">
        <div className="row gap-12" style={{ alignItems: "flex-end" }}>
          <div style={{ flex: "1 1 260px", minWidth: 0 }}>
            <Field label="Scenario">
              <select className="select" value={scenarioId} onChange={(e) => setScenarioId(Number(e.target.value))}>
                {scenarios.map(s => <option key={s.scenario_id} value={s.scenario_id}>{s.scenario_id} — {s.scenario_name}</option>)}
              </select>
            </Field>
          </div>
          <button className="btn btn-secondary" onClick={exportCsv}><IconDownload size={15} /> Export CSV</button>
        </div>
        {error && <div className="mt-16"><Alert kind="danger">{error}</Alert></div>}
      </Card>

      {!admin ? (
        <Card title="Import tasks" sub="Admin action">
          <Alert kind="info">
            Operators can export task data but cannot import it: importing changes the scenario and its version history.
          </Alert>
        </Card>
      ) : (
        <Card title="Import tasks" sub="Validate before writing. The dry run reports every error without touching the data.">
          <div className="field">
            <span className="label">CSV file</span>
            <input className="input" type="file" accept=".csv,text/csv"
              onChange={(e) => e.target.files?.[0] && loadFile(e.target.files[0])} />
            <span className="hint">
              Required columns: task_id, edge_id, component_name, estimated_hours, estimated_cost, service_weight, priority.
              Optional: region_code, required_skill, outage_cause, depends_on (ids separated by “;”).
            </span>
          </div>

          <div className="field mt-16">
            <span className="label">…or paste CSV</span>
            <textarea className="textarea mono" value={csv} rows={8}
              onChange={(e) => { setCsv(e.target.value); setChecked(null); setMessage(""); }}
              placeholder="task_id,edge_id,component_name,estimated_hours,…" />
          </div>

          <div className="row gap-8 mt-16">
            <button className="btn btn-secondary" onClick={check} disabled={!csv.trim()}>
              <IconCheck size={15} /> Check file
            </button>
            <button className="btn btn-primary" onClick={importNow} disabled={!checked?.valid}>
              <IconUpload size={15} /> Import valid file
            </button>
          </div>

          {checked && checked.valid && !checked.committed && (
            <div className="mt-16"><Alert kind="success">No errors found. Ready to import.</Alert></div>
          )}
          {checked && !checked.valid && (
            <div className="mt-16">
              <Alert kind="danger"><strong>{checked.errors.length} problem{checked.errors.length === 1 ? "" : "s"} found.</strong> Nothing was imported.</Alert>
              <div className="table-wrap mt-12" style={{ border: "1px solid var(--border)", borderRadius: 10 }}>
                <table className="table table-compact">
                  <thead><tr><th style={{ width: 70 }}>Row</th><th style={{ width: 130 }}>Column</th><th>Problem</th></tr></thead>
                  <tbody>
                    {checked.errors.map((e, i) => (
                      <tr key={i}>
                        <td className="num">{e.row || "file"}</td>
                        <td className="mono">{e.column}</td>
                        <td>{e.message}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}
          {message && <div className="mt-16"><Alert kind="success">{message}</Alert></div>}
        </Card>
      )}

    </div>
  );
}
