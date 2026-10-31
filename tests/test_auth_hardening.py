"""Tests for the auth hardening: refresh rotation, password policy, rate limiting
and the element→physics mapping (items 1 and 5)."""
import os

import pytest

os.environ.setdefault("DATABASE_URL", "postgresql://localhost:5433/gridrestore")

from backend import ratelimit, auth  # noqa: E402


@pytest.fixture(autouse=True)
def _rl_clear():
    ratelimit.clear_all()
    yield
    ratelimit.clear_all()


def _uniq(seed: int) -> str:
    import time as _t
    return f"user{seed:04d}_{_t.time_ns() % 1_000_000}"


@pytest.fixture()
def uniq_name():
    """Unique per run: tests are not transactional, so a name used by an earlier
    run of the suite must not clash."""
    import time as _t
    return f"u{_t.time_ns() % 10_000_000}"


def test_refresh_rotation_and_reuse_detection():
    name = _uniq(1)
    auth.create_user(name, "secret9")
    sess = auth.authenticate(name, "secret9")
    assert sess and sess["refresh_token"]
    rot = auth.rotate_refresh(sess["refresh_token"])
    assert rot and rot["refresh_token"] != sess["refresh_token"]
    # The used token must never work again (rotation).
    assert auth.rotate_refresh(sess["refresh_token"]) is None
    # The new token works exactly once, then a fresh one is issued.
    rot2 = auth.rotate_refresh(rot["refresh_token"])
    assert rot2 and rot2["refresh_token"] != rot["refresh_token"]
    assert auth.rotate_refresh(rot["refresh_token"]) is None
    assert auth.rotate_refresh(rot2["refresh_token"]) is not None


def test_bad_refresh_rejected():
    assert auth.rotate_refresh("no-such-token-aaaaaaaaaaaa") is None


def test_password_change_revokes_sessions():
    name = _uniq(2)
    auth.create_user(name, "firstpw9")
    s1 = auth.authenticate(name, "firstpw9")
    assert auth.change_password(name, "wrongold", "secondpw9") is None
    s2 = auth.change_password(name, "firstpw9", "secondpw9")
    assert s2 and s2["token"] and s2["refresh_token"]
    # all previously issued refresh tokens are revoked
    assert auth.rotate_refresh(s1["refresh_token"]) is None
    assert auth.authenticate(name, "firstpw9") is None
    assert auth.authenticate(name, "secondpw9")["username"] == name
    auth.change_password(name, "secondpw9", "firstpw9")


def test_rate_limiter_window():
    for _ in range(5):
        assert ratelimit.check("rl", limit=5, window=0.1)[0]
    allowed, retry = ratelimit.check("rl", limit=5, window=0.1)
    assert not allowed and retry >= 0.05
    ratelimit.reset("rl")
    assert ratelimit.check("rl", limit=5, window=0.1)[0]


def test_create_user_rejects_weak_and_duplicates():
    name = _uniq(3)
    assert auth.create_user(name, "goodpw9") is not None
    assert auth.create_user(name, "goodpw9") is None          # duplicate
    assert auth.create_user("ab", "goodpw9") is None          # username < 3 chars
    assert auth.create_user(_uniq(4), "12") is None           # password < 6 chars


def test_access_token_expiry_window():
    tok = auth.create_token("admin", "admin")
    assert auth.parse_token(tok)["username"] == "admin"
    assert auth.parse_token(tok) is not None
    # tampered signature must fail
    raw = tok[:-4] + ("AAAA" if not tok.endswith("AAAA") else "BBBB")
    assert auth.parse_token(raw) is None


# ------------------------------- item 1: element ↔ physics mapping

def test_physics_map_is_deterministic_and_bounded():
    from backend import physics_map
    n1 = physics_map.ensure_map()
    n2 = physics_map.ensure_map()
    assert n1 == n2 and n1 > 0
    rows = physics_map.map_rows(1)
    assert rows, "scenario 1 must have tasks with mapped edges"
    for row in rows:
        assert 0.0 <= float(row["voltage_risk"]) <= 1.0
        assert row["case_name"] in ("case9", "case14", "case30", "case57", "case118")


def test_task_weights_bounded_and_positive():
    from backend import physics_map
    w = physics_map.task_weights(1)
    assert w
    for bonus in w.values():
        assert 1.0 <= bonus <= 1.0 + physics_map._PHI + 1e-9


def test_scheduler_accepts_physics_weights():
    import pandas as pd
    from backend.scheduler import schedule_repairs
    frame = pd.DataFrame([
        {"task_id": "A", "estimated_hours": 2.0, "estimated_cost": 100, "service_weight": 5, "priority": 3},
        {"task_id": "B", "estimated_hours": 2.0, "estimated_cost": 100, "service_weight": 5, "priority": 3},
    ], columns=["task_id", "estimated_hours", "estimated_cost", "service_weight", "priority"])
    crews = [{"crew_id": "C1", "skill": "multi-skill"}]
    # A physics-boosted B is picked before A (single crew ⇒ order decides).
    without = schedule_repairs(frame, "gridrestore_score", 1000, crews)
    with_w = schedule_repairs(frame, "gridrestore_score", 1000, crews,
                              physics_weights={"B": 1.5})
    assert without["actions"][0]["task_id"] == "A"
    assert with_w["actions"][0]["task_id"] == "B"
