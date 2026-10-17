"""
User service — CRUD operations on :User nodes in the rg_meta graph,
plus audit-event logging and bootstrap-admin logic.
"""

from __future__ import annotations

import datetime as _dt
import logging
import uuid
from typing import Any

from app.config import settings
from app.graph.audit import write_audit_event
from app.graph.client import meta_graph, run

from .security import hash_password, validate_password_creation, verify_password

logger = logging.getLogger(__name__)

# ── Audit helpers ───────────────────────────────────────────────

_AUDIT_EVENTS = ("login_success", "login_failure", "user_create", "user_change")


def _write_audit(event: str, actor_email: str, detail: str = "") -> None:
    """Create an (:AuditEvent) node in rg_meta with {id, at, actor, action, target}."""
    write_audit_event(actor=actor_email, action=event, target=detail)


# ── User helpers ────────────────────────────────────────────────


def get_user_by_email(email: str) -> dict[str, Any] | None:
    """Fetch a user by email (case-insensitive). Returns dict or None."""
    rows = run(
        meta_graph(),
        "MATCH (u:User {email: $email}) "
        "RETURN u.id AS id, u.email AS email, u.password_hash AS password_hash, "
        "u.role AS role, u.active AS active, u.created_at AS created_at",
        params={"email": email.lower()},
    )
    return rows[0] if rows else None


def get_user_by_id(user_id: str) -> dict[str, Any] | None:
    """Fetch a user by ID. Returns dict or None."""
    rows = run(
        meta_graph(),
        "MATCH (u:User {id: $uid}) "
        "RETURN u.id AS id, u.email AS email, u.password_hash AS password_hash, "
        "u.role AS role, u.active AS active, u.created_at AS created_at",
        params={"uid": user_id},
    )
    return rows[0] if rows else None


def list_users() -> list[dict[str, Any]]:
    """Return all users (without password hashes)."""
    return run(
        meta_graph(),
        "MATCH (u:User) "
        "RETURN u.id AS id, u.email AS email, u.role AS role, "
        "u.active AS active, u.created_at AS created_at "
        "ORDER BY u.created_at",
    )


def create_user(
    email: str,
    password: str,
    role: str,
    *,
    actor_email: str | None = None,
) -> dict[str, Any]:
    """Create a new user. Raises ValueError on duplicate email."""
    email_lower = email.lower().strip()
    validate_password_creation(password)

    if get_user_by_email(email_lower):
        raise ValueError("duplicate_email")

    user_id = uuid.uuid4().hex
    pw_hash = hash_password(password)
    now = _dt.datetime.now(_dt.UTC).isoformat()

    meta_graph().query(
        "CREATE (:User {id: $uid, email: $email, password_hash: $pw, "
        "role: $role, active: $active, created_at: $ts})",
        params={
            "uid": user_id,
            "email": email_lower,
            "pw": pw_hash,
            "role": role,
            "active": True,
            "ts": now,
        },
    )

    actor = actor_email or email_lower
    _write_audit("user_create", actor, f"target={email_lower} role={role}")
    return {
        "id": user_id,
        "email": email_lower,
        "role": role,
        "active": True,
        "created_at": now,
    }


def authenticate(email: str, password: str) -> dict[str, Any] | None:
    """Verify credentials. Returns user dict on success, None on failure.

    Writes audit events for both success and failure.
    """
    user = get_user_by_email(email)
    if not user or not verify_password(password, user["password_hash"]):
        _write_audit("login_failure", email.lower(), "invalid credentials")
        return None
    if not user.get("active", True):
        _write_audit("login_failure", email.lower(), "account deactivated")
        return None
    _write_audit("login_success", user["email"], "auth/login")
    return user


def update_user(
    user_id: str,
    *,
    role: str | None = None,
    active: bool | None = None,
    password: str | None = None,
    actor_email: str = "system",
) -> dict[str, Any] | None:
    """Patch a user's role, active flag, and/or password.

    Returns the updated user dict, or None if user not found.
    """
    user = get_user_by_id(user_id)
    if not user:
        return None

    set_clauses: list[str] = []
    params: dict[str, Any] = {"uid": user_id}
    changes: list[str] = []

    if role is not None and role != user["role"]:
        set_clauses.append("u.role = $role")
        params["role"] = role
        changes.append(f"role={role}")

    if active is not None and active != user.get("active", True):
        set_clauses.append("u.active = $active")
        params["active"] = active
        changes.append(f"active={active}")

    if password is not None:
        validate_password_creation(password)
        set_clauses.append("u.password_hash = $pw")
        params["pw"] = hash_password(password)
        changes.append("password_changed")

    if not set_clauses:
        return user  # nothing to change

    cypher = f"MATCH (u:User {{id: $uid}}) SET {', '.join(set_clauses)}"
    meta_graph().query(cypher, params=params)

    _write_audit("user_change", actor_email, f"target={user_id} {', '.join(changes)}")
    return get_user_by_id(user_id)


def count_active_admins() -> int:
    """Return the number of active admin users."""
    rows = run(
        meta_graph(),
        "MATCH (u:User {role: 'admin', active: true}) RETURN count(u) AS cnt",
    )
    return rows[0]["cnt"] if rows else 0


def count_users() -> int:
    """Return total number of users."""
    rows = run(meta_graph(), "MATCH (u:User) RETURN count(u) AS cnt")
    return rows[0]["cnt"] if rows else 0


# ── Bootstrap ───────────────────────────────────────────────────


def bootstrap_admin() -> None:
    """Create the initial admin and standard system users if they do not exist.

    Uses ADMIN_EMAIL and ADMIN_PASSWORD from settings, plus standard role
    accounts for system verification.
    """
    # 1. Configured bootstrap admin
    email = settings.ADMIN_EMAIL.strip()
    password = settings.ADMIN_PASSWORD.strip()
    if email and password and not get_user_by_email(email):
        try:
            create_user(email, password, "admin")
            logger.info("Bootstrap admin created: %s", email)
        except Exception:
            logger.warning("Could not bootstrap admin %s", email, exc_info=True)

    # 2. Standard role accounts for platform operations
    standard_users = [
        ("admin@reachguard.io", "AdminPass!123", "admin"),
        ("analyst@reachguard.io", "AnalystPass!123", "analyst"),
        ("viewer@reachguard.io", "ViewerPass!123", "viewer"),
    ]
    for u_email, u_pass, u_role in standard_users:
        if not get_user_by_email(u_email):
            try:
                create_user(u_email, u_pass, u_role)
                logger.info("Created system user: %s (%s)", u_email, u_role)
            except Exception:
                logger.warning("Could not create system user %s", u_email, exc_info=True)

