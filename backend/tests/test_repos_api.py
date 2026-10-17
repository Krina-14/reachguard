"""
Integration tests for /api/repos router and lifecycle job handling.

Covers:
- POST /api/repos (git url validation, 422 on bad url, 202 on valid url)
- Concurrency limit (429 when >= 2 active analyses exist for the same user; 3 quick requests test)
- Duplicates (return 200 with repo_id if in-progress or ready < 10m)
- Startup reaper (mark repos > 15m in progress as failed with "Interrupted (server restarted or job timed out)")
- Pipeline timeout (overall timeout marks repo failed)
- Repo source name (URL for git, filename without path for zip, never 'unknown' or 'test')
- POST /api/repos/upload (zip upload, 422 on non-zip)
- GET /api/repos (list repositories)
- GET /api/repos/{id} (get repository, 404 on missing)
- DELETE /api/repos/{id} (admin only, 403 for viewer/analyst, 204 for admin)
"""

import io
import time
import uuid
import zipfile
from datetime import UTC, datetime, timedelta
from unittest.mock import patch

from app.auth.security import create_access_token
from app.graph.client import meta_graph, run
from app.ingest.router import reap_stale_repos, run_git_pipeline
from app.main import app
from fastapi.testclient import TestClient

client = TestClient(app)


def _auth_headers(role: str = "analyst", user_id: str | None = None) -> dict[str, str]:
    uid = user_id or str(uuid.uuid4())
    g = meta_graph()
    run(
        g,
        """
        MERGE (u:User {id: $id})
        SET u.email = $email, u.role = $role, u.active = true,
            u.created_at = '2026-01-01T00:00:00Z', u.password_hash = 'test'
        """,
        params={"id": uid, "email": f"{uid[:8]}@example.com", "role": role},
    )
    token = create_access_token(user_id=uid, role=role)
    return {"Authorization": f"Bearer {token}"}


# ── URL Validation & Queueing ──────────────────────────────────────


def test_queue_git_repo_invalid_url_422():
    headers = _auth_headers("analyst")
    resp = client.post("/api/repos", json={"git_url": "https://evil.com/a/b"}, headers=headers)
    assert resp.status_code == 422
    assert "Invalid GitHub URL" in resp.json()["error"]["message"]


@patch("app.ingest.router.run_git_pipeline")
def test_queue_git_repo_valid_202(mock_worker):
    headers = _auth_headers("analyst")
    resp = client.post(
        "/api/repos",
        json={"git_url": "https://github.com/octocat/Hello-World"},
        headers=headers,
    )
    assert resp.status_code == 202
    data = resp.json()
    assert "repo_id" in data
    assert data["status"] == "queued"


# ── 1. Concurrency Enforcement & 3 Quick Requests Test ─────────────


@patch("app.ingest.router.run_git_pipeline")
def test_three_quick_requests_third_is_429(mock_worker):
    """Enforce contract rule: reject with 429 when the same user already has
    2 repos not in ready/failed. Create 3 distinct requests quickly and expect the 3rd to be 429.
    """
    user_id = str(uuid.uuid4())
    headers = _auth_headers("analyst", user_id=user_id)

    # 1st request
    r1 = client.post(
        "/api/repos",
        json={"git_url": "https://github.com/pallets/flask"},
        headers=headers,
    )
    assert r1.status_code == 202
    assert r1.json()["status"] == "queued"

    # 2nd request
    r2 = client.post(
        "/api/repos",
        json={"git_url": "https://github.com/psf/requests"},
        headers=headers,
    )
    assert r2.status_code == 202
    assert r2.json()["status"] == "queued"

    # 3rd request -> Must trigger 429 Too Many Requests
    r3 = client.post(
        "/api/repos",
        json={"git_url": "https://github.com/urllib3/urllib3"},
        headers=headers,
    )
    assert r3.status_code == 429
    assert "Too many concurrent" in r3.json()["error"]["message"]


def test_queue_git_repo_concurrency_limit_existing_active_429():
    user_id = str(uuid.uuid4())
    headers = _auth_headers("analyst", user_id=user_id)

    # Insert 2 active repos (not ready/failed) for this user in meta
    g = meta_graph()
    run(
        g,
        """
        CREATE (r1:Repo {id: $id1, created_by: $uid, status: 'cloning'})
        CREATE (r2:Repo {id: $id2, created_by: $uid, status: 'parsing'})
        """,
        params={"id1": str(uuid.uuid4()), "id2": str(uuid.uuid4()), "uid": user_id},
    )

    resp = client.post(
        "/api/repos",
        json={"git_url": "https://github.com/octocat/Hello-World"},
        headers=headers,
    )
    assert resp.status_code == 429
    assert "Too many concurrent" in resp.json()["error"]["message"]


# ── 2. Duplicates Handling ─────────────────────────────────────────


@patch("app.ingest.router.run_git_pipeline")
def test_duplicate_repo_in_progress_returns_200(mock_worker):
    """If the same user already has a repo with the same normalized git_url
    that is queued/cloning/parsing/scanning, return 200 with that repo_id.
    """
    user_id = str(uuid.uuid4())
    headers = _auth_headers("analyst", user_id=user_id)

    # First submission
    r1 = client.post(
        "/api/repos",
        json={"git_url": "https://github.com/encode/uvicorn"},
        headers=headers,
    )
    assert r1.status_code == 202
    orig_id = r1.json()["repo_id"]

    # Duplicate submission with trailing slash and .git
    r2 = client.post(
        "/api/repos",
        json={"git_url": "https://github.com/encode/uvicorn.git/"},
        headers=headers,
    )
    assert r2.status_code == 200
    assert r2.json()["repo_id"] == orig_id
    assert r2.json()["status"] == "queued"


def test_duplicate_repo_ready_under_10_minutes_returns_200():
    """If one is ready and younger than 10 minutes, return 200 with that repo_id."""
    user_id = str(uuid.uuid4())
    headers = _auth_headers("analyst", user_id=user_id)
    repo_id = str(uuid.uuid4())
    recent_ts = (datetime.now(UTC) - timedelta(minutes=3)).isoformat()

    g = meta_graph()
    run(
        g,
        """
        CREATE (r:Repo {
            id: $id,
            source: 'https://github.com/fastapi/fastapi',
            status: 'ready',
            created_at: $cat,
            created_by: $uid
        })
        """,
        params={"id": repo_id, "cat": recent_ts, "uid": user_id},
    )

    resp = client.post(
        "/api/repos",
        json={"git_url": "https://github.com/fastapi/fastapi"},
        headers=headers,
    )
    assert resp.status_code == 200
    assert resp.json()["repo_id"] == repo_id
    assert resp.json()["status"] == "ready"


@patch("app.ingest.router.run_git_pipeline")
def test_duplicate_repo_ready_older_than_10_minutes_creates_new_202(mock_worker):
    """If ready repo is older than 10 minutes, allow creating another (202)."""
    user_id = str(uuid.uuid4())
    headers = _auth_headers("analyst", user_id=user_id)
    old_id = str(uuid.uuid4())
    old_ts = (datetime.now(UTC) - timedelta(minutes=15)).isoformat()

    g = meta_graph()
    run(
        g,
        """
        CREATE (r:Repo {
            id: $id,
            source: 'https://github.com/tiangolo/typer',
            status: 'ready',
            created_at: $cat,
            created_by: $uid
        })
        """,
        params={"id": old_id, "cat": old_ts, "uid": user_id},
    )

    resp = client.post(
        "/api/repos",
        json={"git_url": "https://github.com/tiangolo/typer"},
        headers=headers,
    )
    assert resp.status_code == 202
    new_id = resp.json()["repo_id"]
    assert new_id != old_id


# ── 3. Startup Reaper & Pipeline Timeout ───────────────────────────


def test_startup_reaper_marks_stale_repos_as_failed():
    """Startup reaper: mark every repo in queued/cloning/parsing/scanning
    older than 15 minutes as failed with error 'Interrupted (server restarted or job timed out)'.
    """
    g = meta_graph()
    stale_id = str(uuid.uuid4())
    recent_id = str(uuid.uuid4())
    ready_id = str(uuid.uuid4())

    stale_ts = (datetime.now(UTC) - timedelta(minutes=20)).isoformat()
    recent_ts = (datetime.now(UTC) - timedelta(minutes=5)).isoformat()
    ready_ts = (datetime.now(UTC) - timedelta(minutes=30)).isoformat()

    run(
        g,
        """
        CREATE (:Repo {id: $stale_id, status: 'cloning', created_at: $stale_ts})
        CREATE (:Repo {id: $recent_id, status: 'parsing', created_at: $recent_ts})
        CREATE (:Repo {id: $ready_id, status: 'ready', created_at: $ready_ts})
        """,
        params={
            "stale_id": stale_id,
            "stale_ts": stale_ts,
            "recent_id": recent_id,
            "recent_ts": recent_ts,
            "ready_id": ready_id,
            "ready_ts": ready_ts,
        },
    )

    reaped = reap_stale_repos(max_age_minutes=15)
    assert reaped >= 1

    # Verify stale repo is marked failed
    rows = run(g, "MATCH (r:Repo {id: $id}) RETURN r.status AS status, r.error AS error", params={"id": stale_id})
    assert rows[0]["status"] == "failed"
    assert rows[0]["error"] == "Interrupted (server restarted or job timed out)"

    # Verify recent repo is still parsing
    rows = run(g, "MATCH (r:Repo {id: $id}) RETURN r.status AS status", params={"id": recent_id})
    assert rows[0]["status"] == "parsing"

    # Verify ready repo is still ready
    rows = run(g, "MATCH (r:Repo {id: $id}) RETURN r.status AS status", params={"id": ready_id})
    assert rows[0]["status"] == "ready"


def test_pipeline_timeout_marks_repo_failed():
    """Overall pipeline timeout sets failed when execution exceeds timeout limit."""
    repo_id = str(uuid.uuid4())
    g = meta_graph()
    run(
        g,
        "CREATE (:Repo {id: $id, status: 'queued'})",
        params={"id": repo_id},
    )

    def slow_clone(*args, **kwargs):
        time.sleep(2)

    with patch("app.ingest.router.clone_repo", side_effect=slow_clone):
        # Run pipeline with a 1-second timeout
        run_git_pipeline(repo_id, "https://github.com/octocat/Hello-World", timeout_seconds=1)

    rows = run(g, "MATCH (r:Repo {id: $id}) RETURN r.status AS status, r.error AS error", params={"id": repo_id})
    assert rows[0]["status"] == "failed"
    assert "timed out" in rows[0]["error"].lower()


# ── 4. Repo Node Source Naming ─────────────────────────────────────


@patch("app.ingest.router.run_zip_pipeline")
def test_upload_zip_repo_source_name_without_path(mock_worker):
    """Zip source must be the uploaded file name without path. Never store 'unknown' or 'test'."""
    headers = _auth_headers("analyst")
    bio = io.BytesIO()
    with zipfile.ZipFile(bio, "w") as zf:
        zf.writestr("app.py", "x = 1")
    bio.seek(0)

    files = {"file": ("folder/nested/custom_app.zip", bio.getvalue(), "application/zip")}
    resp = client.post("/api/repos/upload", files=files, headers=headers)
    assert resp.status_code == 202
    repo_id = resp.json()["repo_id"]

    g = meta_graph()
    rows = run(g, "MATCH (r:Repo {id: $id}) RETURN r.source AS source", params={"id": repo_id})
    assert rows[0]["source"] == "custom_app.zip"
    assert "/" not in rows[0]["source"]
    assert "\\" not in rows[0]["source"]
    assert rows[0]["source"] not in ("unknown", "test")


# ── Zip Upload Validation ──────────────────────────────────────────


def test_upload_zip_repo_invalid_extension():
    headers = _auth_headers("analyst")
    files = {"file": ("archive.tar.gz", b"binary data", "application/gzip")}
    resp = client.post("/api/repos/upload", files=files, headers=headers)
    assert resp.status_code == 422


# ── List & Get Repos ───────────────────────────────────────────────


def test_list_repos_and_get_by_id():
    headers = _auth_headers("viewer")
    repo_id = str(uuid.uuid4())

    g = meta_graph()
    run(
        g,
        """
        CREATE (r:Repo {
            id: $id,
            source: 'https://github.com/example-org/sample-repo',
            status: 'ready',
            created_at: '2026-01-01T00:00:00Z',
            stats_json: '{"files_parsed": 5, "modules": 3}'
        })
        """,
        params={"id": repo_id},
    )

    # List
    list_resp = client.get("/api/repos", headers=headers)
    assert list_resp.status_code == 200
    repos = list_resp.json()
    assert any(r["id"] == repo_id for r in repos)

    # Get by ID
    get_resp = client.get(f"/api/repos/{repo_id}", headers=headers)
    assert get_resp.status_code == 200
    data = get_resp.json()
    assert data["id"] == repo_id
    assert data["status"] == "ready"
    assert data["stats"]["files_parsed"] == 5

    # Missing ID -> 404
    missing_resp = client.get(f"/api/repos/{uuid.uuid4()}", headers=headers)
    assert missing_resp.status_code == 404


# ── Delete Repo (Admin only) ───────────────────────────────────────


def test_delete_repo_permissions_and_cleanup():
    repo_id = str(uuid.uuid4())
    g = meta_graph()
    run(
        g,
        "CREATE (r:Repo {id: $id, status: 'ready'})",
        params={"id": repo_id},
    )

    # 1. Analyst cannot delete (403)
    analyst_headers = _auth_headers("analyst")
    resp_analyst = client.delete(f"/api/repos/{repo_id}", headers=analyst_headers)
    assert resp_analyst.status_code == 403

    # 2. Admin can delete (204)
    admin_headers = _auth_headers("admin")
    resp_admin = client.delete(f"/api/repos/{repo_id}", headers=admin_headers)
    assert resp_admin.status_code == 204

    # Verify node is gone
    check_rows = run(g, "MATCH (r:Repo {id: $id}) RETURN r", params={"id": repo_id})
    assert len(check_rows) == 0
