// Typed fetch client over backend/api.py. Throws ApiClientError on non-2xx.
import type {
  CauseRow, CriticalPath, CriticalRepair, CrewSpec, Role, RunAction, RunSummary,
  ScheduleResult, Scenario, SearchHit, SearchMode, Session, SkillGaps, Strategy,
} from "./api-types";

export const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://127.0.0.1:8000";

export class ApiClientError extends Error {
  status: number;
  constructor(status: number, detail: string) {
    super(detail || `Request failed: ${status}`);
    this.status = status;
  }
}

async function request<T>(path: string, token?: string, init?: RequestInit): Promise<T> {
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

export const api = {
  login: (username: string, password: string) =>
    request<Session>("/api/login", undefined, { method: "POST", body: JSON.stringify({ username, password }) }),
  scenarios: (token: string) => request<Scenario[]>("/api/scenarios", token),
  createScenario: (token: string, body: { name: string; budget: number; crew_count: number }) =>
    request<Scenario>("/api/scenarios", token, { method: "POST", body: JSON.stringify(body) }),
  strategies: (token: string) => request<Strategy[]>("/api/strategies", token),
  schedule: (token: string, body: { scenario_id: number; strategy: Strategy | string; crews?: CrewSpec[] }) =>
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
};

export type { Role };
