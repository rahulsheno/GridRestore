// Typed fetch client over backend/api.py. Throws ApiClientError on non-2xx.
import type {
  PhysicsCurvePoint, PhysicsFigure, PhysicsMdpDetail, PhysicsOverview, PhysicsRun,
  AuditPage, CauseRow, CriticalPath, CriticalRepair, CrewSpec, GridView, ImportResult, Role,
  RunAction, RunSummary, ScheduleResult, Scenario, SearchHit, SearchMode, Session, SkillGaps, Strategy,
} from "./api-types";

export const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://127.0.0.1:8000";

export class ApiClientError extends Error {
  status: number;
  constructor(status: number, detail: string) {
    super(detail || `Request failed: ${status}`);
    this.status = status;
  }
}

// One fetch. Separate so the retry logic below cannot recurse into itself.
async function _raw<T>(path: string, token?: string, init?: RequestInit): Promise<T> {
  const headers: Record<string, string> = {};
  if (init?.headers) {
    for (const [k, v] of Object.entries(init.headers as Record<string, string>)) headers[k] = v;
  }
  if (token) headers.Authorization = `Bearer ${token}`;
  if (init?.body !== undefined) headers["Content-Type"] = "application/json";
  const res = await fetch(`${API_BASE}${path}`, { ...init, headers });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new ApiClientError(res.status, (data as { detail?: string }).detail ?? "Request failed");
  return data as T;
}

async function request<T>(path: string, token?: string, init?: RequestInit): Promise<T> {
  try { return await _raw<T>(path, token, init); }
  catch (err) {
    if (!(err instanceof ApiClientError) || err.status !== 401) throw err;
    const stored = getStoredSession();
    if (!stored?.refresh_token) throw err;  // anonymous request or no refresh: surface the 401
    try {
      const refreshed = await _raw<Session>("/api/refresh", undefined,
        { method: "POST", body: JSON.stringify({ refresh_token: stored.refresh_token }) });
      const updated: Session = { ...stored, token: refreshed.token, refresh_token: refreshed.refresh_token };
      localStorage.setItem("gr-session", JSON.stringify(updated));
      window.dispatchEvent(new CustomEvent("gr-session-updated"));
      return await _raw<T>(path, refreshed.token, init);
    } catch { throw err; }
  }
}

export function getStoredSession(): Session | null {
  const raw = typeof localStorage !== "undefined" ? localStorage.getItem("gr-session") : null;
  if (!raw) return null;
  try { return JSON.parse(raw) as Session; } catch { return null; }
}

async function requestText(path: string, token: string): Promise<string> {
  const res = await fetch(`${API_BASE}${path}`, { headers: { Authorization: `Bearer ${token}` } });
  if (!res.ok) {
    const data = await res.json().catch(() => ({}));
    throw new ApiClientError(res.status, (data as { detail?: string }).detail ?? "Request failed");
  }
  return res.text();
}

export const api = {
  login: (username: string, password: string) =>
    request<Session>("/api/login", undefined, { method: "POST", body: JSON.stringify({ username, password }) }),
  register: (username: string, password: string) =>
    request<Session>("/api/register", undefined, { method: "POST", body: JSON.stringify({ username, password }) }),
  scenarios: (token: string) => request<Scenario[]>("/api/scenarios", token),
  createScenario: (token: string, body: { name: string; budget: number; crew_count: number }) =>
    request<Scenario>("/api/scenarios", token, { method: "POST", body: JSON.stringify(body) }),
  strategies: (token: string) => request<Strategy[]>("/api/strategies", token),
  schedule: (token: string, body: { scenario_id: number; strategy: Strategy | string; crews?: CrewSpec[]; use_physics?: boolean }) =>
    request<ScheduleResult>("/api/schedule", token, { method: "POST", body: JSON.stringify(body) }),
  runs: (token: string) => request<RunSummary[]>("/api/runs", token),
  runActions: (token: string, runId: number) =>
    request<RunAction[]>(`/api/runs/${runId}/actions`, token),
  search: (token: string, body: { query: string; mode: SearchMode | string; limit?: number }) =>
    request<SearchHit[]>("/api/search", token, { method: "POST", body: JSON.stringify(body) }),
  criticalRepairs: (token: string, scenarioId: number) =>
    request<CriticalRepair[]>(`/api/scenarios/${scenarioId}/critical-repairs`, token),
  criticalPath: (token: string, scenarioId: number) =>
    request<CriticalPath>(`/api/scenarios/${scenarioId}/critical-path`, token),
  skillGaps: (token: string, scenarioId: number) =>
    request<SkillGaps>(`/api/scenarios/${scenarioId}/skill-gaps`, token),
  causeBreakdown: (token: string, scenarioId: number) =>
    request<CauseRow[]>(`/api/scenarios/${scenarioId}/cause-breakdown`, token),
  grid: (token: string, scenarioId: number) =>
    request<GridView>(`/api/scenarios/${scenarioId}/grid`, token),
  audit: (token: string, params: Record<string, string>) => {
    const query = new URLSearchParams(params).toString();
    return request<AuditPage>(`/api/audit${query ? `?${query}` : ""}`, token);
  },
  exportTasksCsv: (token: string, scenarioId: number) =>
    requestText(`/api/scenarios/${scenarioId}/tasks.csv`, token),
  importTasks: (token: string, scenarioId: number, body: { csv: string; commit: boolean; note?: string }) =>
    request<ImportResult>(`/api/scenarios/${scenarioId}/tasks/import`, token, { method: "POST", body: JSON.stringify(body) }),
  refresh: (refreshToken: string) =>
    request<Session>("/api/refresh", undefined, { method: "POST", body: JSON.stringify({ refresh_token: refreshToken }) }),
  logout: (refreshToken: string) =>
    request<{ revoked: boolean }>("/api/logout", undefined, { method: "POST", body: JSON.stringify({ refresh_token: refreshToken }) }),
  changePassword: (token: string, oldPassword: string, newPassword: string) =>
    request<Session>("/api/password", token, { method: "POST", body: JSON.stringify({ old_password: oldPassword, new_password: newPassword }) }),
};

export type { Role };

// Physics study results (read-only). Kept separate from `api` so the scheduling client is unchanged.
export const physicsApi = {
  runs: (token: string) => request<PhysicsRun[]>("/api/physics/runs", token),
  overview: (token: string, runId: number) => request<PhysicsOverview>(`/api/physics/runs/${runId}`, token),
  continuation: (token: string, runId: number, caseName: string) =>
    request<PhysicsCurvePoint[]>(`/api/physics/runs/${runId}/continuation/${caseName}`, token),
  mdp: (token: string, runId: number, caseName: string) =>
    request<PhysicsMdpDetail>(`/api/physics/runs/${runId}/mdp/${caseName}`, token),
  figure: (token: string, runId: number, name: string) =>
    request<PhysicsFigure>(`/api/physics/runs/${runId}/figures/${name}`, token),
};
