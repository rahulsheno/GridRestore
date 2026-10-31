-- Migration 006: results of the physics study (backend/grid). Idempotent.
-- Each execution of `python -m backend.grid.physics_study` creates one physics_runs row, and all its
-- results reference that run. The REST API only reads these tables.

CREATE TABLE IF NOT EXISTS physics_runs (
  run_id BIGSERIAL PRIMARY KEY,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  created_by TEXT NOT NULL DEFAULT current_user,
  mode TEXT NOT NULL CHECK (mode IN ('full', 'quick')),
  headline_weights JSONB NOT NULL,
  plan_weights JSONB NOT NULL,
  settings JSONB NOT NULL DEFAULT '{}'::jsonb
);

CREATE TABLE IF NOT EXISTS physics_validation (
  run_id BIGINT NOT NULL REFERENCES physics_runs(run_id) ON DELETE CASCADE,
  check_name TEXT NOT NULL,
  case_name TEXT NOT NULL,
  metric TEXT NOT NULL,
  value DOUBLE PRECISION,
  PRIMARY KEY (run_id, check_name, case_name, metric)
);

CREATE TABLE IF NOT EXISTS physics_continuation (
  run_id BIGINT NOT NULL REFERENCES physics_runs(run_id) ON DELETE CASCADE,
  case_name TEXT NOT NULL,
  alpha DOUBLE PRECISION NOT NULL,
  status TEXT NOT NULL,
  max_loading DOUBLE PRECISION,
  min_vm DOUBLE PRECISION,
  PRIMARY KEY (run_id, case_name, alpha)
);

CREATE TABLE IF NOT EXISTS physics_continuation_summary (
  run_id BIGINT NOT NULL REFERENCES physics_runs(run_id) ON DELETE CASCADE,
  case_name TEXT NOT NULL,
  voltage_limit_alpha DOUBLE PRECISION,
  nose_alpha DOUBLE PRECISION,
  first_s2_alpha DOUBLE PRECISION,
  first_s3_alpha DOUBLE PRECISION,
  first_divergence_alpha DOUBLE PRECISION,
  PRIMARY KEY (run_id, case_name)
);

CREATE TABLE IF NOT EXISTS physics_fdia_summary (
  run_id BIGINT NOT NULL REFERENCES physics_runs(run_id) ON DELETE CASCADE,
  case_name TEXT NOT NULL,
  kind TEXT NOT NULL CHECK (kind IN ('dc', 'ac')),
  metrics JSONB NOT NULL,
  PRIMARY KEY (run_id, case_name, kind)
);

CREATE TABLE IF NOT EXISTS physics_fdia_trials (
  run_id BIGINT NOT NULL REFERENCES physics_runs(run_id) ON DELETE CASCADE,
  case_name TEXT NOT NULL,
  trial INTEGER NOT NULL,
  j_clean DOUBLE PRECISION,
  clean_alarm BOOLEAN,
  stealthy_feasible BOOLEAN,
  stealthy_bypass BOOLEAN,
  j_random DOUBLE PRECISION,
  random_detected BOOLEAN,
  PRIMARY KEY (run_id, case_name, trial)
);

CREATE TABLE IF NOT EXISTS physics_mdp_policy (
  run_id BIGINT NOT NULL REFERENCES physics_runs(run_id) ON DELETE CASCADE,
  case_name TEXT NOT NULL,
  stress_vector TEXT NOT NULL,
  weight_set TEXT NOT NULL CHECK (weight_set IN ('headline', 'plan')),
  state TEXT NOT NULL,
  loading_target DOUBLE PRECISION,
  min_vm DOUBLE PRECISION,
  v_star DOUBLE PRECISION,
  optimal_action TEXT NOT NULL,
  lambda_v DOUBLE PRECISION,
  isolated_bus INTEGER,
  PRIMARY KEY (run_id, case_name, stress_vector, weight_set, state)
);

CREATE TABLE IF NOT EXISTS physics_mdp_transitions (
  run_id BIGINT NOT NULL REFERENCES physics_runs(run_id) ON DELETE CASCADE,
  case_name TEXT NOT NULL,
  stress_vector TEXT NOT NULL,
  collapse_model TEXT NOT NULL CHECK (collapse_model IN ('voltage', 'loading')),
  action TEXT NOT NULL,
  p_s3_given_s2 DOUBLE PRECISION,
  p_s1_given_s0 DOUBLE PRECISION,
  p_s2_given_s1 DOUBLE PRECISION,
  PRIMARY KEY (run_id, case_name, stress_vector, collapse_model, action)
);

CREATE TABLE IF NOT EXISTS physics_sensitivity (
  run_id BIGINT NOT NULL REFERENCES physics_runs(run_id) ON DELETE CASCADE,
  sweep TEXT NOT NULL,
  k DOUBLE PRECISION NOT NULL,
  lambda0 DOUBLE PRECISION NOT NULL,
  w1 DOUBLE PRECISION NOT NULL,
  w3 DOUBLE PRECISION NOT NULL,
  k_voltage DOUBLE PRECISION NOT NULL,
  v_star_s0 DOUBLE PRECISION,
  action_s1 TEXT,
  action_s2 TEXT,
  non_default_states INTEGER,
  p_s3_given_s2 DOUBLE PRECISION,
  PRIMARY KEY (run_id, sweep, k, lambda0, w1, w3, k_voltage)
);

CREATE TABLE IF NOT EXISTS physics_convergence (
  run_id BIGINT NOT NULL REFERENCES physics_runs(run_id) ON DELETE CASCADE,
  case_name TEXT NOT NULL,
  stress_vector TEXT NOT NULL,
  method TEXT NOT NULL,
  step INTEGER NOT NULL,
  max_abs_change DOUBLE PRECISION,
  PRIMARY KEY (run_id, case_name, stress_vector, method, step)
);

CREATE TABLE IF NOT EXISTS physics_figures (
  run_id BIGINT NOT NULL REFERENCES physics_runs(run_id) ON DELETE CASCADE,
  name TEXT NOT NULL,
  content_type TEXT NOT NULL,
  data BYTEA NOT NULL,
  PRIMARY KEY (run_id, name)
);

CREATE INDEX IF NOT EXISTS idx_physics_trials_run ON physics_fdia_trials(run_id, case_name);
CREATE INDEX IF NOT EXISTS idx_physics_convergence_run ON physics_convergence(run_id, case_name, stress_vector);
