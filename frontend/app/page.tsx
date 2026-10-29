"use client";
import { useEffect, useMemo, useRef, useState } from "react";
import dynamic from "next/dynamic";
import { api, ApiClientError, getStoredSession } from "../lib/api-client";
import ThemeToggle from "../components/ThemeToggle";
import GridPanel from "../components/GridPanel";
import AuditPanel from "../components/AuditPanel";
import TaskDataPanel from "../components/TaskDataPanel";
import PhysicsPanel from "../components/PhysicsPanel";
import { Alert, Card, Empty, Field, PageHead, Spinner, Stat } from "../components/ui";
import {
  IconActivity, IconAlert, IconArrowRight, IconBolt, IconCalendar, IconChart, IconCheck,
  IconChevronDown, IconClock, IconClose, IconDashboard, IconDatabase, IconEye, IconEyeOff,
  IconHistory, IconKey, IconLayers, IconLogout, IconMenu, IconNetwork, IconPlay,
  IconPlus, IconRoute, IconSearch, IconShield,
} from "../components/icons";
import type {
  CauseRow, CriticalPath, CriticalRepair, RunAction, RunSummary,
  ScheduleResult, Scenario, SearchHit, SearchMode, Session, SkillGaps, Strategy,
} from "../lib/api-types";

const GridScene = dynamic(() => import("../components/GridScene"), {
  ssr: false,
  loading: () => null,
});

const DEFAULT_CREWS = [{ crew_id: "C1", skill: "multi-skill" }, { crew_id: "C2", skill: "general" }, { crew_id: "C3", skill: "general" }];

const PRESET_NAMES = (() => {
  const core = [
    "Storm outage - North region",
    "Equipment failure - Central feeder",
    "Vehicle impact - Feeder E7",
    "Vegetation contact - South line",
    "Hospital feeder fault",
    "Water facility outage - Branch E5",
  ];
  const causes = [
    "Storm outage", "Equipment failure", "Vehicle impact", "Vegetation contact",
    "Cable fault", "Transformer failure", "Feeder trip", "Overload",
    "Ground fault", "Relay misoperation",
  ];
  const assets = [
    "Feeder E1", "Feeder E2", "Feeder E3", "Feeder E4", "Feeder E5", "Feeder E6",
    "Feeder E7", "Feeder E8", "Feeder E9", "Substation S1", "North bus B1",
  ];
  const generated = causes.flatMap((cause) => assets.map((asset) => `${cause} - ${asset}`));
  return [...core, ...generated.filter((name) => !core.includes(name))];
})();

type Tab = "scenarios" | "schedule" | "runs" | "search" | "critical" | "grid" | "data" | "audit" | "physics";

const TAB_META: Record<Tab, { title: string; sub: string }> = {
  scenarios: { title: "Overview", sub: "Portfolio of outage scenarios, budgets and crew capacity." },
  schedule: { title: "Scheduling", sub: "Run a restoration heuristic under budget, precedence and crew-skill constraints." },
  runs: { title: "Saved runs", sub: "Every schedule is persisted with its assignments and provenance." },
  search: { title: "Repair search", sub: "Find similar past repairs by semantics or by full-text match." },
  critical: { title: "Critical path", sub: "Find the unblockers, the makespan floor and the skill coverage gaps." },
  grid: { title: "Grid map", sub: "Network topology with restoration status from the latest saved run." },
  data: { title: "Task data", sub: "Bulk edit scenario tasks through a validated CSV round-trip." },
  audit: { title: "Audit trail", sub: "Row-level change history captured by database triggers." },
  physics: { title: "Physics study", sub: "Power-flow, continuation, FDIA and MDP results on IEEE benchmark cases." },
};

const NAV: { group: string; items: { id: Tab; label: string; icon: typeof IconBolt }[] }[] = [
  {
    group: "Operate",
    items: [
      { id: "scenarios", label: "Overview", icon: IconDashboard },
      { id: "schedule", label: "Scheduling", icon: IconCalendar },
      { id: "runs", label: "Saved runs", icon: IconHistory },
    ],
  },
  {
    group: "Analyse",
    items: [
      { id: "search", label: "Repair search", icon: IconSearch },
      { id: "critical", label: "Critical path", icon: IconRoute },
      { id: "grid", label: "Grid map", icon: IconNetwork },
    ],
  },
  {
    group: "Administration",
    items: [
      { id: "data", label: "Task data", icon: IconDatabase },
      { id: "audit", label: "Audit trail", icon: IconShield },
      { id: "physics", label: "Physics study", icon: IconActivity },
    ],
  },
];

const STRATEGY_LABEL: Record<string, string> = {
  gridrestore_score: "GridRestore score",
  priority_first: "Priority first",
  shortest_repair_first: "Shortest repair first",
};

const nf = (v: unknown, digits = 0) => {
  const x = Number(v);
  if (v === null || v === undefined || Number.isNaN(x)) return "—";
  return x.toLocaleString(undefined, { minimumFractionDigits: digits, maximumFractionDigits: digits });
};

const initials = (name: string) => name.trim().slice(0, 2).toUpperCase() || "?";

type Toast = { kind: "success" | "error" | "info"; text: string };

export default function Home() {
  const [session, setSession] = useState<Session | null>(null);
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [page, setPage] = useState<"login" | "signup">("login");
  const [showPw, setShowPw] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [tab, setTab] = useState<Tab>("scenarios");
  const [menuOpen, setMenuOpen] = useState(false);
  const [accountOpen, setAccountOpen] = useState(false);
  const accountRef = useRef<HTMLDivElement>(null);
  const [toast, setToast] = useState<Toast | null>(null);

  const [scenarios, setScenarios] = useState<Scenario[]>([]);
  const [runs, setRuns] = useState<RunSummary[]>([]);
  const [actions, setActions] = useState<RunAction[]>([]);
  const [strategies, setStrategies] = useState<Strategy[]>([]);
  const [scenarioId, setScenarioId] = useState<number>(1);
  const [strategy, setStrategy] = useState<Strategy>("gridrestore_score");
  const [usePhysics, setUsePhysics] = useState(false);
  const [running, setRunning] = useState(false);
  const [result, setResult] = useState<ScheduleResult | null>(null);
  const [query, setQuery] = useState("hospital emergency power repair");
  const [mode, setMode] = useState<SearchMode>("vector");
  const [hits, setHits] = useState<SearchHit[]>([]);
  const [searching, setSearching] = useState(false);
  const [searched, setSearched] = useState(false);
  const [crit, setCrit] = useState<CriticalRepair[]>([]);
  const [cpath, setCpath] = useState<CriticalPath | null>(null);
  const [gaps, setGaps] = useState<SkillGaps | null>(null);
  const [causes, setCauses] = useState<CauseRow[]>([]);
  const [analysing, setAnalysing] = useState(false);
  const [name, setName] = useState(PRESET_NAMES[0]);
  const [budget, setBudget] = useState(14000);
  const [crewCount, setCrewCount] = useState(3);
  const [creating, setCreating] = useState(false);
  const [oldPw, setOldPw] = useState("");
  const [newPw, setNewPw] = useState("");
  const [showPwForm, setShowPwForm] = useState(false);
  const [pwError, setPwError] = useState("");
  const [pwBusy, setPwBusy] = useState(false);

  const token = session?.token ?? "";
  const meta = TAB_META[tab];

  function fail(e: unknown, fallback: string) {
    setError(e instanceof ApiClientError ? `${fallback}: ${e.message} (${e.status})` : `${fallback}.`);
  }

  function notify(text: string, kind: Toast["kind"] = "success") {
    setToast({ kind, text });
  }

  useEffect(() => {
    if (!toast) return;
    const t = setTimeout(() => setToast(null), 3800);
    return () => clearTimeout(t);
  }, [toast]);

  // Moving between views should start at the top, like a real route change.
  useEffect(() => {
    window.scrollTo(0, 0);
  }, [tab]);

  useEffect(() => {
    const raw = localStorage.getItem("gr-session");
    if (raw) {
      try { setSession(JSON.parse(raw) as Session); } catch { /* ignore corrupt state */ }
    }
  }, []);

  useEffect(() => {
    // The API client rotates the access token behind our back on a 401;
    // pull the refreshed session in so the next calls do not refresh again.
    const onUpdated = () => {
      const next = getStoredSession();
      if (next) setSession(next);
    };
    window.addEventListener("gr-session-updated", onUpdated);
    return () => window.removeEventListener("gr-session-updated", onUpdated);
  }, []);

  useEffect(() => {
    if (session) {
      load(session.token).catch(() => {
        setSession(null);
        localStorage.removeItem("gr-session");
      });
    }
  }, [session]);

  useEffect(() => {
    if (!accountOpen) return;
    const onDown = (e: MouseEvent) => {
      if (accountRef.current && !accountRef.current.contains(e.target as Node)) setAccountOpen(false);
    };
    document.addEventListener("mousedown", onDown);
    return () => document.removeEventListener("mousedown", onDown);
  }, [accountOpen]);

  useEffect(() => {
    if (!showPwForm) return;
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") setShowPwForm(false); };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [showPwForm]);

  async function load(t: string) {
    const [sc, rn, st] = await Promise.all([api.scenarios(t), api.runs(t), api.strategies(t)]);
    setScenarios(sc); setRuns(rn); setStrategies(st);
    if (sc.length) setScenarioId(prev => (sc.some(s => s.scenario_id === prev) ? prev : sc[0].scenario_id));
  }

  async function logout() {
    try { if (session?.refresh_token) await api.logout(session.refresh_token); } catch { /* token may already be gone */ }
    setSession(null);
    localStorage.removeItem("gr-session");
    setPage("login");
    setPassword("");
    setAccountOpen(false);
  }

  async function changePassword() {
    setPwError(""); setPwBusy(true);
    try {
      const s = await api.changePassword(token, oldPw, newPw);
      setSession(s);
      localStorage.setItem("gr-session", JSON.stringify(s));
      setOldPw(""); setNewPw(""); setShowPwForm(false);
      notify("Password updated. Other sessions were signed out.");
    } catch (e) {
      setPwError(e instanceof ApiClientError ? e.message : "Password change failed.");
    } finally {
      setPwBusy(false);
    }
  }

  async function login() {
    setError(""); setBusy(true);
    try {
      const s = await api.login(username, password);
      setSession(s);
      localStorage.setItem("gr-session", JSON.stringify(s));
    } catch {
      setError("Invalid credentials. Check your username and password.");
    } finally {
      setBusy(false);
    }
  }

  async function signup() {
    setError(""); setBusy(true);
    try {
      await api.register(username, password);
      const s = await api.login(username, password);
      setSession(s);
      localStorage.setItem("gr-session", JSON.stringify(s));
      notify("Account created. Signed in as operator.");
    } catch (e) {
      fail(e, "Sign-up failed");
    } finally {
      setBusy(false);
    }
  }

  async function createScenario() {
    setError(""); setCreating(true);
    try {
      const created = await api.createScenario(token, { name, budget, crew_count: crewCount });
      await load(token);
      setScenarioId(created.scenario_id);
      notify(`Scenario #${created.scenario_id} created.`);
    } catch (e) {
      fail(e, "Create failed");
    } finally {
      setCreating(false);
    }
  }

  async function runSchedule() {
    setResult(null); setError(""); setRunning(true);
    try {
      const data = await api.schedule(token, { scenario_id: scenarioId, strategy, crews: DEFAULT_CREWS, use_physics: usePhysics });
      setResult(data);
      setActions([]);
      await load(token);
      notify(`Run #${data.run_id} saved: ${data.scheduled_count} tasks scheduled.`);
    } catch (e) {
      fail(e, "Schedule failed");
    } finally {
      setRunning(false);
    }
  }

  async function showActions(runId: number) {
    setError("");
    try { setActions(await api.runActions(token, runId)); } catch (e) { fail(e, "Load actions failed"); }
  }

  async function search() {
    setError(""); setSearching(true);
    try {
      setHits(await api.search(token, { query, mode, limit: 5 }));
      setSearched(true);
    } catch (e) {
      fail(e, "Search failed");
    } finally {
      setSearching(false);
    }
  }

  async function loadCritical() {
    setError(""); setAnalysing(true);
    try {
      const [cr, cp, sg, cb] = await Promise.all([
        api.criticalRepairs(token, scenarioId),
        api.criticalPath(token, scenarioId),
        api.skillGaps(token, scenarioId),
        api.causeBreakdown(token, scenarioId),
      ]);
      setCrit(cr); setCpath(cp); setGaps(sg); setCauses(cb);
    } catch (e) {
      fail(e, "Critical analysis failed");
    } finally {
      setAnalysing(false);
    }
  }

  const latestRun = useMemo(
    () => [...runs].sort((a, b) => Number(b.run_id) - Number(a.run_id))[0],
    [runs],
  );

  /* ------------------------------------------------------------- auth view */
  if (!session) {
    const isLogin = page === "login";
    return (
      <div className="auth">
        <aside className="auth-brand">
          <div className="auth-scene" aria-hidden="true">
            <GridScene />
          </div>

          <div className="brand">
            <span className="brand-mark"><IconBolt size={19} /></span>
            <span>
              <span className="brand-name">GridRestore</span>
              <span className="brand-tag" style={{ display: "block" }}>Restoration planning workspace</span>
            </span>
          </div>
        </aside>

        <main className="auth-panel">
          <div style={{ position: "absolute", top: 18, right: 18 }}>
            <ThemeToggle />
          </div>
          <div className="auth-card">
            <div className="auth-eyebrow">GridRestore</div>
            <h1 className="auth-title">{isLogin ? "Sign in to your workspace" : "Create your account"}</h1>
            <p className="auth-sub">
              {isLogin
                ? "Use your account to open scenarios and run schedules."
                : "New accounts are created with the operator role. Admin accounts already exist."}
            </p>

            <form className="auth-form" onSubmit={(e) => { e.preventDefault(); if (!busy) (isLogin ? login() : signup()); }}>
              <Field label="Username" htmlFor="username">
                <input id="username" className="input" value={username} autoComplete="username" autoFocus
                  placeholder={isLogin ? "Your username" : "3–50 characters"}
                  onChange={(e) => setUsername(e.target.value)} />
              </Field>

              <Field label="Password" htmlFor="password">
                <div style={{ position: "relative" }}>
                  <input id="password" className="input" style={{ paddingRight: 44 }}
                    type={showPw ? "text" : "password"} value={password}
                    autoComplete={isLogin ? "current-password" : "new-password"}
                    placeholder={isLogin ? "Password" : "At least 6 characters"}
                    onChange={(e) => setPassword(e.target.value)} />
                  <button type="button" className="icon-btn" onClick={() => setShowPw(v => !v)}
                    style={{ position: "absolute", right: 1, top: 1, height: 36 }}
                    aria-label={showPw ? "Hide password" : "Show password"}
                    title={showPw ? "Hide password" : "Show password"}>
                    {showPw ? <IconEyeOff size={17} /> : <IconEye size={17} />}
                  </button>
                </div>
              </Field>

              {error && <Alert kind="danger">{error}</Alert>}

              <button type="submit" className="btn btn-primary btn-block" disabled={busy}>
                {busy ? <><span className="spinner" /> Please wait…</> : isLogin ? "Sign in" : "Create account"}
              </button>
            </form>

            <p className="auth-switch">
              {isLogin ? "New here?" : "Already registered?"}{" "}
              <a href="#" onClick={(e) => { e.preventDefault(); setPage(isLogin ? "signup" : "login"); setError(""); }}>
                {isLogin ? "Create an account" : "Sign in"}
              </a>
            </p>
          </div>
        </main>
      </div>
    );
  }

  const roleLabel = session.role === "admin" ? "Administrator" : "Operator";

  /* ------------------------------------------------------------ app shell */
  return (
    <div className="app">
      {menuOpen && <div className="scrim" onClick={() => setMenuOpen(false)} aria-hidden="true" />}

      <aside className={`sidebar ${menuOpen ? "open" : ""}`}>
        <div className="brand">
          <span className="brand-mark"><IconBolt size={19} /></span>
          <span>
            <span className="brand-name">GridRestore</span>
            <span className="brand-tag" style={{ display: "block" }}>Restoration planning</span>
          </span>
        </div>

        <nav className="nav" aria-label="Primary">
          {NAV.map((group) => (
            <div className="nav-group" key={group.group}>
              <span className="nav-label">{group.group}</span>
              {group.items.map((item) => {
                const Icon = item.icon;
                return (
                  <button key={item.id} className={`nav-item ${tab === item.id ? "active" : ""}`}
                    onClick={() => { setTab(item.id); setError(""); setMenuOpen(false); }}
                    aria-current={tab === item.id ? "page" : undefined}>
                    <span className="nav-icon"><Icon size={17} /></span>
                    {item.label}
                  </button>
                );
              })}
            </div>
          ))}
        </nav>

        <div className="sidebar-foot">
          <span className="avatar">{initials(session.username)}</span>
          <div className="meta" style={{ minWidth: 0 }}>
            <strong>{session.username}</strong>
            <span>{roleLabel}</span>
          </div>
        </div>
      </aside>

      <div className="main">
        <header className="topbar">
          <button className="icon-btn mobile-only" onClick={() => setMenuOpen(true)} aria-label="Open navigation">
            <IconMenu size={18} />
          </button>
          <div className="crumbs">
            <span>GridRestore</span>
            <span className="sep">/</span>
            <strong>{meta.title}</strong>
          </div>
          <span className="spacer" />
          <ThemeToggle />
          <div style={{ position: "relative" }} ref={accountRef}>
            <button className="user-chip" onClick={() => setAccountOpen(v => !v)} aria-haspopup="menu" aria-expanded={accountOpen}>
              <span className="avatar">{initials(session.username)}</span>
              <span className="who">
                <strong>{session.username}</strong>
                <span>{roleLabel}</span>
              </span>
              <IconChevronDown size={14} />
            </button>
            {accountOpen && (
              <div className="menu" role="menu">
                <div className="menu-head">
                  <strong>{session.username}</strong>
                  <span>{roleLabel} · session {session.expires_in ? `${Math.round(session.expires_in / 60)} min` : "active"}</span>
                </div>
                <button className="menu-item" role="menuitem"
                  onClick={() => { setShowPwForm(true); setPwError(""); setAccountOpen(false); }}>
                  <IconKey size={16} /> Change password
                </button>
                <div className="menu-sep" />
                <button className="menu-item danger" role="menuitem" onClick={logout}>
                  <IconLogout size={16} /> Sign out
                </button>
              </div>
            )}
          </div>
        </header>

        <main className="content">
          <PageHead title={meta.title} sub={meta.sub} actions={
            tab === "critical" ? (
              <>
                <div style={{ flex: "1 1 240px", maxWidth: 340 }}>
                  <select className="select" value={scenarioId}
                    aria-label="Scenario" onChange={(e) => setScenarioId(Number(e.target.value))}>
                    {scenarios.map(s => <option key={s.scenario_id} value={s.scenario_id}>{s.scenario_id} — {s.scenario_name}</option>)}
                  </select>
                </div>
                <button className="btn btn-primary" onClick={loadCritical} disabled={analysing}>
                  {analysing ? <><span className="spinner" /> Analysing…</> : <><IconActivity size={15} /> Analyse scenario</>}
                </button>
              </>
            ) : undefined
          } />

          {session.must_change_password && (
            <div className="mt-16" style={{ marginBottom: 20 }}>
              <Alert kind="warn">
                Your password is due for a change. Update it to keep the account in policy.{" "}
                <a href="#" onClick={(e) => { e.preventDefault(); setShowPwForm(true); }}>Change password</a>
              </Alert>
            </div>
          )}

          {error && <div style={{ marginBottom: 20 }}><Alert kind="danger">{error}</Alert></div>}

          {tab === "scenarios" && (
            <div className="stack">
              <div className="stats">
                <Stat label="Scenarios" value={nf(scenarios.length)} hint="Outage cases in the workspace"
                  icon={<IconLayers size={15} />} />
                <Stat label="Saved runs" value={nf(runs.length)} hint="Persisted schedules"
                  icon={<IconHistory size={15} />} />
                <Stat label="Latest makespan"
                  value={latestRun ? <>{nf(latestRun.makespan_hours, 1)}<small> h</small></> : "—"}
                  hint={latestRun ? `Run #${latestRun.run_id} · ${STRATEGY_LABEL[latestRun.strategy_name] ?? latestRun.strategy_name}` : "No runs saved yet"}
                  icon={<IconClock size={15} />} />
                <Stat label="Latest score"
                  value={latestRun ? nf(latestRun.weighted_recovery_score, 1) : "—"}
                  hint="Weighted recovery objective"
                  icon={<IconChart size={15} />} />
              </div>

              {session.role === "admin" && (
                <Card title="New scenario" sub="Admin only. Tasks start from the demo set and the action is audited.">
                  <div className="form-grid" style={{ alignItems: "start" }}>
                    <Field label="Scenario name" hint="Pick a name below or from the list.">
                      <select className="select" value={name} onChange={(e) => setName(e.target.value)}>
                        {PRESET_NAMES.map(n => <option key={n} value={n}>{n}</option>)}
                      </select>
                    </Field>
                    <Field label="Budget" hint="Upper bound on total repair cost">
                      <input className="input num" type="number" min={1} value={budget}
                        onChange={(e) => setBudget(Number(e.target.value))} />
                    </Field>
                    <Field label="Crews" hint="Available crew count">
                      <input className="input num" type="number" min={1} max={20} value={crewCount}
                        onChange={(e) => setCrewCount(Number(e.target.value))} />
                    </Field>
                  </div>

                  <div className="mt-16">
                    <span className="stat-label" style={{ display: "block", marginBottom: 8 }}>
                      Scenario names ({PRESET_NAMES.length})
                    </span>
                    <div className="chip-list">
                      {PRESET_NAMES.map(n => (
                        <button key={n} type="button" onClick={() => setName(n)}
                          className={`chip chip-btn ${name === n ? "active" : ""}`}
                          aria-pressed={name === n}>
                          {n}
                        </button>
                      ))}
                    </div>
                  </div>

                  <div className="row gap-12 mt-20" style={{ justifyContent: "space-between" }}>
                    <span className="small muted">Each scenario gets a new ID, its own task list and audit entry.</span>
                    <button className="btn btn-primary" onClick={createScenario} disabled={creating}>
                      {creating ? <><span className="spinner" /> Creating…</> : <><IconPlus size={15} /> Create scenario</>}
                    </button>
                  </div>
                </Card>
              )}

              <Card title="Scenarios" sub={`${scenarios.length} scenario${scenarios.length === 1 ? "" : "s"} available`} flush>
                {scenarios.length === 0 ? (
                  <div style={{ padding: 20 }}>
                    <Empty icon={<IconLayers size={18} />} title="No scenarios yet">
                      {session.role === "admin" ? "Create one above to start planning." : "Ask an administrator to create a scenario."}
                    </Empty>
                  </div>
                ) : (
                  <div className="table-wrap">
                    <table className="table">
                      <thead>
                        <tr>
                          <th style={{ width: 70 }}>ID</th>
                          <th>Name</th>
                          <th className="num">Budget</th>
                          <th className="num">Crews</th>
                          <th style={{ width: 120 }} />
                        </tr>
                      </thead>
                      <tbody>
                        {scenarios.map(s => (
                          <tr key={s.scenario_id}>
                            <td className="id">SCN-{String(s.scenario_id).padStart(2, "0")}</td>
                            <td className="strong">{s.scenario_name}</td>
                            <td className="num">{nf(s.budget)}</td>
                            <td className="num">{nf(s.crew_count)}</td>
                            <td className="right">
                              <button className="btn btn-secondary btn-sm"
                                onClick={() => { setScenarioId(s.scenario_id); setResult(null); setTab("schedule"); }}>
                                Schedule <IconArrowRight size={13} />
                              </button>
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                )}
              </Card>
            </div>
          )}

          {tab === "schedule" && (
            <div className="stack">
              <Card title="Scheduling input" sub="Choose the scenario and strategy. Runs are persisted with their assignments.">
                <div className="form-grid">
                  <Field label="Scenario">
                    <select className="select" value={scenarioId} onChange={(e) => setScenarioId(Number(e.target.value))}>
                      {scenarios.map(s => <option key={s.scenario_id} value={s.scenario_id}>{s.scenario_id} — {s.scenario_name}</option>)}
                    </select>
                  </Field>
                  <Field label="Strategy">
                    <select className="select" value={strategy} onChange={(e) => setStrategy(e.target.value as Strategy)}>
                      {strategies.map(s => <option key={s} value={s}>{STRATEGY_LABEL[s] ?? s}</option>)}
                    </select>
                  </Field>
                  <Field label="Crew roster">
                    <div className="row gap-6" style={{ height: 38, alignItems: "center" }}>
                      {DEFAULT_CREWS.map(c => (
                        <span className="chip" key={c.crew_id}><span className="dot" style={{ color: "var(--accent)" }} />{c.crew_id} · {c.skill}</span>
                      ))}
                    </div>
                  </Field>
                </div>

                {strategy === "gridrestore_score" && (
                  <label className="check-row mt-16">
                    <input type="checkbox" checked={usePhysics} onChange={(e) => setUsePhysics(e.target.checked)} />
                    <span>
                      <span className="check-title">Apply physics-layer weights</span>
                      <span className="check-sub">
                        Repairs in voltage-weak areas receive up to 1.25× service weight, using the
                        element-to-IEEE-case mapping derived from continuation margins.
                      </span>
                    </span>
                  </label>
                )}

                <div className="row gap-8 mt-16">
                  <button className="btn btn-primary" onClick={runSchedule} disabled={running}>
                    {running ? <><span className="spinner" /> Running…</> : <><IconPlay size={15} /> Run and save</>}
                  </button>
                  <span className="small muted">Budget and crew limits are enforced by the scheduler.</span>
                </div>
              </Card>

              {result && (
                <>
                  <div className="stats">
                    <Stat label="Run" value={`#${result.run_id}`} hint={STRATEGY_LABEL[result.strategy] ?? result.strategy} />
                    <Stat label="Scheduled" value={nf(result.scheduled_count)} hint={`${result.unscheduled_task_ids.length} left unscheduled`} />
                    <Stat label="Total cost" value={nf(result.total_cost)} hint="Within scenario budget" />
                    <Stat label="Makespan" value={<>{nf(result.makespan_hours, 1)}<small> h</small></>} hint="Last finish time" />
                    <Stat label="Weighted score" value={nf(result.weighted_recovery_score, 1)} hint="Recovery objective" />
                  </div>

                  <Card title="Crew timeline" sub={`${result.scheduled_count} assignments across ${DEFAULT_CREWS.length} crews`}>
                    <Gantt actions={result.actions} makespan={Number(result.makespan_hours)} />
                  </Card>

                  <Card title="Assignments" sub="Saved run detail" flush>
                    <div className="table-wrap">
                      <table className="table">
                        <thead>
                          <tr>
                            <th>Task</th><th>Crew</th>
                            <th className="num">Start</th><th className="num">Finish</th>
                            <th className="num">Hours</th><th className="num">Cost</th><th className="num">Weight</th>
                          </tr>
                        </thead>
                        <tbody>
                          {result.actions.map(a => (
                            <tr key={a.task_id}>
                              <td className="id">{a.task_id}</td>
                              <td><span className="chip">{a.crew_id}</span></td>
                              <td className="num">{nf(a.start_hour, 1)} h</td>
                              <td className="num">{nf(a.finish_hour, 1)} h</td>
                              <td className="num">{nf(Number(a.finish_hour) - Number(a.start_hour), 1)}</td>
                              <td className="num">{nf(a.estimated_cost)}</td>
                              <td className="num">{nf(a.service_weight)}</td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  </Card>

                  {result.unscheduled_task_ids.length > 0 && (
                    <Alert kind="warn">
                      <strong>Unscheduled:</strong> {result.unscheduled_task_ids.join(", ")}.
                      These tasks exceed the budget, crew or precedence window.
                    </Alert>
                  )}
                </>
              )}

              {!result && (
                <Empty icon={<IconCalendar size={18} />} title="No run in this session">
                  Configure the inputs above and run the scheduler to see the assignments and timeline.
                </Empty>
              )}
            </div>
          )}

          {tab === "runs" && (
            <div className="stack">
              <Card title="Saved runs" sub={`${runs.length} persisted schedule${runs.length === 1 ? "" : "s"}`} flush>
                {runs.length === 0 ? (
                  <div style={{ padding: 20 }}>
                    <Empty icon={<IconHistory size={18} />} title="No saved runs">
                      Run a schedule to create the first entry.
                    </Empty>
                  </div>
                ) : (
                  <div className="table-wrap">
                    <table className="table">
                      <thead>
                        <tr>
                          <th style={{ width: 70 }}>Run</th><th>Scenario</th><th>Strategy</th>
                          <th className="num">Cost</th><th className="num">Makespan</th>
                          <th className="num">Score</th><th className="num">Started</th><th style={{ width: 110 }} />
                        </tr>
                      </thead>
                      <tbody>
                        {[...runs].sort((a, b) => Number(b.run_id) - Number(a.run_id)).map(r => (
                          <tr key={r.run_id}>
                            <td className="id">#{r.run_id}</td>
                            <td className="strong">{r.scenario_name}</td>
                            <td><span className="badge badge-neutral">{STRATEGY_LABEL[r.strategy_name] ?? r.strategy_name}</span></td>
                            <td className="num">{nf(r.total_cost)}</td>
                            <td className="num">{nf(r.makespan_hours, 1)} h</td>
                            <td className="num">{nf(r.weighted_recovery_score, 1)}</td>
                            <td className="num small muted">{r.started_at ? new Date(r.started_at).toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" }) : "—"}</td>
                            <td className="right">
                              <button className="btn btn-secondary btn-sm" onClick={() => showActions(r.run_id)}>
                                Actions <IconArrowRight size={13} />
                              </button>
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                )}
              </Card>

              {actions.length > 0 && (
                <Card title="Assignments" sub="Selected run" flush
                  actions={<span className="chip">{actions.length} tasks</span>}>
                  <div className="table-wrap">
                    <table className="table">
                      <thead><tr><th>Task</th><th>Crew</th><th className="num">Start</th><th className="num">Finish</th></tr></thead>
                      <tbody>
                        {actions.map((a, i) => (
                          <tr key={`${a.task_id}-${i}`}>
                            <td className="id">{a.task_id}</td>
                            <td><span className="chip">{a.crew_label}</span></td>
                            <td className="num">{nf(a.start_hour, 1)} h</td>
                            <td className="num">{nf(a.finish_hour, 1)} h</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </Card>
              )}
            </div>
          )}

          {tab === "search" && (
            <div className="stack">
              <Card title="Find similar repairs" sub="Semantic search compares 384-dimension embeddings; full-text uses PostgreSQL ranking.">
                <div className="row gap-12" style={{ alignItems: "flex-end" }}>
                  <div style={{ flex: "1 1 280px", minWidth: 0 }}>
                    <Field label="Fault description">
                      <input className="input" value={query} onChange={(e) => setQuery(e.target.value)}
                        onKeyDown={(e) => { if (e.key === "Enter") search(); }}
                        placeholder="e.g. hospital emergency power repair" />
                    </Field>
                  </div>
                  <div className="seg" role="group" aria-label="Search mode">
                    <button className={mode === "vector" ? "active" : ""} onClick={() => setMode("vector")}>Semantic</button>
                    <button className={mode === "fts" ? "active" : ""} onClick={() => setMode("fts")}>Full-text</button>
                  </div>
                  <button className="btn btn-primary" onClick={search} disabled={searching}>
                    {searching ? <><span className="spinner" /> Searching…</> : <><IconSearch size={15} /> Search</>}
                  </button>
                </div>
              </Card>

              {searched && hits.length === 0 ? (
                <Empty icon={<IconSearch size={18} />} title="No matches">
                  Try a broader fault description or switch the search mode.
                </Empty>
              ) : hits.length > 0 ? (
                <Card title="Results" sub={`${hits.length} closest repair narratives`} flush>
                  <div className="table-wrap">
                    <table className="table">
                      <thead>
                        <tr><th style={{ width: 54 }}>Rank</th><th style={{ width: 80 }}>Task</th><th>Narrative</th><th style={{ width: 160 }}>Score</th></tr>
                      </thead>
                      <tbody>
                        {hits.map((h, i) => {
                          const similarity = h.distance !== undefined && h.distance !== null
                            ? Math.max(0, Math.min(1, 1 - Number(h.distance)))
                            : undefined;
                          return (
                            <tr key={h.task_id}>
                              <td className="num muted">{i + 1}</td>
                              <td className="id">{h.task_id}</td>
                              <td>{h.narrative}</td>
                              <td>
                                {similarity !== undefined ? (
                                  <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                                    <div className="score-bar" style={{ flex: 1 }}>
                                      <span style={{ width: `${(similarity * 100).toFixed(0)}%` }} />
                                    </div>
                                    <span className="mono small muted">{nf(similarity * 100, 0)}%</span>
                                  </div>
                                ) : (
                                  <span className="mono small muted">rank {h.rank ?? "—"}</span>
                                )}
                              </td>
                            </tr>
                          );
                        })}
                      </tbody>
                    </table>
                  </div>
                </Card>
              ) : null}
            </div>
          )}

          {tab === "critical" && (
            <div className="stack">
              {!cpath && !crit.length ? (
                <Empty icon={<IconRoute size={18} />} title="No analysis loaded">
                  Run the analysis to see unblockers, the critical chain, skill coverage and outage causes.
                </Empty>
              ) : (
                <>
                  {cpath && (
                    <Card title="Critical path" sub="Earliest-start model over the precedence graph">
                      <div className="crit-summary">
                        <div>
                          <div className="stat-label">Makespan floor</div>
                          <div className="stat-value" style={{ marginTop: 6 }}>{nf(cpath.makespan_floor_hours, 1)}<small> h</small></div>
                        </div>
                        <div className="crit-summary-divider" aria-hidden="true" />
                        <div>
                          <div className="stat-label">Critical chain</div>
                          <div className="mono" style={{ marginTop: 8, color: "var(--text-2)", fontSize: 13 }}>
                            {cpath.critical_chain.length ? cpath.critical_chain.join("  →  ") : "none"}
                          </div>
                        </div>
                      </div>
                      <div className="table-wrap" style={{ border: "1px solid var(--border)", borderRadius: 10 }}>
                        <table className="table">
                          <thead>
                            <tr><th>Task</th><th className="num">Duration</th><th className="num">ES</th>
                              <th className="num">EF</th><th className="num">Slack</th><th>Status</th></tr>
                          </thead>
                          <tbody>
                            {cpath.tasks.map(t => (
                              <tr key={t.task_id}>
                                <td className="id">{t.task_id}</td>
                                <td className="num">{nf(t.duration_hours, 1)} h</td>
                                <td className="num">{nf(t.earliest_start, 1)}</td>
                                <td className="num">{nf(t.earliest_finish, 1)}</td>
                                <td className="num">{nf(t.slack, 1)}</td>
                                <td>{t.critical
                                  ? <span className="badge badge-danger">critical</span>
                                  : <span className="badge badge-neutral">float</span>}</td>
                              </tr>
                            ))}
                          </tbody>
                        </table>
                      </div>
                    </Card>
                  )}

                  <div className="grid-2">
                    <Card title="Top unblockers" sub="Tasks whose completion frees the most downstream work" flush>
                      <div className="table-wrap">
                        <table className="table">
                          <thead><tr><th>Task</th><th>Component</th><th className="num">Unblocks</th><th className="num">Weight freed</th></tr></thead>
                          <tbody>
                            {crit.map(c => (
                              <tr key={c.task_id}>
                                <td className="id">{c.task_id}</td>
                                <td>{c.component_name}</td>
                                <td className="num">{nf(c.unblocks_count)}</td>
                                <td className="num">{nf(c.unblocked_service_weight, 1)}</td>
                              </tr>
                            ))}
                          </tbody>
                        </table>
                      </div>
                    </Card>

                    <Card title="Skill coverage" sub={gaps?.verdict} flush>
                      <div className="table-wrap">
                        <table className="table">
                          <thead><tr><th>Skill</th><th className="num">Tasks</th><th className="num">Hours</th><th>Covered by</th></tr></thead>
                          <tbody>
                            {gaps?.demand.map(d => (
                              <tr key={d.required_skill}>
                                <td className="strong">{d.required_skill}</td>
                                <td className="num">{nf(d.task_count)}</td>
                                <td className="num">{nf(d.total_hours, 1)}</td>
                                <td>{d.crews_available.length
                                  ? d.crews_available.map(c => <span key={c} className="chip" style={{ marginRight: 4 }}>{c}</span>)
                                  : <span className="badge badge-danger">no crew</span>}</td>
                              </tr>
                            ))}
                          </tbody>
                        </table>
                      </div>
                    </Card>
                  </div>

                  {causes.length > 0 && (
                    <Card title="Outage causes" sub="Where the cost and service weight concentrate" flush>
                      <div className="table-wrap">
                        <table className="table">
                          <thead><tr><th>Cause</th><th className="num">Tasks</th><th className="num">Avg cost</th><th className="num">Avg weight</th></tr></thead>
                          <tbody>
                            {causes.map(c => (
                              <tr key={c.outage_cause}>
                                <td className="strong">{c.outage_cause}</td>
                                <td className="num">{nf(c.task_count)}</td>
                                <td className="num">{nf(c.avg_cost)}</td>
                                <td className="num">{nf(c.avg_weight, 2)}</td>
                              </tr>
                            ))}
                          </tbody>
                        </table>
                      </div>
                    </Card>
                  )}
                </>
              )}
            </div>
          )}

          {tab === "grid" && <GridPanel token={token} scenarios={scenarios} scenarioId={scenarioId} setScenarioId={setScenarioId} />}
          {tab === "data" && <TaskDataPanel token={token} role={session.role} scenarios={scenarios} scenarioId={scenarioId} setScenarioId={setScenarioId} />}
          {tab === "audit" && <AuditPanel token={token} role={session.role} />}
          {tab === "physics" && <PhysicsPanel token={token} />}
        </main>
      </div>

      {showPwForm && (
        <div className="overlay" onMouseDown={(e) => { if (e.target === e.currentTarget) setShowPwForm(false); }}>
          <div className="modal" role="dialog" aria-modal="true" aria-labelledby="pw-title">
            <div className="modal-head">
              <div>
                <div className="modal-title" id="pw-title">Change password</div>
                <div className="modal-sub">All other sessions are signed out after the change.</div>
              </div>
              <button className="icon-btn" onClick={() => setShowPwForm(false)} aria-label="Close">
                <IconClose size={17} />
              </button>
            </div>
            <form onSubmit={(e) => { e.preventDefault(); if (!pwBusy) changePassword(); }}>
              <div className="modal-body">
                <Field label="Current password">
                  <input className="input" type="password" value={oldPw} autoComplete="current-password"
                    onChange={(e) => setOldPw(e.target.value)} autoFocus />
                </Field>
                <Field label="New password" hint="At least 6 characters.">
                  <input className="input" type="password" value={newPw} autoComplete="new-password"
                    onChange={(e) => setNewPw(e.target.value)} />
                </Field>
                {pwError && <Alert kind="danger">{pwError}</Alert>}
              </div>
              <div className="modal-foot">
                <button type="button" className="btn btn-secondary" onClick={() => setShowPwForm(false)}>Cancel</button>
                <button type="submit" className="btn btn-primary" disabled={pwBusy || !oldPw || !newPw}>
                  {pwBusy ? <><span className="spinner" /> Updating…</> : "Update password"}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {toast && (
        <div className={`toast toast-${toast.kind}`} role="status" aria-live="polite">
          {toast.kind === "success" ? <IconCheck size={17} /> : toast.kind === "error" ? <IconAlert size={17} /> : null}
          <span>{toast.text}</span>
          <button className="icon-btn" style={{ width: 26, height: 26 }} onClick={() => setToast(null)} aria-label="Dismiss">
            <IconClose size={14} />
          </button>
        </div>
      )}
    </div>
  );
}

/* ------------------------------------------------------------------ gantt */

function Gantt({ actions, makespan }: { actions: { task_id: string; crew_id?: string; crew_label?: string; start_hour: number | string; finish_hour: number | string }[]; makespan: number }) {
  const span = makespan > 0 ? makespan : Math.max(1, ...actions.map(a => Number(a.finish_hour)));
  const crewIndex = (label?: string) => {
    const match = /C(\d)/.exec(label ?? "");
    return match ? Math.max(0, Number(match[1]) - 1) : 0;
  };
  return (
    <div>
      <div className="gantt">
        {actions.map(a => {
          const start = Number(a.start_hour);
          const finish = Number(a.finish_hour);
          const left = (start / span) * 100;
          const width = Math.max(1.5, ((finish - start) / span) * 100);
          const crew = a.crew_id ?? a.crew_label ?? "";
          return (
            <div className="gantt-row" key={a.task_id}>
              <span className="gantt-label">{a.task_id}</span>
              <div className="gantt-track">
                <div className={`gantt-bar c${crewIndex(crew) % 4}`}
                  style={{ left: `${left}%`, width: `${width}%` }}
                  title={`${a.task_id} · ${crew} · ${nf(start, 1)}h → ${nf(finish, 1)}h`}>
                  {crew}
                </div>
              </div>
            </div>
          );
        })}
      </div>
      <div className="gantt-axis"><span>0 h</span><span>{nf(span, 1)} h</span></div>
    </div>
  );
}
