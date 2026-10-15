"""
Integration tests for /api/repos router.

Covers:
- POST /api/repos (git url validation, 422 on bad url, 202 on valid url)
- Concurrency limit (429 when >= 2 active analyses exist for the same user)
- POST /api/repos/upload (zip upload, 422 on non-zip)
- GET /api/repos (list repositories)
- GET /api/repos/{id} (get repository, 404 on missing)
- DELETE /api/repos/{id} (admin only, 403 for viewer/analyst, 204 for admin)
"""

import io
import uuid
import zipfile
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.auth.security import create_access_token
from app.graph.client import meta_graph, run
from app.main import app

client = TestClient(app)


def _auth_headers(role: str = "analyst", user_id: str | None = None) -> dict[str, str]:
    uid = user_id or str(uuid.uuid4())
    # Create user node in rg_meta so dependency check passes
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


def test_queue_git_repo_concurrency_limit_429():
    user_id = str(uuid.uuid4())
    headers = _auth_headers("analyst", user_id=user_id)

    # Insert 2 active repos for this user in rg_meta
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


# ── Zip Upload ─────────────────────────────────────────────────────


@patch("app.ingest.router.run_zip_pipeline")
def test_upload_zip_repo_valid(mock_worker):
    headers = _auth_headers("analyst")
    bio = io.BytesIO()
    with zipfile.ZipFile(bio, "w") as zf:
        zf.writestr("main.py", "print('hello')")
    bio.seek(0)

    files = {"file": ("repo.zip", bio.getvalue(), "application/zip")}
    resp = client.post("/api/repos/upload", files=files, headers=headers)
    assert resp.status_code == 202
    assert resp.json()["status"] == "queued"


def test_upload_zip_repo_invalid_extension():
    headers = _auth_headers("analyst")
    files = {"file": ("repo.tar.gz", b"binary data", "application/gzip")}
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
            source: 'https://github.com/test/repo',
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
