"use client";
import { useState } from "react";
import { api, ApiClientError } from "../lib/api-client";
import type { AuditPage, Role } from "../lib/api-types";
import { Alert, Card, Empty, Field } from "./ui";
import { IconArrowRight, IconSearch, IconShield } from "./icons";

const PAGE_SIZE = 25;
const TABLES = ["", "repair_tasks", "outage_scenarios", "restoration_runs"];
const OPERATIONS = ["", "INSERT", "UPDATE", "DELETE"];

const opBadge = (op: string) =>
  op === "INSERT" ? "badge-success" : op === "UPDATE" ? "badge-warn" : op === "DELETE" ? "badge-danger" : "badge-neutral";

export default function AuditPanel({ token, role }: { token: string; role: Role }) {
  const [table, setTable] = useState("");
  const [operation, setOperation] = useState("");
  const [rowKey, setRowKey] = useState("");
  const [appUser, setAppUser] = useState("");
  const [offset, setOffset] = useState(0);
  const [page, setPage] = useState<AuditPage | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  if (role !== "admin") {
    return (
      <Card title="Audit trail" sub="Administrators only">
        <Alert kind="danger">
          You do not have access to the audit history. It records who changed a scenario or task;
          ask an administrator if you need a specific change traced.
        </Alert>
      </Card>
    );
  }

  async function load(nextOffset: number) {
    setError(""); setLoading(true);
    const params: Record<string, string> = { limit: String(PAGE_SIZE), offset: String(nextOffset) };
    if (table) params.table_name = table;
    if (operation) params.operation = operation;
    if (rowKey.trim()) params.row_key = rowKey.trim();
    if (appUser.trim()) params.app_user = appUser.trim();
    try {
      setPage(await api.audit(token, params));
      setOffset(nextOffset);
    } catch (e) {
      setError(e instanceof ApiClientError ? e.message : "Could not load the audit history.");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="stack">
      <Card title="Filters" sub="Narrow by table, operation, primary key or application user.">
        <div className="form-grid">
          <Field label="Table">
            <select className="select" value={table} onChange={(e) => setTable(e.target.value)}>
              {TABLES.map(t => <option key={t} value={t}>{t || "Any table"}</option>)}
            </select>
          </Field>
          <Field label="Operation">
            <select className="select" value={operation} onChange={(e) => setOperation(e.target.value)}>
              {OPERATIONS.map(o => <option key={o} value={o}>{o || "Any operation"}</option>)}
            </select>
          </Field>
          <Field label="Row key">
            <input className="input mono" value={rowKey} onChange={(e) => setRowKey(e.target.value)} placeholder="e.g. T01" />
          </Field>
          <Field label="App user">
            <input className="input" value={appUser} onChange={(e) => setAppUser(e.target.value)} placeholder="e.g. admin" />
          </Field>
          <button className="btn btn-primary" onClick={() => load(0)} disabled={loading}>
            {loading ? <><span className="spinner" /> Searching…</> : <><IconSearch size={15} /> Search</>}
          </button>
        </div>
        {error && <div className="mt-16"><Alert kind="danger">{error}</Alert></div>}
      </Card>

      <Card title="Change history" sub={page ? `${page.total} matching change${page.total === 1 ? "" : "s"}` : "Run a search to load entries"}
        actions={page && page.total > PAGE_SIZE ? (
          <div className="row gap-6">
            <button className="btn btn-secondary btn-sm" disabled={offset === 0}
              onClick={() => load(Math.max(0, offset - PAGE_SIZE))}>Previous</button>
            <button className="btn btn-secondary btn-sm" disabled={offset + PAGE_SIZE >= page.total}
              onClick={() => load(offset + PAGE_SIZE)}>Next <IconArrowRight size={13} /></button>
          </div>
        ) : undefined}>
        {!page ? (
          <Empty icon={<IconShield size={18} />} title="No results yet">
            Apply a filter (or none) and search to page through the row-level audit trail.
          </Empty>
        ) : page.items.length === 0 ? (
          <Empty icon={<IconShield size={18} />} title="No matching changes">
            Try a wider filter or clear the row key.
          </Empty>
        ) : (
          <>
            <div className="table-wrap" style={{ border: "1px solid var(--border)", borderRadius: 10 }}>
              <table className="table table-compact">
                <thead>
                  <tr><th>Time</th><th>Table</th><th>Operation</th><th>Row</th><th>App user</th><th>DB user</th></tr>
                </thead>
                <tbody>
                  {page.items.map(i => (
                    <tr key={i.audit_id}>
                      <td className="small muted">{new Date(i.changed_at).toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" })}</td>
                      <td className="mono">{i.table_name}</td>
                      <td><span className={`badge ${opBadge(i.operation)}`}>{i.operation}</span></td>
                      <td className="mono">{i.row_key ?? "—"}</td>
                      <td>{i.app_user ?? <span className="muted">—</span>}</td>
                      <td className="mono small muted">{i.db_user}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <p className="small muted mt-12">
              Showing {page.items.length ? page.offset + 1 : 0}–{page.offset + page.items.length} of {page.total}.
            </p>
          </>
        )}
      </Card>
    </div>
  );
}
