"""Role-based auth: bcrypt password verify + signed session tokens.

Roles: admin (create scenarios, run/save schedules) and operator (view + run only).
Secrets come from environment (SESSION_SECRET); passwords never stored in plain text.
"""
import base64
import hashlib
import hmac
import os
import time
import bcrypt
from .db import connect

SESSION_TTL_SECONDS = 12 * 3600

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

def authenticate(username: str, password: str):
    with connect() as conn:
        row = conn.execute(
            "SELECT username, password_hash, role FROM app_users WHERE username=%s",
            (username.strip(),)).fetchone()
    if not row or not verify_password(password, row["password_hash"]):
        return None
    return {"username": row["username"], "role": row["role"],
            "token": create_token(row["username"], row["role"])}

def require_role(token: str, *allowed: str):
    session = parse_token(token or "")
    if not session or session["role"] not in allowed:
        raise PermissionError("Not authorized for this action")
    return session
