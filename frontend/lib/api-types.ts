// S1-04 TypeScript contract layer — single source of truth for API shapes.
// Mirrors backend/api.py Pydantic models + scheduler/criticality outputs.
export type Role = "admin" | "operator";
export type Strategy = "priority_first" | "shortest_repair_first" | "gridrestore_score";
export type SearchMode = "vector" | "fts";

export interface Session { username: string; role: Role; token: string;
  refresh_token?: string; refresh_expires?: string; expires_in?: number;
  must_change_password?: boolean; password_age_days?: number; }
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

// Grid map, audit history, CSV import/export and validation results (added with migration 005 and the v2 API).
export type EdgeStatus = "blocked" | "unscheduled" | "restored" | "clear";
export interface GridNode { node_id: string; node_name: string; node_type: string; criticality: number | string; region_code: string; }
export interface GridEdge { edge_id: string; from_node_id: string; to_node_id: string; component_type: string; status: EdgeStatus; }
export interface GridView { scenario_id: number; latest_run_id: number | null; nodes: GridNode[]; edges: GridEdge[]; task_status: Record<string, string>; blocked_task_ids: string[]; }
export interface AuditItem { audit_id: number; table_name: string; operation: string; row_key: string | null; changed_at: string; db_user: string; app_user: string | null; }
export interface AuditPage { total: number; limit: number; offset: number; items: AuditItem[]; }
export interface RowError { row: number; column: string; message: string; }
export interface ImportResult { valid: boolean; errors: RowError[]; committed: boolean; version_no: number | null; inserted?: number; message?: string; }

// Physics study results (read-only endpoints under /api/physics).
export interface PhysicsWeights { w1: number; w2: number; w3: number; }
export interface PhysicsRun { run_id: number; created_at: string; created_by: string; mode: string; headline_weights: PhysicsWeights; plan_weights: PhysicsWeights; }
export interface PhysicsValidationRow { check_name: string; case_name: string; metric: string; value: number | null; }
export interface PhysicsContinuationSummary { case_name: string; voltage_limit_alpha: number | null; nose_alpha: number | null; first_s2_alpha: number | null; first_s3_alpha: number | null; first_divergence_alpha: number | null; voltage_limit_alpha_free_q: number | null; nose_alpha_free_q: number | null; }
export interface PhysicsFdiaSummary { case_name: string; kind: "dc" | "ac"; metrics: Record<string, number | boolean | string | string[] | null>; }
export interface PhysicsPolicyRow { case_name?: string; stress_vector: string; weight_set: "headline" | "plan"; state: string; loading_target: number | null; min_vm: number | null; v_star: number | null; optimal_action: string; lambda_v?: number | null; isolated_bus?: number | null; }
export interface PhysicsOverview { run: PhysicsRun; validation: PhysicsValidationRow[]; continuation_summary: PhysicsContinuationSummary[]; fdia: PhysicsFdiaSummary[]; mdp_policy: PhysicsPolicyRow[]; figures: string[]; }
export interface PhysicsCurvePoint { alpha: number; status: string; max_loading: number | null; min_vm: number | null; }
export interface PhysicsTransition { stress_vector: string; collapse_model: "voltage" | "loading"; action: string; p_s3_given_s2: number | null; p_s1_given_s0: number | null; p_s2_given_s1: number | null; }
export interface PhysicsMdpDetail { policy: PhysicsPolicyRow[]; transitions: PhysicsTransition[]; }
export interface PhysicsFigure { name: string; content_type: string; data_base64: string; }
