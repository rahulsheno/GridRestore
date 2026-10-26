"""Role-based auth: bcrypt password verify + signed session tokens.

Roles: admin (create scenarios, run/save schedules) and operator (view + run only).
Secrets come from environment (SESSION_SECRET); passwords never stored in plain text.

Hardening: short-lived signed access tokens, rotating refresh tokens stored only
as SHA-256 hashes in the database, and a password-age rule (login reports
must_change_password when the password is older than PASSWORD_MAX_AGE_DAYS).
"""
import base64
import hashlib
import hmac
import os
import secrets as _secrets
import time

import bcrypt
import psycopg

from .db import connect

SESSION_TTL_SECONDS = int(os.getenv("ACCESS_TOKEN_TTL_SECONDS", str(15 * 60)))
REFRESH_TTL_SECONDS = int(os.getenv("REFRESH_TOKEN_TTL_SECONDS", str(7 * 24 * 3600)))
PASSWORD_MAX_AGE_DAYS = int(os.getenv("PASSWORD_MAX_AGE_DAYS", "90"))

def _secret() -> str:
    secret = os.getenv("SESSION_SECRET")
    if not secret:
        raise RuntimeError("SESSION_SECRET is not set. Add a long random value to your .env file.")
    return secret

def verify_password(plain: str, hashed: str) -> bool:
    return bcrypt.checkpw(plain.encode(), hashed.encode())

def create_token(username: str, role: str) -> str:
    payload = f"{username}:{role}:{int(time.time())}"
    sig = hmac.new(_secret().encode(), payload.encode(), hashlib.sha256).hexdigest()
    return base64.urlsafe_b64encode(f"{payload}:{sig}".encode()).decode()

def parse_token(token: str):
    try:
        raw = base64.urlsafe_b64decode(token.encode()).decode()
        username, role, issued, sig = raw.split(":")
        payload = f"{username}:{role}:{issued}"
        expect = hmac.new(_secret().encode(), payload.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(expect, sig):
            return None
        if time.time() - int(issued) > SESSION_TTL_SECONDS:
            return None
        if role not in ("admin", "operator"):
            return None
        return {"username": username, "role": role}
    except Exception:
        return None

def _refresh_hash(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()

def issue_refresh(username: str) -> tuple[str, str]:
    """Create a refresh token for the user. Returns (raw_token, expires_iso)."""
    raw = _secrets.token_urlsafe(48)
    expires = time.time() + REFRESH_TTL_SECONDS
    with connect() as conn:
        conn.execute(
            "INSERT INTO refresh_tokens (token_hash, username, expires_at) "
            "VALUES (%s, %s, now() + %s * interval '1 second')",
            (_refresh_hash(raw), username, REFRESH_TTL_SECONDS))
    return raw, time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(expires))

def _load_refresh(raw: str):
    with connect() as conn:
        return conn.execute(
            "SELECT token_hash, username, revoked, expires_at, issued_at "
            "FROM refresh_tokens WHERE token_hash=%s", (_refresh_hash(raw),)).fetchone()

def rotate_refresh(raw: str):
    """Validate a refresh token, revoke it and return a new (username, role, new_raw,
    new_expires) payload, or None when invalid/expired/revoked."""
    with connect() as conn:
        row = conn.execute(
            "UPDATE refresh_tokens SET revoked=TRUE "
            "WHERE token_hash=%s AND revoked=FALSE AND expires_at > now() "
            "RETURNING username", (_refresh_hash(raw),)).fetchone()
    if row is None:
        return None
    user = conn_user_role(row["username"])
    if user is None:
        return None
    username, role = user
    new_raw, new_expires = issue_refresh(username)
    return {"username": username, "role": role, "refresh_token": new_raw, "refresh_expires": new_expires}

def revoke_refresh(raw: str) -> None:
    row = _load_refresh(raw)
    if row and not row["revoked"]:
        with connect() as conn:
            conn.execute("UPDATE refresh_tokens SET revoked=TRUE WHERE token_hash=%s", (row["token_hash"],))

def conn_user_role(username: str):
    with connect() as conn:
        row = conn.execute("SELECT username, role FROM app_users WHERE username=%s", (username,)).fetchone()
    return (row["username"], row["role"]) if row else None

def _utcnow() -> str:
    return time.strftime("%Y-%m-%d %H:%M:%SZ", time.gmtime())

def hash_password(plain: str) -> str:
    return bcrypt.hashpw(plain.encode(), bcrypt.gensalt(12)).decode()

def authenticate(username: str, password: str):
    with connect() as conn:
        row = conn.execute(
            "SELECT username, password_hash, role, password_changed_at, must_change_password "
            "FROM app_users WHERE username=%s", (username.strip(),)).fetchone()
    if not row or not verify_password(password, row["password_hash"]):
        return None
    age_days, must = _password_state(row)
    token = create_token(row["username"], row["role"])
    refresh_raw, refresh_expires = issue_refresh(row["username"])
    return {"username": row["username"], "role": row["role"], "token": token,
            "expires_in": SESSION_TTL_SECONDS, "refresh_token": refresh_raw,
            "refresh_expires": refresh_expires, "password_age_days": age_days,
            "must_change_password": must}

def _password_state(row) -> tuple[int, bool]:
    changed = row.get("password_changed_at")
    forced = bool(row.get("must_change_password"))
    if changed is None:
        return 0, forced
    try:
        import datetime as _dt
        changed_s = str(changed).replace("+00:00", "Z").split(".")[0]
        changed_dt = _dt.datetime.fromisoformat(changed_s.replace("Z", "+00:00"))
        age_days = (changed_dt and (_dt.datetime.now(_dt.timezone.utc) - changed_dt).days) or 0
    except Exception:
        age_days = 0
    return int(age_days), forced or age_days >= PASSWORD_MAX_AGE_DAYS

def change_password(username: str, old_password: str, new_password: str):
    """Rotate the password. Returns a new session payload, or None when the old
    password is wrong or the new one is too weak (all refresh tokens are revoked)."""
    if len(new_password) < 6:
        return None
    old_role = conn_user_role(username)
    if not old_role or not old_password or old_password == new_password:
        return None
    with connect() as conn:
        row = conn.execute("SELECT password_hash FROM app_users WHERE username=%s",
                           (username,)).fetchone()
    if not row or not verify_password(old_password, row["password_hash"]):
        return None
    with connect() as conn:
        conn.execute(
            "UPDATE app_users SET password_hash=%s, password_changed_at=now(), must_change_password=FALSE "
            "WHERE username=%s", (hash_password(new_password), username))
        conn.execute("UPDATE refresh_tokens SET revoked=TRUE WHERE username=%s AND revoked=FALSE", (username,))
    role = old_role[1]
    token = create_token(username, role)
    refresh_raw, refresh_expires = issue_refresh(username)
    return {"username": username, "role": role, "token": token,
            "expires_in": SESSION_TTL_SECONDS, "refresh_token": refresh_raw,
            "refresh_expires": refresh_expires}

def create_user(username: str, password: str):
    """Sign up a new user. New self-registered users are always operators;
    admins are only created through the seeded migration, never via sign-up."""
    username = username.strip()
    if not 3 <= len(username) <= 50:
        return None
    if len(password) < 6:
        return None
    try:
        with connect() as conn:
            row = conn.execute(
                "INSERT INTO app_users (username, password_hash, role) "
                "VALUES (%s, %s, 'operator') RETURNING username, role",
                (username, hash_password(password))).fetchone()
    except Exception as exc:
        if isinstance(exc, psycopg.errors.UniqueViolation):
            return None
        raise
    return {"username": row["username"], "role": row["role"]}

def require_role(token: str, *allowed: str):
    session = parse_token(token or "")
    if not session or session["role"] not in allowed:
        raise PermissionError("Not authorized for this action")
    return session
