// S1-04 TypeScript contract layer — single source of truth for API shapes.
// Mirrors backend/api.py Pydantic models + scheduler/criticality outputs.
export type Role = "admin" | "operator";
export type Strategy = "priority_first" | "shortest_repair_first" | "gridrestore_score";
export type SearchMode = "vector" | "fts";

export interface Session { username: string; role: Role; token: string; }
export interface Scenario { scenario_id: number; scenario_name: string; budget: number | string; crew_count: number; created_at?: string; }
export interface CrewSpec { crew_id: string; skill: string; }
export interface ScheduleAction { task_id: string; crew_id: string; start_hour: number; finish_hour: number; duration_hours?: number; estimated_cost: number; service_weight: number; }
export interface ScheduleResult { run_id: number; strategy: Strategy | string; total_cost: number; makespan_hours: number; weighted_recovery_score: number; scheduled_count: number; actions: ScheduleAction[]; unscheduled_task_ids: string[]; }
export interface RunSummary { run_id: number; scenario_id: number; scenario_name: string; strategy_name: string; total_cost: number | string; makespan_hours: number | string; weighted_recovery_score: number | string; started_at?: string; }
export interface RunAction { task_id: string; crew_label: string; start_hour: number | string; finish_hour: number | string; }
export interface SearchHit { task_id: string; narrative: string; distance?: number; rank?: number; }
export interface CriticalRepair { task_id: string; component_name: string; service_weight: number | string; priority: number; unblocks_count: number; unblocked_service_weight: number; }
export interface CpmTask { task_id: string; duration_hours: number; earliest_start: number; earliest_finish: number; latest_start: number; latest_finish: number; slack: number; critical: boolean; }
export interface CriticalPath { makespan_floor_hours: number; critical_chain: string[]; tasks: CpmTask[]; }
export interface SkillDemand { required_skill: string; task_count: number; total_hours: number; total_weight: number; covered: boolean; crews_available: string[]; }
export interface SkillGaps { scenario_id: number; roster: CrewSpec[]; demand: SkillDemand[]; gaps: string[]; verdict: string; }
export interface CauseRow { outage_cause: string; task_count: number; avg_cost: number; avg_weight: number; }
export interface ApiError { detail: string; }
