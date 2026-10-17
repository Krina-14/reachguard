"""
ReachGuard — Repositories & Ingestion API Router.

Endpoints:
- POST   /api/repos         — Queue a git repository analysis (analyst+)
- POST   /api/repos/upload  — Upload a zip archive for analysis (analyst+)
- GET    /api/repos         — List all analyzed repositories (viewer+)
- GET    /api/repos/{id}    — Get repository details and ingestion stats (viewer+)
- DELETE /api/repos/{id}    — Delete a repository graph and metadata (admin only)
"""

from __future__ import annotations

import json
import logging
import shutil
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Any

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    File,
    HTTPException,
    Response,
    UploadFile,
    status,
)
from pydantic import BaseModel

from app.config import settings
from app.deps import require_role
from app.graph.audit import write_audit_event
from app.graph.client import (
    delete_graph_if_exists,
    meta_graph,
    repo_graph_name,
    run,
)
from app.ingest.builder import build_repo_graph, update_repo_status
from app.ingest.fetch import clone_repo, extract_zip, validate_git_url

logger = logging.getLogger(__name__)

# Role dependency singletons to satisfy linter
require_analyst = require_role("analyst", "admin")
require_viewer = require_role("viewer", "analyst", "admin")
require_admin = require_role("admin")

repos_router = APIRouter(prefix="/api/repos", tags=["repos"])


# ── Schemas ────────────────────────────────────────────────────────


class GitRepoRequest(BaseModel):
    git_url: str


class RepoActionResponse(BaseModel):
    repo_id: str
    status: str


# ── Helpers ────────────────────────────────────────────────────────


def _count_user_active_repos(user_id: str) -> int:
    """Return count of repositories currently being analyzed by this user."""
    g = meta_graph()
    cypher = """
    MATCH (r:Repo {created_by: $user_id})
    WHERE r.status IN ['queued', 'cloning', 'parsing', 'scanning']
    RETURN count(r) AS active_count
    """
    rows = run(g, cypher, params={"user_id": user_id})
    if rows:
        return int(rows[0].get("active_count", 0))
    return 0


# ── Background Pipeline Workers ────────────────────────────────────


def run_git_pipeline(repo_id: str, git_url: str) -> None:
    """Background worker to clone and build graph for a git repo."""
    dest_dir = Path(settings.WORK_DIR) / f"clone_{repo_id}"
    try:
        update_repo_status(repo_id, "cloning", "Cloning repository from GitHub")
        clone_repo(git_url, dest_dir)
        build_repo_graph(repo_id, dest_dir, is_git=True)
    except Exception as exc:  # noqa: BLE001
        err_msg = str(exc)
        logger.error("Git pipeline failed for repo %s: %s", repo_id, err_msg)
        update_repo_status(repo_id, "failed", stage_detail=None, error=err_msg)
        if dest_dir.exists():
            shutil.rmtree(dest_dir, ignore_errors=True)


def run_zip_pipeline(repo_id: str, zip_path: Path) -> None:
    """Background worker to extract zip and build graph."""
    dest_dir = Path(settings.WORK_DIR) / f"unzip_{repo_id}"
    try:
        update_repo_status(repo_id, "parsing", "Extracting uploaded zip archive")
        extract_zip(zip_path, dest_dir)
        if zip_path.exists():
            zip_path.unlink(missing_ok=True)
        build_repo_graph(repo_id, dest_dir, is_git=False)
    except Exception as exc:  # noqa: BLE001
        err_msg = str(exc)
        logger.error("Zip pipeline failed for repo %s: %s", repo_id, err_msg)
        update_repo_status(repo_id, "failed", stage_detail=None, error=err_msg)
        if zip_path.exists():
            zip_path.unlink(missing_ok=True)
        if dest_dir.exists():
            shutil.rmtree(dest_dir, ignore_errors=True)


# ── Endpoints ──────────────────────────────────────────────────────


@repos_router.post(
    "",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=RepoActionResponse,
)
def queue_git_repo(
    req: GitRepoRequest,
    background_tasks: BackgroundTasks,
    current_user: Annotated[dict[str, Any], Depends(require_analyst)],
) -> RepoActionResponse:
    """Queue a public GitHub repository for static analysis (analyst+)."""
    # 1. Strict URL validation (raises 422 if invalid)
    validate_git_url(req.git_url)

    # 2. Check concurrency limit (max 2 active per user -> 429)
    user_id = current_user["id"]
    if _count_user_active_repos(user_id) >= 2:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many concurrent repository analyses. Maximum is 2.",
        )

    # 3. Create Repo node in rg_meta
    repo_id = str(uuid.uuid4())
    now_iso = datetime.now(UTC).isoformat()

    g = meta_graph()
    cypher = """
    CREATE (r:Repo {
        id: $id,
        source: $source,
        source_type: 'git',
        status: 'queued',
        stage_detail: 'Queued for analysis',
        error: null,
        created_at: $created_at,
        created_by: $created_by,
        stats_json: null
    })
    """
    run(
        g,
        cypher,
        params={
            "id": repo_id,
            "source": req.git_url,
            "created_at": now_iso,
            "created_by": user_id,
        },
    )

    # 4. Enqueue background pipeline
    background_tasks.add_task(run_git_pipeline, repo_id, req.git_url)

    # 5. Audit event
    write_audit_event(current_user.get("email", user_id), "repo_create", repo_id)

    return RepoActionResponse(repo_id=repo_id, status="queued")


@repos_router.post(
    "/upload",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=RepoActionResponse,
)
def upload_zip_repo(
    background_tasks: BackgroundTasks,
    file: Annotated[UploadFile, File()],
    current_user: Annotated[dict[str, Any], Depends(require_analyst)],
) -> RepoActionResponse:
    """Upload a zip archive for static analysis (analyst+)."""
    user_id = current_user["id"]
    if _count_user_active_repos(user_id) >= 2:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many concurrent repository analyses. Maximum is 2.",
        )

    filename = file.filename or "upload.zip"
    if not filename.lower().endswith(".zip"):
        raise HTTPException(
            status_code=422,
            detail="Uploaded file must be a .zip archive",
        )

    repo_id = str(uuid.uuid4())
    now_iso = datetime.now(UTC).isoformat()

    # Save uploaded file to disk
    work_dir = Path(settings.WORK_DIR)
    work_dir.mkdir(parents=True, exist_ok=True)
    zip_dest = work_dir / f"upload_{repo_id}.zip"

    try:
        with open(zip_dest, "wb") as f:
            shutil.copyfileobj(file.file, f)
    except Exception as exc:
        if zip_dest.exists():
            zip_dest.unlink(missing_ok=True)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Failed to save uploaded file: {exc}",
        ) from exc

    # Create Repo node in rg_meta
    g = meta_graph()
    cypher = """
    CREATE (r:Repo {
        id: $id,
        source: $source,
        source_type: 'zip',
        status: 'queued',
        stage_detail: 'Queued for analysis',
        error: null,
        created_at: $created_at,
        created_by: $created_by,
        stats_json: null
    })
    """
    run(
        g,
        cypher,
        params={
            "id": repo_id,
            "source": filename,
            "created_at": now_iso,
            "created_by": user_id,
        },
    )

    # Enqueue background pipeline
    background_tasks.add_task(run_zip_pipeline, repo_id, zip_dest)

    # Audit event
    write_audit_event(current_user.get("email", user_id), "repo_create", repo_id)

    return RepoActionResponse(repo_id=repo_id, status="queued")


@repos_router.get("")
def list_repos(
    _current_user: Annotated[dict[str, Any], Depends(require_viewer)],
) -> list[dict[str, Any]]:
    """List all analyzed repositories with their current status and stats (viewer+)."""
    g = meta_graph()
    cypher = """
    MATCH (r:Repo)
    RETURN r.id AS id, r.source AS source, r.status AS status,
           r.created_at AS created_at, r.stats_json AS stats_json
    ORDER BY r.created_at DESC
    """
    rows = run(g, cypher)
    results: list[dict[str, Any]] = []

    for r in rows:
        stats_obj = None
        if r.get("stats_json"):
            try:
                stats_obj = json.loads(r["stats_json"])
            except (json.JSONDecodeError, TypeError):
                stats_obj = None

        results.append(
            {
                "id": r["id"],
                "source": r.get("source") or "unknown",
                "status": r.get("status") or "queued",
                "created_at": r.get("created_at") or datetime.now(UTC).isoformat(),
                "stats": stats_obj,
            }
        )
    return results


@repos_router.get("/{repo_id}")
def get_repo(
    repo_id: str,
    _current_user: Annotated[dict[str, Any], Depends(require_viewer)],
) -> dict[str, Any]:
    """Get detailed status and statistics for a specific repository (viewer+)."""
    g = meta_graph()
    cypher = """
    MATCH (r:Repo {id: $repo_id})
    RETURN r.id AS id, r.source AS source, r.status AS status,
           r.stage_detail AS stage_detail, r.error AS error,
           r.created_at AS created_at, r.stats_json AS stats_json
    """
    rows = run(g, cypher, params={"repo_id": repo_id})
    if not rows:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Repository {repo_id} not found",
        )

    r = rows[0]
    stats_obj: dict[str, Any] | None = None
    if r.get("stats_json"):
        try:
            stats_obj = json.loads(r["stats_json"])
        except (json.JSONDecodeError, TypeError):
            stats_obj = None

    return {
        "id": r["id"],
        "source": r.get("source") or "unknown",
        "status": r.get("status") or "queued",
        "stage_detail": r.get("stage_detail"),
        "error": r.get("error"),
        "created_at": r.get("created_at") or datetime.now(UTC).isoformat(),
        "stats": stats_obj,
    }



@repos_router.delete("/{repo_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_repo(
    repo_id: str,
    _current_user: Annotated[dict[str, Any], Depends(require_admin)],
) -> Response:
    """Delete a repository graph and its record in rg_meta (admin only)."""
    # 1. Drop repo graph
    try:
        rg_name = repo_graph_name(repo_id)
        delete_graph_if_exists(rg_name)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Invalid repository ID: {exc}",
        ) from exc

    # 2. Delete Repo node in rg_meta
    g = meta_graph()
    cypher = """
    MATCH (r:Repo {id: $repo_id})
    DETACH DELETE r
    """
    run(g, cypher, params={"repo_id": repo_id})

    # 3. Audit event
    write_audit_event(_current_user.get("email", "admin"), "repo_delete", repo_id)

    return Response(status_code=status.HTTP_204_NO_CONTENT)
