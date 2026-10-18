-- Migration 003: role-based auth (Admin / Operator), bcrypt-hashed passwords.
-- Passwords are NEVER stored in plain text; backend verifies via bcrypt.
CREATE TABLE IF NOT EXISTS app_users (
  user_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  username TEXT NOT NULL UNIQUE CHECK (length(trim(username)) BETWEEN 3 AND 50),
  password_hash TEXT NOT NULL,
  role TEXT NOT NULL CHECK (role IN ('admin', 'operator')),
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Seed: admin / admin123, operator / operator123 (bcrypt hashes).
INSERT INTO app_users (username, password_hash, role) VALUES
  ('admin', '$2b$12$yRS3JQLfyAgNauKHiHkIiuwLwgziSNHMD73GrRMPVZ.gvZvE1sm3q', 'admin'),
  ('operator', '$2b$12$vaQsW/KeYEUuirF/4sk4n.UYJltmMXaOwHCy56RDCAlLIJpArD6B6', 'operator')
ON CONFLICT (username) DO NOTHING;
