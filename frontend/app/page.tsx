"use client";
import { useEffect, useState } from "react";
import { api, ApiClientError } from "../lib/api-client";
import type {
  CauseRow, CriticalPath, CriticalRepair, RunAction, RunSummary,
  ScheduleResult, Scenario, SearchHit, SearchMode, Session, SkillGaps, Strategy,
} from "../lib/api-types";

const input: React.CSSProperties = {display:"block",width:"100%",boxSizing:"border-box",padding:10,marginTop:8,border:"1px solid #c8d2dc",borderRadius:8};
const panel:React.CSSProperties={background:"white",padding:20,borderRadius:14,border:"1px solid #dce3e9"};
const DEFAULT_CREWS = [{crew_id:"C1",skill:"multi-skill"},{crew_id:"C2",skill:"general"},{crew_id:"C3",skill:"general"}];

type Tab = "scenarios" | "schedule" | "runs" | "search" | "critical";

export default function Home(){
 const [session,setSession]=useState<Session|null>(null);
 const [username,setUsername]=useState("admin"),[password,setPassword]=useState("admin123");
 const [error,setError]=useState(""),[tab,setTab]=useState<Tab>("scenarios");
 const [scenarios,setScenarios]=useState<Scenario[]>([]),[runs,setRuns]=useState<RunSummary[]>([]);
 const [actions,setActions]=useState<RunAction[]>([]),[strategies,setStrategies]=useState<Strategy[]>([]);
 const [scenarioId,setScenarioId]=useState<number>(1),[strategy,setStrategy]=useState<Strategy>("gridrestore_score");
 const [result,setResult]=useState<ScheduleResult|null>(null);
 const [query,setQuery]=useState("hospital emergency power repair"),[mode,setMode]=useState<SearchMode>("vector"),[hits,setHits]=useState<SearchHit[]>([]);
 const [crit,setCrit]=useState<CriticalRepair[]>([]),[cpath,setCpath]=useState<CriticalPath|null>(null);
 const [gaps,setGaps]=useState<SkillGaps|null>(null),[causes,setCauses]=useState<CauseRow[]>([]);
 const [name,setName]=useState("Lab scenario"),[budget,setBudget]=useState(14000),[crewCount,setCrewCount]=useState(3);
 const token = session?.token ?? "";
 function fail(e: unknown, fallback: string){
  setError(e instanceof ApiClientError ? `${fallback}: ${e.message} (${e.status})` : `${fallback}.`);
 }
 async function login(){
  setError("");
  try {
   const s = await api.login(username, password);
   setSession(s); localStorage.setItem("gr-session", JSON.stringify(s));
  } catch { setError("Invalid credentials"); }
 }
 async function load(t: string){
  const [sc,rn,st] = await Promise.all([api.scenarios(t), api.runs(t), api.strategies(t)]);
  setScenarios(sc); setRuns(rn); setStrategies(st);
  if(sc.length) setScenarioId(sc[0].scenario_id);
 }
 useEffect(()=>{const raw=localStorage.getItem("gr-session");if(raw){try{setSession(JSON.parse(raw) as Session);}catch{}}},[]);
 useEffect(()=>{if(session) load(session.token).catch(()=>{setSession(null);localStorage.removeItem("gr-session");});},[session]);
 async function createScenario(){
  try { await api.createScenario(token,{name,budget,crew_count:crewCount}); await load(token); }
  catch(e){ fail(e,"Create failed"); }
 }
 async function runSchedule(){
  setResult(null); setError("");
  try {
   const data = await api.schedule(token,{scenario_id:scenarioId,strategy,crews:DEFAULT_CREWS});
   setResult(data); await load(token);
  } catch(e){ fail(e,"Schedule failed"); }
 }
 async function showActions(runId: number){
  try { setActions(await api.runActions(token,runId)); } catch(e){ fail(e,"Load actions failed"); }
 }
 async function search(){
  try { setHits(await api.search(token,{query,mode,limit:5})); } catch(e){ fail(e,"Search failed"); }
 }
 async function loadCritical(){
  try {
   const [cr,cp,sg,cb] = await Promise.all([
    api.criticalRepairs(token,scenarioId), api.criticalPath(token,scenarioId),
    api.skillGaps(token,scenarioId), api.causeBreakdown(token,scenarioId)]);
   setCrit(cr); setCpath(cp); setGaps(sg); setCauses(cb);
  } catch(e){ fail(e,"Critical analysis failed"); }
 }
 const th={textAlign:"left" as const,borderBottom:"1px solid #dce3e9",padding:6};
 const td={padding:6};

 if(!session)return <main style={{maxWidth:460,margin:"60px auto",padding:20}}><div style={panel}>
  <p style={{color:"#496b8b",fontWeight:700,fontSize:12}}>GRIDRESTORE - LOGIN</p><h1>Sign in</h1>
  <p style={{color:"#536270"}}>Use admin/admin123 or operator/operator123.</p>
  <label>Username<input value={username} onChange={e=>setUsername(e.target.value)} style={input}/></label>
  <label>Password<input type="password" value={password} onChange={e=>setPassword(e.target.value)} style={input}/></label>
  <button onClick={login} style={{marginTop:12,background:"#163d5b",color:"white",border:0,padding:12,width:"100%",borderRadius:8,fontWeight:700}}>Sign in</button>
  {error&&<p style={{color:"#a12622"}}>{error}</p>}</div></main>;
 const tabs: Tab[] = ["scenarios","schedule","runs","search","critical"];
 return <main style={{maxWidth:1100,margin:"0 auto",padding:"32px 20px"}}>
  <header style={{display:"flex",justifyContent:"space-between",alignItems:"center"}}><div>
   <p style={{color:"#496b8b",fontWeight:700,fontSize:12}}>DBMS LAB - SYNTHETIC DATA ONLY</p>
   <h1 style={{margin:"6px 0"}}>GridRestore</h1>
   <p style={{color:"#536270"}}>Signed in as {session.username} ({session.role})</p></div>
   <button onClick={()=>{setSession(null);localStorage.removeItem("gr-session");}} style={{padding:10,borderRadius:8}}>Sign out</button></header>
  {error&&<p style={{color:"#a12622"}}>{error}</p>}
  <nav style={{display:"flex",gap:8,margin:"16px 0"}}>{tabs.map(t=>
   <button key={t} onClick={()=>setTab(t)} style={{padding:"10px 16px",borderRadius:8,border:"1px solid #c8d2dc",background:tab===t?"#163d5b":"white",color:tab===t?"white":"#163d5b",fontWeight:700}}>{t}</button>)}</nav>
  {tab==="scenarios"&&<section style={panel}><h2>Scenarios</h2>
   {session.role==="admin"&&<div style={{display:"grid",gridTemplateColumns:"repeat(auto-fit,minmax(180px,1fr))",gap:12,marginBottom:16}}>
    <label>Name<input value={name} onChange={e=>setName(e.target.value)} style={input}/></label>
    <label>Budget<input type="number" value={budget} onChange={e=>setBudget(Number(e.target.value))} style={input}/></label>
    <label>Crews<input type="number" value={crewCount} onChange={e=>setCrewCount(Number(e.target.value))} style={input}/></label>
    <button onClick={createScenario} style={{alignSelf:"end",padding:12,background:"#163d5b",color:"white",border:0,borderRadius:8}}>Create</button></div>}
   <table style={{width:"100%",borderCollapse:"collapse"}}><thead><tr>{["ID","Name","Budget","Crews"].map(h=><th key={h} style={th}>{h}</th>)}</tr></thead>
   <tbody>{scenarios.map(s=><tr key={s.scenario_id}><td style={td}>{s.scenario_id}</td><td style={td}>{s.scenario_name}</td><td style={td}>{String(s.budget)}</td><td style={td}>{s.crew_count}</td></tr>)}</tbody></table></section>}
  {tab==="schedule"&&<section style={panel}><h2>Run and save schedule</h2>
   <label>Scenario<select value={scenarioId} onChange={e=>setScenarioId(Number(e.target.value))} style={input}>{scenarios.map(s=><option key={s.scenario_id} value={s.scenario_id}>{s.scenario_id} - {s.scenario_name}</option>)}</select></label>
   <label>Strategy<select value={strategy} onChange={e=>setStrategy(e.target.value as Strategy)} style={input}>{strategies.map(s=><option key={s} value={s}>{s}</option>)}</select></label>
   <button onClick={runSchedule} style={{marginTop:12,padding:12,background:"#163d5b",color:"white",border:0,borderRadius:8}}>Run and save</button>
   {result&&<div style={{marginTop:12}}><p>Saved run {result.run_id}: {result.scheduled_count} tasks, cost {result.total_cost}</p>
    <table style={{width:"100%",borderCollapse:"collapse"}}><thead><tr>{["Task","Crew","Start","Finish"].map(h=><th key={h} style={th}>{h}</th>)}</tr></thead>
    <tbody>{result.actions.map(a=><tr key={a.task_id}><td style={td}>{a.task_id}</td><td style={td}>{a.crew_id}</td><td style={td}>{a.start_hour}h</td><td style={td}>{a.finish_hour}h</td></tr>)}</tbody></table></div>}</section>}
  {tab==="runs"&&<section style={panel}><h2>Saved runs</h2>
   <table style={{width:"100%",borderCollapse:"collapse"}}><thead><tr>{["Run","Scenario","Strategy","Cost",""].map(h=><th key={h} style={th}>{h}</th>)}</tr></thead>
   <tbody>{runs.map(r=><tr key={r.run_id}><td style={td}>{r.run_id}</td><td style={td}>{r.scenario_name}</td><td style={td}>{r.strategy_name}</td><td style={td}>{String(r.total_cost)}</td><td style={td}><button onClick={()=>showActions(r.run_id)}>Actions</button></td></tr>)}</tbody></table>
   {!!actions.length&&<table style={{width:"100%",borderCollapse:"collapse",marginTop:12}}><thead><tr>{["Task","Crew","Start","Finish"].map(h=><th key={h} style={th}>{h}</th>)}</tr></thead>
   <tbody>{actions.map((a,i)=><tr key={`${a.task_id}-${i}`}><td style={td}>{a.task_id}</td><td style={td}>{a.crew_label}</td><td style={td}>{String(a.start_hour)}h</td><td style={td}>{String(a.finish_hour)}h</td></tr>)}</tbody></table>}</section>}
  {tab==="search"&&<section style={panel}><h2>Similar repairs</h2>
   <label>Fault<input value={query} onChange={e=>setQuery(e.target.value)} style={input}/></label>
   <label>Mode<select value={mode} onChange={e=>setMode(e.target.value as SearchMode)} style={input}><option value="vector">Vector</option><option value="fts">Full-text</option></select></label>
   <button onClick={search} style={{marginTop:12,padding:12,background:"#163d5b",color:"white",border:0,borderRadius:8}}>Search</button>
   {!!hits.length&&<table style={{width:"100%",borderCollapse:"collapse",marginTop:12}}><thead><tr>{["Task","Narrative","Score"].map(h=><th key={h} style={th}>{h}</th>)}</tr></thead>
   <tbody>{hits.map(h=><tr key={h.task_id}><td style={td}>{h.task_id}</td><td style={td}>{h.narrative}</td><td style={td}>{h.distance ?? h.rank ?? ""}</td></tr>)}</tbody></table>}</section>}
  {tab==="critical"&&<section style={panel}><h2>Critical repairs</h2>
   <p style={{color:"#536270"}}>Top unblockers free the most downstream work; the critical chain sets the makespan floor.</p>
   <button onClick={loadCritical} style={{padding:12,background:"#163d5b",color:"white",border:0,borderRadius:8}}>Analyze scenario {scenarioId}</button>
   {!!crit.length&&<table style={{width:"100%",borderCollapse:"collapse",marginTop:12}}><thead><tr>{["Task","Component","Unblocks","Unblocked wt"].map(h=><th key={h} style={th}>{h}</th>)}</tr></thead>
   <tbody>{crit.map(c=><tr key={c.task_id}><td style={td}>{c.task_id}</td><td style={td}>{c.component_name}</td><td style={td}>{c.unblocks_count}</td><td style={td}>{c.unblocked_service_weight}</td></tr>)}</tbody></table>}
   {cpath&&<div style={{marginTop:12}}><p>Makespan floor: {cpath.makespan_floor_hours}h — critical chain: {cpath.critical_chain.join(" -> ")||"none"}</p>
    <table style={{width:"100%",borderCollapse:"collapse"}}><thead><tr>{["Task","ES","EF","Slack","Critical"].map(h=><th key={h} style={th}>{h}</th>)}</tr></thead>
    <tbody>{cpath.tasks.map(t=><tr key={t.task_id}><td style={td}>{t.task_id}</td><td style={td}>{t.earliest_start}h</td><td style={td}>{t.earliest_finish}h</td><td style={td}>{t.slack}h</td><td style={td}>{t.critical?"yes":""}</td></tr>)}</tbody></table></div>}
   {gaps&&<div style={{marginTop:16}}><h3>Skill coverage</h3><p>{gaps.verdict}</p>
    <table style={{width:"100%",borderCollapse:"collapse"}}><thead><tr>{["Skill","Tasks","Hours","Covered by"].map(h=><th key={h} style={th}>{h}</th>)}</tr></thead>
    <tbody>{gaps.demand.map(d=><tr key={d.required_skill}><td style={td}>{d.required_skill}</td><td style={td}>{d.task_count}</td><td style={td}>{d.total_hours}h</td><td style={td}>{d.crews_available.join(", ")||"none"}</td></tr>)}</tbody></table></div>}
   {!!causes.length&&<div style={{marginTop:16}}><h3>Outage causes</h3>
    <table style={{width:"100%",borderCollapse:"collapse"}}><thead><tr>{["Cause","Tasks","Avg cost","Avg weight"].map(h=><th key={h} style={th}>{h}</th>)}</tr></thead>
    <tbody>{causes.map(c=><tr key={c.outage_cause}><td style={td}>{c.outage_cause}</td><td style={td}>{c.task_count}</td><td style={td}>{c.avg_cost}</td><td style={td}>{c.avg_weight}</td></tr>)}</tbody></table></div>}</section>}
  <p style={{color:"#536270",fontSize:12,marginTop:16}}>Synthetic data only.</p></main>;
}