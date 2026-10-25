-- Migration 007: physics study extensions. Idempotent.
--   * continuation summary: the unlimited-Q comparison next to the headline (Q-limited) values
--   * FDIA summary: LNR and targeted-attack kinds
--   * sensitivity: discount factor gamma as a sweep parameter

ALTER TABLE physics_continuation_summary ADD COLUMN IF NOT EXISTS voltage_limit_alpha_free_q DOUBLE PRECISION;
ALTER TABLE physics_continuation_summary ADD COLUMN IF NOT EXISTS nose_alpha_free_q DOUBLE PRECISION;

ALTER TABLE physics_fdia_summary DROP CONSTRAINT IF EXISTS physics_fdia_summary_kind_check;
ALTER TABLE physics_fdia_summary ADD CONSTRAINT physics_fdia_summary_kind_check
  CHECK (kind IN ('dc', 'ac', 'lnr', 'targeted'));

ALTER TABLE physics_sensitivity ADD COLUMN IF NOT EXISTS gamma DOUBLE PRECISION NOT NULL DEFAULT 0.95;
DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint c JOIN pg_attribute a
      ON a.attrelid = c.conrelid AND a.attnum = ANY (c.conkey)
    WHERE c.conrelid = 'physics_sensitivity'::regclass AND c.contype = 'p' AND a.attname = 'gamma'
  ) THEN
    ALTER TABLE physics_sensitivity DROP CONSTRAINT physics_sensitivity_pkey;
    ALTER TABLE physics_sensitivity ADD PRIMARY KEY (run_id, sweep, k, lambda0, w1, w3, k_voltage, gamma);
  END IF;
END $$;
