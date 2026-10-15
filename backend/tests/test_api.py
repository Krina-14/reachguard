"""
Integration and role-matrix tests for findings, whatif, and memory API routers.

Tests:
- Role matrix test looping over endpoints and roles (unauthenticated, viewer, analyst, admin)
- 404 on unknown repo or finding
- 409 when repo status is not ready
- 422 on invalid change types or unknown entrypoint/module/package IDs
- 422 on decision reason < 10 characters or invalid decision type
- Decision approval/rejection lifecycle
- AuditEvent emission for decisions and repo operations
- Findings filtering and pagination
"""

from __future__ import annotations

import uuid
from collections.abc import Generator

import pytest
from fastapi.testclient import TestClient

from app.auth.security import create_access_token
from app.graph.client import (
    delete_graph_if_exists,
    meta_graph,
    repo_graph,
    repo_graph_name,
    run,
)
from app.graph.schema import ensure_repo_schema
from app.main import app

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


@pytest.fixture()
def ready_repo() -> Generator[tuple[str, str, str], None, None]:
    """Provide a seeded repo graph with status 'ready'.

    Yields (repo_id, finding_id, decision_id).
    """
    repo_id = str(uuid.uuid4())
    finding_id = "find-" + uuid.uuid4().hex[:6]
    dec_id = "dec-" + uuid.uuid4().hex[:6]

    mg = meta_graph()
    run(
        mg,
        """
        CREATE (r:Repo {
            id: $id,
            source: 'https://github.com/test/repo',
            source_type: 'git',
            status: 'ready',
            created_at: '2026-01-01T00:00:00Z',
            created_by: 'admin',
            stats_json: '{\"modules\": 2, \"packages\": 2, \"findings\": 1, \"files_parsed\": 2, \"lockfile_kind\": \"requirements.txt\"}'
        })
        """,
        {"id": repo_id},
    )

    rg = repo_graph(repo_id)
    ensure_repo_schema(rg)
    seed_cypher = """
    CREATE (e1:Entrypoint {id: 'ep-login', method: 'POST', path: '/login', public: true}),
           (e2:Entrypoint {id: 'ep-admin', method: 'GET', path: '/admin', public: false}),
           (m1:Module {id: 'app.auth', file: 'app/auth.py', lines: 30}),
           (m2:Module {id: 'app.db', file: 'app/db.py', lines: 20}),
           (p1:Package {id: 'pkg1@1.0.0', name: 'pkg1', version: '1.0.0', direct: true, ecosystem: 'PyPI'}),
           (p2:Package {id: 'pkg2@2.0.0', name: 'pkg2', version: '2.0.0', direct: true, ecosystem: 'PyPI'}),
           (v1:Vulnerability {id: 'GHSA-test-v1', summary: 'Test vulnerability in pkg1', severity: 'HIGH'}),
           (f1:Finding {id: $fid, status: 'open', first_seen: '2026-01-01T00:00:00Z'}),
           (d1:Decision {id: $did, type: 'accept_risk', reason: 'Pre-existing pending decision', status: 'pending', by: 'analyst@example.com', created_at: '2026-01-01T00:00:00Z'})

    CREATE (e1)-[:HANDLED_BY]->(m1),
           (e2)-[:HANDLED_BY]->(m2),
           (m1)-[:USES]->(p1),
           (v1)-[:AFFECTS]->(p1),
           (f1)-[:ABOUT]->(v1),
           (f1)-[:ON_PACKAGE]->(p1),
           (f1)-[:HAS_DECISION]->(d1)
    """
    run(rg, seed_cypher, {"fid": finding_id, "did": dec_id})

    yield repo_id, finding_id, dec_id

    # Cleanup
    delete_graph_if_exists(repo_graph_name(repo_id))
    run(mg, "MATCH (r:Repo {id: $id}) DETACH DELETE r", {"id": repo_id})


@pytest.fixture()
def unready_repo() -> Generator[str, None, None]:
    """Provide a repo in 'parsing' status (not ready)."""
    repo_id = str(uuid.uuid4())
    mg = meta_graph()
    run(
        mg,
        """
        CREATE (r:Repo {
            id: $id,
            source: 'https://github.com/test/unready',
            source_type: 'git',
            status: 'parsing',
            created_at: '2026-01-01T00:00:00Z',
            created_by: 'admin'
        })
        """,
        {"id": repo_id},
    )

    yield repo_id

    run(mg, "MATCH (r:Repo {id: $id}) DETACH DELETE r", {"id": repo_id})


# ── Role Matrix Test (Contract Section 3) ──────────────────────


def test_role_matrix(ready_repo: tuple[str, str, str]) -> None:
    """Loop over endpoints and roles, asserting status codes per Contract Section 3."""
    repo_id, fid, did = ready_repo

    endpoints = [
        # (method, path_template, json_body, expected_status_by_role)
        (
            "GET",
            f"/api/repos/{repo_id}/findings",
            None,
            {"unauth": 401, "viewer": 200, "analyst": 200, "admin": 200},
        ),
        (
            "GET",
            f"/api/repos/{repo_id}/findings/{fid}",
            None,
            {"unauth": 401, "viewer": 200, "analyst": 200, "admin": 200},
        ),
        (
            "GET",
            f"/api/repos/{repo_id}/graph",
            None,
            {"unauth": 401, "viewer": 200, "analyst": 200, "admin": 200},
        ),
        (
            "GET",
            f"/api/repos/{repo_id}/choke-points",
            None,
            {"unauth": 401, "viewer": 200, "analyst": 200, "admin": 200},
        ),
        (
            "GET",
            f"/api/repos/{repo_id}/memory",
            None,
            {"unauth": 401, "viewer": 200, "analyst": 200, "admin": 200},
        ),
        (
            "POST",
            f"/api/repos/{repo_id}/whatif",
            {"changes": [{"type": "add_auth", "entrypoint_id": "ep-login"}]},
            {"unauth": 401, "viewer": 403, "analyst": 200, "admin": 200},
        ),
        (
            "POST",
            f"/api/repos/{repo_id}/findings/{fid}/decisions",
            {"type": "fix_planned", "reason": "Planning to upgrade package in sprint 4"},
            {"unauth": 401, "viewer": 403, "analyst": 200, "admin": 200},
        ),
        (
            "POST",
            f"/api/repos/{repo_id}/decisions/{did}/approve",
            None,
            {"unauth": 401, "viewer": 403, "analyst": 403, "admin": 200},
        ),
    ]

    roles = ["unauth", "viewer", "analyst", "admin"]

    for method, path, body, expected_map in endpoints:
        for r in roles:
            headers = {} if r == "unauth" else _auth_headers(r)

            if method == "GET":
                resp = client.get(path, headers=headers)
            elif method == "POST":
                resp = client.post(path, json=body, headers=headers)
            else:
                raise ValueError(f"Unsupported method: {method}")

            expected = expected_map[r]
            assert resp.status_code == expected, (
                f"Failed for {r} on {method} {path}: expected {expected}, got {resp.status_code} ({resp.text})"
            )


# ── 404 on Unknown Repo / Finding ──────────────────────────────


def test_404_unknown_repo() -> None:
    bad_repo = str(uuid.uuid4())
    headers = _auth_headers("admin")

    assert client.get(f"/api/repos/{bad_repo}/findings", headers=headers).status_code == 404
    assert client.get(f"/api/repos/{bad_repo}/findings/some-f", headers=headers).status_code == 404
    assert client.get(f"/api/repos/{bad_repo}/graph", headers=headers).status_code == 404
    assert client.get(f"/api/repos/{bad_repo}/choke-points", headers=headers).status_code == 404
    assert client.get(f"/api/repos/{bad_repo}/memory", headers=headers).status_code == 404
    assert client.post(f"/api/repos/{bad_repo}/whatif", json={"changes": []}, headers=headers).status_code == 404


def test_404_unknown_finding(ready_repo: tuple[str, str, str]) -> None:
    repo_id, _, _ = ready_repo
    headers = _auth_headers("admin")

    resp = client.get(f"/api/repos/{repo_id}/findings/nonexistent-fid", headers=headers)
    assert resp.status_code == 404
    assert "not found" in resp.json()["error"]["message"]

    resp = client.get(f"/api/repos/{repo_id}/graph?finding_id=nonexistent-fid", headers=headers)
    assert resp.status_code == 404


# ── 409 on Unready Repo ────────────────────────────────────────


def test_409_unready_repo(unready_repo: str) -> None:
    repo_id = unready_repo
    headers = _auth_headers("admin")

    assert client.get(f"/api/repos/{repo_id}/findings", headers=headers).status_code == 409
    assert client.get(f"/api/repos/{repo_id}/graph", headers=headers).status_code == 409
    assert client.post(f"/api/repos/{repo_id}/whatif", json={"changes": []}, headers=headers).status_code == 409
    assert client.get(f"/api/repos/{repo_id}/memory", headers=headers).status_code == 409


# ── 422 on Invalid What-if Inputs ──────────────────────────────


def test_whatif_422_validations(ready_repo: tuple[str, str, str]) -> None:
    repo_id, _, _ = ready_repo
    headers = _auth_headers("analyst")

    # Unknown entrypoint id
    resp = client.post(
        f"/api/repos/{repo_id}/whatif",
        json={"changes": [{"type": "add_auth", "entrypoint_id": "nonexistent-ep"}]},
        headers=headers,
    )
    assert resp.status_code == 422
    assert "Unknown entrypoint" in resp.json()["error"]["message"]

    # Unknown module id
    resp = client.post(
        f"/api/repos/{repo_id}/whatif",
        json={"changes": [{"type": "remove_import", "module_id": "nonexistent-m", "package_id": "pkg1@1.0.0"}]},
        headers=headers,
    )
    assert resp.status_code == 422
    assert "Unknown module" in resp.json()["error"]["message"]

    # Unknown package id
    resp = client.post(
        f"/api/repos/{repo_id}/whatif",
        json={"changes": [{"type": "remove_import", "module_id": "app.auth", "package_id": "nonexistent-pkg"}]},
        headers=headers,
    )
    assert resp.status_code == 422
    assert "Unknown package" in resp.json()["error"]["message"]

    # Unsupported change type
    resp = client.post(
        f"/api/repos/{repo_id}/whatif",
        json={"changes": [{"type": "invalid_type"}]},
        headers=headers,
    )
    assert resp.status_code == 422


# ── 422 on Invalid Decision Inputs ─────────────────────────────


def test_decision_422_validations(ready_repo: tuple[str, str, str]) -> None:
    repo_id, fid, _ = ready_repo
    headers = _auth_headers("analyst")

    # Reason < 10 characters
    resp = client.post(
        f"/api/repos/{repo_id}/findings/{fid}/decisions",
        json={"type": "accept_risk", "reason": "short"},
        headers=headers,
    )
    assert resp.status_code == 422

    # Invalid decision type
    resp = client.post(
        f"/api/repos/{repo_id}/findings/{fid}/decisions",
        json={"type": "invalid_type", "reason": "Valid reason exceeding 10 characters"},
        headers=headers,
    )
    assert resp.status_code == 422


# ── Findings Filtering & Pagination ────────────────────────────


def test_findings_filtering_and_pagination(ready_repo: tuple[str, str, str]) -> None:
    repo_id, _, _ = ready_repo
    headers = _auth_headers("viewer")

    # Pagination
    resp = client.get(f"/api/repos/{repo_id}/findings?limit=1&offset=0", headers=headers)
    assert resp.status_code == 200
    assert len(resp.json()) == 1

    # Filter verdict
    resp = client.get(f"/api/repos/{repo_id}/findings?verdict=reachable_in_model", headers=headers)
    assert resp.status_code == 200
    assert len(resp.json()) == 1

    resp_empty = client.get(f"/api/repos/{repo_id}/findings?verdict=nonexistent_verdict", headers=headers)
    assert resp_empty.status_code == 200
    assert len(resp_empty.json()) == 0

    # Search filter q
    resp_q = client.get(f"/api/repos/{repo_id}/findings?q=pkg1", headers=headers)
    assert resp_q.status_code == 200
    assert len(resp_q.json()) == 1


# ── Decision Lifecycle & AuditEvent ────────────────────────────


def test_decision_lifecycle_and_audit(ready_repo: tuple[str, str, str]) -> None:
    repo_id, fid, _ = ready_repo
    analyst_h = _auth_headers("analyst")
    admin_h = _auth_headers("admin")

    # 1. Analyst creates accept_risk decision -> pending
    resp = client.post(
        f"/api/repos/{repo_id}/findings/{fid}/decisions",
        json={"type": "accept_risk", "reason": "Accept risk until next quarter"},
        headers=analyst_h,
    )
    assert resp.status_code == 200
    dec_data = resp.json()
    did = dec_data["id"]
    assert dec_data["status"] == "pending"

    # 2. Admin approves decision -> approved
    approve_resp = client.post(
        f"/api/repos/{repo_id}/decisions/{did}/approve",
        headers=admin_h,
    )
    assert approve_resp.status_code == 200
    assert approve_resp.json()["status"] == "approved"

    # 3. Approving again returns 409
    reapprove_resp = client.post(
        f"/api/repos/{repo_id}/decisions/{did}/approve",
        headers=admin_h,
    )
    assert reapprove_resp.status_code == 409

    # 4. Verify AuditEvents exist in rg_meta
    mg = meta_graph()
    audit_rows = run(mg, "MATCH (a:AuditEvent) WHERE a.action CONTAINS 'decision' RETURN a")
    assert len(audit_rows) >= 1
