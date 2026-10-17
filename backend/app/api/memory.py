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

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field

from app.api.common import check_repo_ready
from app.deps import require_role
from app.graph import queries
from app.graph.audit import write_audit_event
from app.graph.client import meta_graph, repo_graph, run
from app.scoring import score as score_finding

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


# ══════════════════════════════════════════════════════════════════
# Decisions router — /api/decisions (admin only)
# ══════════════════════════════════════════════════════════════════

decisions_router = APIRouter(prefix="/api/decisions", tags=["decisions"])


def _normalize_pkg_name(name: str | None) -> str:
    return (name or "").strip().lower().replace("-", "_")


@decisions_router.get("", status_code=status.HTTP_200_OK)
def list_global_decisions(
    _current_user: Annotated[dict[str, Any], Depends(require_admin)],
    status_filter: str = Query(default="pending", alias="status"),
) -> list[dict[str, Any]]:
    """Return decisions with specified status across all ready repositories (admin only).

    Contract: For every repo in ready status, return decisions with status together with
    repo_id, repo source, and finding summary {id, vuln_id, package, version, verdict, score}.
    One query per repo graph, parameterized. Cap 200 rows.
    """
    mg = meta_graph()
    ready_repos = run(
        mg,
        "MATCH (r:Repo {status: 'ready'}) RETURN r.id AS id, r.source AS source ORDER BY r.created_at DESC",
    )

    max_total = 200
    results: list[dict[str, Any]] = []

    for repo in ready_repos:
        if len(results) >= max_total:
            break
        repo_id = repo["id"]
        repo_source = repo.get("source") or ""
        remaining = max_total - len(results)

        try:
            rg = repo_graph(repo_id)
        except Exception:
            continue

        cypher = """
        MATCH (d:Decision {status: $status})<-[:HAS_DECISION]-(f:Finding)
        OPTIONAL MATCH (f)-[:ABOUT]->(v:Vulnerability)
        OPTIONAL MATCH (f)-[:ON_PACKAGE]->(p:Package)
        OPTIONAL MATCH (all_ep:Entrypoint {public: true})
        WITH d, f, v, p, count(DISTINCT all_ep) AS total_public
        OPTIONAL MATCH reach_path = (ep:Entrypoint {public: true})-[:HANDLED_BY|IMPORTS|USES|DEPENDS_ON*1..20]->(p)
        OPTIONAL MATCH (:Module)-[u:USES]->(p)
        OPTIONAL MATCH (ep_bs:Entrypoint {public: true})-[:HANDLED_BY]->(:Module)-[:IMPORTS*0..20]->(m_bs:Module)-[:HAS_BLINDSPOT]->(b:BlindSpot)
        WITH d, f, v, p, total_public,
             count(DISTINCT ep) AS reaching_eps,
             count(DISTINCT u) AS uses_count,
             collect(DISTINCT {kind: b.kind, name: b.name}) AS blind_spots
        RETURN d.id AS id,
               d.type AS type,
               d.status AS status,
               d.reason AS reason,
               d.by AS by,
               d.created_at AS created_at,
               d.expires_at AS expires_at,
               d.approved_by AS approved_by,
               f.id AS finding_id,
               v.id AS vuln_id,
               v.severity AS severity,
               p.name AS package_name,
               p.id AS package_id,
               p.version AS package_version,
               total_public,
               reaching_eps,
               uses_count,
               blind_spots
        ORDER BY d.created_at DESC
        LIMIT $limit
        """
        try:
            rows = run(rg, cypher, params={"status": status_filter, "limit": remaining})
        except Exception:
            continue

        for row in rows:
            pkg_name = row.get("package_name") or row.get("package_id") or ""
            pkg_ver = row.get("package_version") or ""
            vuln_id = row.get("vuln_id") or ""
            severity = row.get("severity") or "UNKNOWN"
            total_pub = int(row.get("total_public") or 0)
            reaching = int(row.get("reaching_eps") or 0)
            uses_cnt = int(row.get("uses_count") or 0)
            blind_spots = row.get("blind_spots") or []

            if total_pub == 0:
                verdict = "unknown"
            elif reaching > 0:
                verdict = "reachable_in_model"
            elif uses_cnt == 0:
                verdict = "no_path_found"
            else:
                has_dynamic = any(
                    isinstance(b, dict) and b.get("kind") in ("dynamic_import", "unparsed_file")
                    for b in blind_spots
                )
                unresolved_match = any(
                    isinstance(b, dict)
                    and b.get("kind") == "unresolved_import"
                    and b.get("name")
                    and _normalize_pkg_name(b["name"]) == _normalize_pkg_name(pkg_name)
                    for b in blind_spots
                )
                if has_dynamic or unresolved_match:
                    verdict = "unknown"
                else:
                    verdict = "no_path_found"

            score_res = score_finding(
                verdict=verdict,
                severity=severity,
                reaching_entrypoints=reaching,
                total_public_entrypoints=total_pub,
            )
            final_score = score_res["score"]

            finding_summary = {
                "id": row.get("finding_id") or "",
                "vuln_id": vuln_id,
                "package": pkg_name,
                "version": pkg_ver,
                "verdict": verdict,
                "score": final_score,
            }
            decision_dict = {
                "id": row.get("id") or "",
                "type": row.get("type") or "",
                "status": row.get("status") or "",
                "reason": row.get("reason") or "",
                "by": row.get("by") or "",
                "created_at": row.get("created_at") or "",
                "expires_at": row.get("expires_at"),
                "approved_by": row.get("approved_by"),
            }
            results.append({
                "repo_id": repo_id,
                "repo_source": repo_source,
                "source": repo_source,
                "finding": finding_summary,
                "decision": decision_dict,
                **decision_dict,
            })
            if len(results) >= max_total:
                break

    return results[:max_total]
