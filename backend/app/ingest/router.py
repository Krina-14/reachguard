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

import concurrent.futures
import json
import logging
import shutil
import uuid
from collections.abc import Callable
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
from fastapi.responses import JSONResponse
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

PIPELINE_TIMEOUT_SECONDS = 600  # 10 minutes overall pipeline timeout


# ── Schemas ────────────────────────────────────────────────────────


class GitRepoRequest(BaseModel):
    git_url: str


class RepoActionResponse(BaseModel):
    repo_id: str
    status: str


# ── Helpers ────────────────────────────────────────────────────────


def normalize_git_url(url: str) -> str:
    """Normalize a GitHub repository URL to canonical https://github.com/<owner>/<repo>."""
    owner, repo = validate_git_url(url)
    return f"https://github.com/{owner}/{repo}"


def _count_user_active_repos(user_id: str, email: str | None = None) -> int:
    """Return count of repositories currently being analyzed by this user.

    Enforces contract rule: reject with 429 when the same user already has
    2 repos not in ready/failed.
    """
    g = meta_graph()
    cypher = """
    MATCH (r:Repo)
    WHERE (r.created_by = $user_id OR ($email <> '' AND r.created_by = $email))
      AND NOT (r.status IN ['ready', 'failed'])
    RETURN count(r) AS active_count
    """
    params = {"user_id": user_id, "email": email or ""}
    print(f"[REPOS QUERY] _count_user_active_repos cypher: {cypher.strip()} params: {params}")
    rows = run(g, cypher, params=params)
    count = int(rows[0].get("active_count", 0)) if rows else 0
    print(f"[REPOS QUERY] _count_user_active_repos result: {count}")
    return count


def _find_duplicate_repo(user_id: str, email: str | None, git_url: str) -> tuple[str, str] | None:
    """Check if the user already has a duplicate repo:

    - Status in ('queued', 'cloning', 'parsing', 'scanning') -> return (repo_id, status)
    - Status == 'ready' and created_at < 10 minutes ago -> return (repo_id, 'ready')
    Otherwise None.
    """
    norm_url = normalize_git_url(git_url)
    norm_git_url = f"{norm_url}.git"
    raw_url = git_url.strip()

    g = meta_graph()
    cypher = """
    MATCH (r:Repo)
    WHERE (r.created_by = $user_id OR ($email <> '' AND r.created_by = $email))
      AND (toLower(r.source) = toLower($norm_url)
           OR toLower(r.source) = toLower($norm_git_url)
           OR toLower(r.source) = toLower($raw_url))
    RETURN r.id AS id, r.status AS status, r.created_at AS created_at
    ORDER BY r.created_at DESC
    """
    params = {
        "user_id": user_id,
        "email": email or "",
        "norm_url": norm_url,
        "norm_git_url": norm_git_url,
        "raw_url": raw_url,
    }
    rows = run(g, cypher, params=params)
    now = datetime.now(UTC)

    for r in rows:
        st = r.get("status")
        if st in ("queued", "cloning", "parsing", "scanning"):
            return r["id"], st
        if st == "ready":
            cat_str = r.get("created_at")
            if cat_str:
                try:
                    cat_dt = datetime.fromisoformat(cat_str)
                    if cat_dt.tzinfo is None:
                        cat_dt = cat_dt.replace(tzinfo=UTC)
                    age_seconds = (now - cat_dt).total_seconds()
                    if 0 <= age_seconds < 600:  # younger than 10 minutes
                        return r["id"], "ready"
                except Exception:
                    pass
    return None


def reap_stale_repos(max_age_minutes: int = 15) -> int:
    """Startup reaper: in lifespan, mark every repo in queued/cloning/parsing/scanning
    older than 15 minutes as failed with error:
    'Interrupted (server restarted or job timed out)'.
    """
    g = meta_graph()
    cypher = """
    MATCH (r:Repo)
    WHERE r.status IN ['queued', 'cloning', 'parsing', 'scanning']
    RETURN r.id AS id, r.status AS status, r.created_at AS created_at
    """
    rows = run(g, cypher)
    now = datetime.now(UTC)
    reaped_count = 0
    cutoff_seconds = max_age_minutes * 60

    for r in rows:
        repo_id = r["id"]
        cat_str = r.get("created_at")
        should_reap = False

        if not cat_str:
            should_reap = True
        else:
            try:
                cat_dt = datetime.fromisoformat(cat_str)
                if cat_dt.tzinfo is None:
                    cat_dt = cat_dt.replace(tzinfo=UTC)
                age = (now - cat_dt).total_seconds()
                if age >= cutoff_seconds:
                    should_reap = True
            except Exception:
                should_reap = True

        if should_reap:
            update_cypher = """
            MATCH (r:Repo {id: $id})
            SET r.status = 'failed',
                r.stage_detail = null,
                r.error = 'Interrupted (server restarted or job timed out)'
            """
            run(g, update_cypher, params={"id": repo_id})
            reaped_count += 1
            logger.info("Startup reaper: marked repo %s as failed (age was > %d min)", repo_id, max_age_minutes)

    return reaped_count


# ── Background Pipeline Workers ────────────────────────────────────


def _execute_with_timeout(fn: Callable[[], None], timeout_seconds: int = PIPELINE_TIMEOUT_SECONDS) -> None:
    """Execute a callable with an overall timeout. Raises TimeoutError if exceeded."""
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(fn)
        try:
            future.result(timeout=timeout_seconds)
        except concurrent.futures.TimeoutError as exc:
            raise TimeoutError(f"Pipeline timed out after {timeout_seconds // 60} minutes") from exc


def run_git_pipeline(repo_id: str, git_url: str, timeout_seconds: int = PIPELINE_TIMEOUT_SECONDS) -> None:
    """Background worker to clone and build graph for a git repo with timeout protection."""
    dest_dir = Path(settings.WORK_DIR) / f"clone_{repo_id}"
    try:
        def _job() -> None:
            update_repo_status(repo_id, "cloning", "Cloning repository from GitHub")
            clone_repo(git_url, dest_dir)
            build_repo_graph(repo_id, dest_dir, is_git=True)

        _execute_with_timeout(_job, timeout_seconds=timeout_seconds)
    except TimeoutError as exc:
        err_msg = str(exc)
        logger.error("Git pipeline timed out for repo %s: %s", repo_id, err_msg)
        update_repo_status(repo_id, "failed", stage_detail=None, error=err_msg)
        if dest_dir.exists():
            shutil.rmtree(dest_dir, ignore_errors=True)
    except Exception as exc:  # noqa: BLE001
        err_msg = str(exc)
        logger.error("Git pipeline failed for repo %s: %s", repo_id, err_msg)
        update_repo_status(repo_id, "failed", stage_detail=None, error=err_msg)
        if dest_dir.exists():
            shutil.rmtree(dest_dir, ignore_errors=True)


def run_zip_pipeline(repo_id: str, zip_path: Path, timeout_seconds: int = PIPELINE_TIMEOUT_SECONDS) -> None:
    """Background worker to extract zip and build graph with timeout protection."""
    dest_dir = Path(settings.WORK_DIR) / f"unzip_{repo_id}"
    try:
        def _job() -> None:
            update_repo_status(repo_id, "parsing", "Extracting uploaded zip archive")
            extract_zip(zip_path, dest_dir)
            if zip_path.exists():
                zip_path.unlink(missing_ok=True)
            build_repo_graph(repo_id, dest_dir, is_git=False)

        _execute_with_timeout(_job, timeout_seconds=timeout_seconds)
    except TimeoutError as exc:
        err_msg = str(exc)
        logger.error("Zip pipeline timed out for repo %s: %s", repo_id, err_msg)
        update_repo_status(repo_id, "failed", stage_detail=None, error=err_msg)
        if zip_path.exists():
            zip_path.unlink(missing_ok=True)
        if dest_dir.exists():
            shutil.rmtree(dest_dir, ignore_errors=True)
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
) -> Any:
    """Queue a public GitHub repository for static analysis (analyst+)."""
    # 1. Strict URL validation (raises 422 if invalid)
    owner, repo_name = validate_git_url(req.git_url)
    user_id = current_user["id"]
    user_email = current_user.get("email")

    # 2. Duplicate check (return 200 with existing repo_id)
    dup = _find_duplicate_repo(user_id, user_email, req.git_url)
    if dup:
        dup_id, dup_status = dup
        logger.info("Found duplicate repo for %s: %s (status=%s)", req.git_url, dup_id, dup_status)
        return JSONResponse(
            status_code=status.HTTP_200_OK,
            content={"repo_id": dup_id, "status": dup_status},
        )

    # 3. Check concurrency limit (max 2 active per user -> 429)
    if _count_user_active_repos(user_id, user_email) >= 2:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many concurrent repository analyses. Maximum is 2.",
        )

    # 4. Source must be the GitHub URL. Never store "unknown" or "test".
    source_url = f"https://github.com/{owner}/{repo_name}"
    if source_url.lower() in ("unknown", "test"):
        raise HTTPException(status_code=422, detail="Invalid repository source")

    # 5. Create Repo node in rg_meta
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
            "source": source_url,
            "created_at": now_iso,
            "created_by": user_id,
        },
    )

    # 6. Enqueue background pipeline
    background_tasks.add_task(run_git_pipeline, repo_id, source_url)

    # 7. Audit event
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
    user_email = current_user.get("email")
    if _count_user_active_repos(user_id, user_email) >= 2:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many concurrent repository analyses. Maximum is 2.",
        )

    raw_filename = file.filename or "upload.zip"
    # File name without path
    filename = Path(raw_filename.replace("\\", "/")).name.strip()
    if not filename.lower().endswith(".zip"):
        raise HTTPException(
            status_code=422,
            detail="Uploaded file must be a .zip archive",
        )
    # Never store "unknown" or "test"
    if filename.lower() in ("unknown", "test", "unknown.zip", "test.zip") or not filename:
        filename = "upload.zip"

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
                "source": r.get("source") or "",
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
        "source": r.get("source") or "",
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
