-- Migration 010: the bridge between the scheduling half and the physics half.
-- Maps every synthetic grid edge to an IEEE-case element and a physics-derived
-- "voltage risk" score. Populated deterministically (see backend/physics_map.py);
-- the physics study's continuation results, when loaded, refine the scores.
CREATE TABLE IF NOT EXISTS element_physics_map (
  edge_id TEXT PRIMARY KEY REFERENCES grid_edges(edge_id) ON DELETE CASCADE,
  case_name TEXT NOT NULL CHECK (case_name IN ('case9','case14','case30','case57','case118')),
  element_type TEXT NOT NULL CHECK (element_type IN ('line','bus')),
  element_index INT NOT NULL CHECK (element_index >= 0),
  voltage_risk NUMERIC(8,4) NOT NULL CHECK (voltage_risk >= 0),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_epm_case ON element_physics_map(case_name);
