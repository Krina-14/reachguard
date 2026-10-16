"""
ReachGuard — Findings and Graph API Router.

Endpoints per Contract Section 7:
- GET /api/repos/{repo_id}/findings (filters: verdict, status, q; pagination: limit, offset)
- GET /api/repos/{repo_id}/findings/{fid}
- GET /api/repos/{repo_id}/graph
- GET /api/repos/{repo_id}/choke-points
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.api.common import check_repo_ready
from app.deps import require_role
from app.graph import queries

require_viewer = require_role("viewer", "analyst", "admin")

findings_router = APIRouter(prefix="/api/repos/{repo_id}", tags=["findings"])


@findings_router.get("/findings")
def get_repo_findings(
    repo_id: str,
    _current_user: Annotated[dict[str, Any], Depends(require_viewer)],
    verdict: str | None = None,
    status_filter: str | None = Query(default=None, alias="status"),
    q: str | None = None,
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
) -> list[dict[str, Any]]:
    """List findings for a repository with optional filters and pagination (viewer+)."""
    check_repo_ready(repo_id)
    items = queries.list_findings(repo_id)

    # 1. Filter by verdict
    if verdict:
        items = [f for f in items if f.get("verdict") == verdict]

    # 2. Filter by status
    if status_filter:
        items = [f for f in items if f.get("status") == status_filter]

    # 3. Filter by search query q (package, vuln_id, or summary)
    if q:
        q_lower = q.lower()
        items = [
            f
            for f in items
            if q_lower in (f.get("package") or "").lower()
            or q_lower in (f.get("vuln_id") or "").lower()
            or q_lower in (f.get("summary") or "").lower()
        ]

    # 4. Pagination (limit default 100, max 500, offset)
    return items[offset : offset + limit]


@findings_router.get("/findings/{fid}")
def get_finding_detail(
    repo_id: str,
    fid: str,
    _current_user: Annotated[dict[str, Any], Depends(require_viewer)],
) -> dict[str, Any]:
    """Get single finding details with trace and score breakdown (viewer+)."""
    check_repo_ready(repo_id)
    finding = queries.get_finding(repo_id, fid)
    if not finding:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Finding '{fid}' not found in repository '{repo_id}'",
        )
    return finding


@findings_router.get("/graph")
def get_repo_graph(
    repo_id: str,
    _current_user: Annotated[dict[str, Any], Depends(require_viewer)],
    finding_id: str | None = None,
) -> dict[str, Any]:
    """Get graph nodes and edges for UI visualization (viewer+)."""
    check_repo_ready(repo_id)
    if finding_id is not None and not queries.get_finding(repo_id, finding_id):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Finding '{finding_id}' not found in repository '{repo_id}'",
        )
    return queries.subgraph(repo_id, finding_id)


@findings_router.get("/choke-points")
def get_choke_points(
    repo_id: str,
    _current_user: Annotated[dict[str, Any], Depends(require_viewer)],
) -> list[dict[str, Any]]:
    """Get top 5 choke point packages whose upgrade/removal clears the most reachable findings (viewer+)."""
    check_repo_ready(repo_id)
    return queries.choke_points(repo_id)


@findings_router.get("/critical-modules")
def get_critical_modules(
    repo_id: str,
    _current_user: Annotated[dict[str, Any], Depends(require_viewer)],
) -> list[dict[str, Any]]:
    """Get top 10 critical modules scored 0-100 (viewer+)."""
    check_repo_ready(repo_id)
    return queries.critical_modules(repo_id)
