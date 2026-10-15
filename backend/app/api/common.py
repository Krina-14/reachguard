"""
Common utilities and dependency checks for ReachGuard API endpoints.
"""

from __future__ import annotations

import re
import uuid
from typing import Any

from fastapi import HTTPException, status

from app.graph.client import meta_graph, run

_UUID4_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$",
    re.IGNORECASE,
)


def validate_repo_uuid(repo_id: str) -> str:
    """Validate repo_id is a canonical UUID4 string. Raises 404 if invalid."""
    if not _UUID4_RE.match(repo_id):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Invalid repository ID format: '{repo_id}'",
        )
    try:
        parsed = uuid.UUID(repo_id, version=4)
        if str(parsed) != repo_id.lower():
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Invalid repository ID: '{repo_id}'",
            )
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Invalid repository ID: '{repo_id}'",
        ) from exc
    return repo_id


def check_repo_ready(repo_id: str) -> dict[str, Any]:
    """Check that repo exists in rg_meta and has status == 'ready'.

    Returns the repo record dict.
    Raises HTTPException(404) if not found.
    Raises HTTPException(409) if status != 'ready'.
    """
    validate_repo_uuid(repo_id)
    g = meta_graph()
    rows = run(
        g,
        "MATCH (r:Repo {id: $id}) RETURN r.id as id, r.status as status, r.source as source",
        {"id": repo_id},
    )
    if not rows:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Repository '{repo_id}' not found",
        )
    r_status = rows[0]["status"]
    if r_status != "ready":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Repository '{repo_id}' is not ready (current status: '{r_status}')",
        )
    return rows[0]
