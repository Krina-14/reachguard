"""
ReachGuard — Decisions and Memory API Router.

Endpoints per Contract Section 7:
- POST /api/repos/{repo_id}/findings/{fid}/decisions (analyst+)
- POST /api/repos/{repo_id}/decisions/{did}/approve (admin)
- POST /api/repos/{repo_id}/decisions/{did}/reject (admin)
- GET  /api/repos/{repo_id}/memory (viewer+)
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from app.api.common import check_repo_ready
from app.deps import require_role
from app.graph import queries
from app.graph.audit import write_audit_event

require_viewer = require_role("viewer", "analyst", "admin")
require_analyst = require_role("analyst", "admin")
require_admin = require_role("admin")

memory_router = APIRouter(prefix="/api/repos/{repo_id}", tags=["memory"])

_VALID_DECISION_TYPES = {"accept_risk", "fix_planned", "false_positive", "fixed"}


class CreateDecisionRequest(BaseModel):
    type: str
    reason: str = Field(min_length=10)
    expires_at: str | None = None


@memory_router.post("/findings/{fid}/decisions", status_code=status.HTTP_200_OK)
def add_decision(
    repo_id: str,
    fid: str,
    req: CreateDecisionRequest,
    current_user: Annotated[dict[str, Any], Depends(require_analyst)],
) -> dict[str, Any]:
    """Create a decision on a finding (analyst+).

    accept_risk starts pending; other types start approved.
    """
    check_repo_ready(repo_id)

    # Validate finding exists
    if not queries.get_finding(repo_id, fid):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Finding '{fid}' not found in repository '{repo_id}'",
        )

    # Validate decision type
    if req.type not in _VALID_DECISION_TYPES:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Invalid decision type: '{req.type}'. Must be one of {_VALID_DECISION_TYPES}",
        )

    user_email = current_user.get("email", current_user.get("id", "analyst"))
    dec = queries.create_decision(
        repo_id=repo_id,
        finding_id=fid,
        by=user_email,
        type=req.type,
        reason=req.reason,
        expires_at=req.expires_at,
    )

    # Audit event
    write_audit_event(user_email, "create_decision", f"{repo_id}:{fid}:{dec['id']}")

    return dec


@memory_router.post("/decisions/{did}/approve", status_code=status.HTTP_200_OK)
def approve_decision(
    repo_id: str,
    did: str,
    current_user: Annotated[dict[str, Any], Depends(require_admin)],
) -> dict[str, Any]:
    """Approve a pending decision (admin only)."""
    check_repo_ready(repo_id)
    user_email = current_user.get("email", current_user.get("id", "admin"))

    try:
        updated = queries.set_decision_status(
            repo_id=repo_id,
            decision_id=did,
            status="approved",
            by=user_email,
        )
    except ValueError as exc:
        msg = str(exc)
        if "not found" in msg.lower():
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=msg,
            ) from exc
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=msg,
        ) from exc

    # Audit event
    write_audit_event(user_email, "approve_decision", f"{repo_id}:{did}")
    return updated


@memory_router.post("/decisions/{did}/reject", status_code=status.HTTP_200_OK)
def reject_decision(
    repo_id: str,
    did: str,
    current_user: Annotated[dict[str, Any], Depends(require_admin)],
) -> dict[str, Any]:
    """Reject a pending decision (admin only)."""
    check_repo_ready(repo_id)
    user_email = current_user.get("email", current_user.get("id", "admin"))

    try:
        updated = queries.set_decision_status(
            repo_id=repo_id,
            decision_id=did,
            status="rejected",
            by=user_email,
        )
    except ValueError as exc:
        msg = str(exc)
        if "not found" in msg.lower():
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=msg,
            ) from exc
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=msg,
        ) from exc

    # Audit event
    write_audit_event(user_email, "reject_decision", f"{repo_id}:{did}")
    return updated


@memory_router.get("/memory")
def get_memory(
    repo_id: str,
    _current_user: Annotated[dict[str, Any], Depends(require_viewer)],
    finding_id: str | None = None,
) -> dict[str, Any]:
    """Get investigation and decision memory (viewer+)."""
    check_repo_ready(repo_id)
    if finding_id is not None and not queries.get_finding(repo_id, finding_id):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Finding '{finding_id}' not found in repository '{repo_id}'",
        )
    return queries.recall(repo_id, finding_id)
