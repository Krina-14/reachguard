"""
Auth & admin API routers.

- /api/auth   — login, me, change-password
- /api/admin  — user management (admin-only)
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, EmailStr, field_validator
from slowapi import Limiter
from slowapi.util import get_remote_address

from app.auth.security import create_access_token, validate_password_creation
from app.auth.service import (
    authenticate,
    count_active_admins,
    create_user,
    list_users,
    update_user,
)
from app.deps import get_current_user, require_role

# ── Rate limiter ────────────────────────────────────────────────

limiter = Limiter(key_func=get_remote_address)

# ══════════════════════════════════════════════════════════════════
# Auth router — /api/auth
# ══════════════════════════════════════════════════════════════════

auth_router = APIRouter(prefix="/api/auth", tags=["auth"])


# ── Schemas ─────────────────────────────────────────────────────


class LoginRequest(BaseModel):
    email: str
    password: str


class ChangePasswordRequest(BaseModel):
    current_password: str | None = None
    old_password: str | None = None
    new_password: str

    def get_current_password(self) -> str:
        return self.current_password or self.old_password or ""


class UserProfile(BaseModel):
    id: str
    email: str
    role: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserProfile | None = None


# ── Endpoints ───────────────────────────────────────────────────


@auth_router.post("/login", response_model=TokenResponse)
@limiter.limit("5/minute")
async def login(body: LoginRequest, request: Request) -> TokenResponse:
    """Authenticate with email + password. Returns a JWT and user profile.

    Rate-limited to 5 attempts per minute per IP.
    Error message is intentionally vague to avoid user enumeration.
    """
    user = authenticate(body.email, body.password)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password",
        )
    token = create_access_token(user["id"], user["role"])
    return TokenResponse(
        access_token=token,
        user=UserProfile(id=user["id"], email=user["email"], role=user["role"]),
    )



@auth_router.get("/me")
async def me(user: dict[str, Any] = Depends(get_current_user)) -> dict[str, Any]:
    """Return the currently authenticated user's profile."""
    return {
        "id": user["id"],
        "email": user["email"],
        "role": user["role"],
        "active": user["active"],
        "created_at": user["created_at"],
    }


@auth_router.post("/change-password", status_code=200)
async def change_password(
    body: ChangePasswordRequest,
    user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, str]:
    """Change the current user's password."""
    from app.auth.security import verify_password

    current_pw = body.get_current_password()
    if not current_pw or not verify_password(current_pw, user["password_hash"]):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Current password is incorrect",
        )
    validate_password_creation(body.new_password)
    update_user(user["id"], password=body.new_password, actor_email=user["email"])
    return {"message": "Password changed"}


# ══════════════════════════════════════════════════════════════════
# Admin router — /api/admin (admin only)
# ══════════════════════════════════════════════════════════════════

admin_router = APIRouter(
    prefix="/api/admin",
    tags=["admin"],
    dependencies=[Depends(require_role("admin"))],
)


# ── Schemas ─────────────────────────────────────────────────────

VALID_ROLES = ("viewer", "analyst", "admin")


class CreateUserRequest(BaseModel):
    email: EmailStr
    password: str
    role: str

    @field_validator("role")
    @classmethod
    def _check_role(cls, v: str) -> str:
        if v not in VALID_ROLES:
            raise ValueError(f"role must be one of {VALID_ROLES}")
        return v


class PatchUserRequest(BaseModel):
    role: str | None = None
    active: bool | None = None
    password: str | None = None

    @field_validator("role")
    @classmethod
    def _check_role(cls, v: str | None) -> str | None:
        if v is not None and v not in VALID_ROLES:
            raise ValueError(f"role must be one of {VALID_ROLES}")
        return v


# ── Endpoints ───────────────────────────────────────────────────


@admin_router.get("/users")
async def admin_list_users(
    _user: dict[str, Any] = Depends(require_role("admin")),
) -> list[dict[str, Any]]:
    """List all users (admin only)."""
    return list_users()


@admin_router.post("/users", status_code=201)
async def admin_create_user(
    body: CreateUserRequest,
    admin: dict[str, Any] = Depends(require_role("admin")),
) -> dict[str, Any]:
    """Create a new user (admin only)."""
    try:
        return create_user(body.email, body.password, body.role)
    except ValueError as exc:
        if "duplicate_email" in str(exc):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="A user with this email already exists",
            ) from exc
        raise


@admin_router.patch("/users/{user_id}")
async def admin_patch_user(
    user_id: str,
    body: PatchUserRequest,
    admin: dict[str, Any] = Depends(require_role("admin")),
) -> dict[str, Any]:
    """Update a user's role, active status, or password (admin only).

    Refuses to demote or deactivate the last active admin.
    """
    from app.auth.service import get_user_by_id

    target = get_user_by_id(user_id)
    if not target:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found",
        )

    # ── Last-admin protection ───────────────────────────────
    is_demote = body.role is not None and body.role != "admin" and target["role"] == "admin"
    is_deactivate = body.active is False and target.get("active", True) and target["role"] == "admin"

    if is_demote or is_deactivate:
        if count_active_admins() <= 1:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Cannot demote or deactivate the last active admin",
            )

    updated = update_user(
        user_id,
        role=body.role,
        active=body.active,
        password=body.password,
        actor_email=admin["email"],
    )
    if not updated:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found",
        )
    # Strip password_hash from response
    updated.pop("password_hash", None)
    return updated
