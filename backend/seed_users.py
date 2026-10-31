"""Create/rotate the admin and operator accounts from environment variables.

Demo default (admin123 / operator123) is fine for local teaching use, but the
point of this module is that no password is ever hard-coded in the repository
for non-demo use: set ADMIN_PASSWORD / OPERATOR_PASSWORD (and optionally
ADMIN_USERNAME / OPERATOR_USERNAME) in .env or the environment before running.

Usage:
    python -m backend.seed_users
"""
import os
import sys

from .auth import hash_password  # seeded passwords are bcrypt-hashed, never plain text
from .db import connect

DEMO_DEFAULTS = {"ADMIN_PASSWORD": "admin123", "OPERATOR_PASSWORD": "operator123"}


def _upsert(username: str, password: str, role: str):
    if not username or not username.strip():
        raise SystemExit(f"{role}: username is empty")
    if len(password) < 8:
        raise SystemExit(f"{role} password for '{username}' must be at least 8 characters")
    with connect() as conn:
        row = conn.execute("SELECT 1 AS ok FROM app_users WHERE username=%s", (username,)).fetchone()
        if row:
            conn.execute(
                "UPDATE app_users SET password_hash=%s, role=%s, password_changed_at=now(), "
                "must_change_password=FALSE WHERE username=%s",
                (hash_password(password), role, username))
            action = "updated"
        else:
            conn.execute(
                "INSERT INTO app_users (username, password_hash, role) VALUES (%s,%s,%s)",
                (username, hash_password(password), role))
            action = "created"
    return action


def seed_users():
    admin_user = os.getenv("ADMIN_USERNAME", "admin")
    operator_user = os.getenv("OPERATOR_USERNAME", "operator")
    admin_pw = os.getenv("ADMIN_PASSWORD", DEMO_DEFAULTS["ADMIN_PASSWORD"])
    operator_pw = os.getenv("OPERATOR_PASSWORD", DEMO_DEFAULTS["OPERATOR_PASSWORD"])
    for name, pw in (("ADMIN_PASSWORD", os.getenv("ADMIN_PASSWORD")),
                     ("OPERATOR_PASSWORD", os.getenv("OPERATOR_PASSWORD"))):
        if not pw:
            print(f"[seed_users] WARNING: {name} not set; using the demo default for local use only.",
                  file=sys.stderr)
    a = _upsert(admin_user, admin_pw, "admin")
    o = _upsert(operator_user, operator_pw, "operator")
    print(f"[seed_users] admin '{admin_user}' {a}; operator '{operator_user}' {o}")
    return {"admin": admin_user, "operator": operator_user}


if __name__ == "__main__":
    seed_users()
