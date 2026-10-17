"""
Password hashing (bcrypt) and JWT token management.

- Passwords over 72 bytes are rejected (bcrypt limitation).
- Minimum password length on creation: 10 characters.
- JWT: HS256 via PyJWT, claims: sub (user id), role, exp.
"""

from __future__ import annotations

import datetime as _dt
from typing import Any

import bcrypt
import jwt
from fastapi import HTTPException, status

from app.config import settings

# ── Password helpers ────────────────────────────────────────────

MIN_PASSWORD_LENGTH = 10
MAX_PASSWORD_BYTES = 72  # bcrypt hard limit


def validate_password_creation(password: str) -> None:
    """Raise 422 if *password* is too short or exceeds bcrypt's 72-byte limit."""
    if len(password) < MIN_PASSWORD_LENGTH:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Password must be at least {MIN_PASSWORD_LENGTH} characters",
        )
    if len(password.encode("utf-8")) > MAX_PASSWORD_BYTES:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Password exceeds 72 bytes (bcrypt limit)",
        )


def hash_password(password: str) -> str:
    """Hash *password* with bcrypt. Rejects passwords over 72 bytes."""
    raw = password.encode("utf-8")
    if len(raw) > MAX_PASSWORD_BYTES:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Password exceeds 72 bytes (bcrypt limit)",
        )
    return bcrypt.hashpw(raw, bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, password_hash: str) -> bool:
    """Return True if *password* matches *password_hash*."""
    return bcrypt.checkpw(
        password.encode("utf-8"),
        password_hash.encode("utf-8"),
    )


# ── JWT helpers ─────────────────────────────────────────────────

_ALGORITHM = "HS256"


def _get_secret() -> str:
    """Return JWT secret, falling back to a dev-mode default."""
    secret = settings.JWT_SECRET
    if not secret:
        # In dev mode the validator allows an empty secret
        secret = "reachguard-dev-secret-do-not-use-in-prod"
    return secret


def create_access_token(user_id: str, role: str) -> str:
    """Create a signed JWT with sub, role, and exp claims."""
    now = _dt.datetime.now(_dt.UTC)
    payload: dict[str, Any] = {
        "sub": user_id,
        "role": role,
        "exp": now + _dt.timedelta(minutes=settings.JWT_EXPIRE_MINUTES),
        "iat": now,
    }
    return jwt.encode(payload, _get_secret(), algorithm=_ALGORITHM)


def decode_access_token(token: str) -> dict[str, Any]:
    """Decode and verify a JWT. Raises 401 on expiry or tamper."""
    try:
        return jwt.decode(token, _get_secret(), algorithms=[_ALGORITHM])
    except jwt.ExpiredSignatureError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token has expired",
        ) from exc
    except jwt.InvalidTokenError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token",
        ) from exc
