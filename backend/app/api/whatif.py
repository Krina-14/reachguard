"""
ReachGuard — What-if Simulation API Router.

Endpoints per Contract Section 7:
- POST /api/repos/{repo_id}/whatif (analyst+)
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from app.api.common import check_repo_ready
from app.deps import require_role
from app.graph import queries
from app.graph.client import repo_graph, run

require_analyst = require_role("analyst", "admin")

whatif_router = APIRouter(prefix="/api/repos/{repo_id}", tags=["whatif"])


class ChangeItem(BaseModel):
    type: str
    entrypoint_id: str | None = None
    module_id: str | None = None
    package_id: str | None = None


class WhatIfRequest(BaseModel):
    finding_id: str | None = None
    changes: list[ChangeItem] = Field(default_factory=list)


@whatif_router.post("/whatif")
def simulate_whatif(
    repo_id: str,
    req: WhatIfRequest,
    _current_user: Annotated[dict[str, Any], Depends(require_analyst)],
) -> dict[str, Any]:
    """Run a what-if simulation on a temporary copy graph (analyst+).

    Validates change types and node existence (422 on unknown entrypoint/module/package ids).
    """
    check_repo_ready(repo_id)

    # Validate finding exists if finding_id is provided
    if req.finding_id is not None and not queries.get_finding(repo_id, req.finding_id):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Finding '{req.finding_id}' not found in repository '{repo_id}'",
        )

    g = repo_graph(repo_id)
    raw_changes = []

    # Validate each change item
    for idx, ch in enumerate(req.changes):
        c_type = ch.type
        if c_type == "add_auth":
            eid = ch.entrypoint_id
            if not eid:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail=f"Change[{idx}]: 'add_auth' requires 'entrypoint_id'",
                )
            # Verify entrypoint exists in repo graph
            ep_rows = run(g, "MATCH (e:Entrypoint {id: $id}) RETURN e.id as id", {"id": eid})
            if not ep_rows:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail=f"Unknown entrypoint id: '{eid}'",
                )
            raw_changes.append({"type": "add_auth", "entrypoint_id": eid})

        elif c_type == "remove_import":
            mid = ch.module_id
            pid = ch.package_id
            if not mid or not pid:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail=f"Change[{idx}]: 'remove_import' requires 'module_id' and 'package_id'",
                )
            # Verify module exists
            m_rows = run(g, "MATCH (m:Module {id: $id}) RETURN m.id as id", {"id": mid})
            if not m_rows:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail=f"Unknown module id: '{mid}'",
                )
            # Verify package exists
            p_rows = run(g, "MATCH (p:Package {id: $id}) RETURN p.id as id", {"id": pid})
            if not p_rows:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail=f"Unknown package id: '{pid}'",
                )
            raw_changes.append({"type": "remove_import", "module_id": mid, "package_id": pid})

        else:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"Unsupported change type: '{c_type}'. Supported: 'add_auth', 'remove_import'",
            )

    return queries.simulate(repo_id, req.finding_id, raw_changes)
