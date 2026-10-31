-- Migration 008: authentication hardening.
-- Refresh tokens (rotating, hashed at rest), password age tracking and a
-- "must change password" flag used when credentials come from a demo seed.
ALTER TABLE app_users ADD COLUMN IF NOT EXISTS password_changed_at TIMESTAMPTZ NOT NULL DEFAULT now();
ALTER TABLE app_users ADD COLUMN IF NOT EXISTS must_change_password BOOLEAN NOT NULL DEFAULT FALSE;

CREATE TABLE IF NOT EXISTS refresh_tokens (
  token_hash TEXT PRIMARY KEY,                     -- SHA-256 of the raw token, never the token itself
  username TEXT NOT NULL REFERENCES app_users(username) ON DELETE CASCADE,
  issued_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  expires_at TIMESTAMPTZ NOT NULL,
  revoked BOOLEAN NOT NULL DEFAULT FALSE
);
CREATE INDEX IF NOT EXISTS idx_refresh_user ON refresh_tokens(username);
CREATE INDEX IF NOT EXISTS idx_refresh_expiry ON refresh_tokens(expires_at);
