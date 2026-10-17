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
    finding_id = uuid.uuid4().hex[:12]
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
            f"/api/repos/{repo_id}/critical-modules",
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
    assert client.get(f"/api/repos/{bad_repo}/critical-modules", headers=headers).status_code == 404
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
    assert client.get(f"/api/repos/{repo_id}/critical-modules", headers=headers).status_code == 409
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


# ── Verify F6: What-if Simulation on Reachable Finding ─────────


def test_verify_f6_whatif_simulation(ready_repo: tuple[str, str, str]) -> None:
    """Verify F6: simulate on a reachable finding; the verdict flips or the path count

    changes consistently with the graph; after the call, reload the finding: unchanged.
    """
    repo_id, fid, _ = ready_repo
    analyst_h = _auth_headers("analyst")

    # 1. Baseline: finding is reachable in real graph
    resp_before = client.get(f"/api/repos/{repo_id}/findings/{fid}", headers=analyst_h)
    assert resp_before.status_code == 200
    finding_before = resp_before.json()
    assert finding_before["verdict"] == "reachable_in_model"
    initial_paths = finding_before["trace"]["paths"]
    assert len(initial_paths) == 1
    assert initial_paths[0]["entrypoint_id"] == "ep-login"

    # 2. Simulate add_auth to ep-login
    resp_sim = client.post(
        f"/api/repos/{repo_id}/whatif",
        json={
            "finding_id": fid,
            "changes": [{"type": "add_auth", "entrypoint_id": "ep-login"}],
        },
        headers=analyst_h,
    )
    assert resp_sim.status_code == 200
    sim_data = resp_sim.json()

    # Verdict flips from reachable_in_model to no_path_found (or path count changes to 0)
    assert sim_data["before"]["verdict"] == "reachable_in_model"
    assert sim_data["after"]["verdict"] == "no_path_found"
    assert len(sim_data["after"]["paths"]) == 0
    assert sim_data["after"]["reaching_entrypoints"] == 0
    assert sim_data["changed"] == [
        {"finding_id": fid, "from": "reachable_in_model", "to": "no_path_found"}
    ]

    # 3. Reload finding after the call: MUST BE UNCHANGED
    resp_reload = client.get(f"/api/repos/{repo_id}/findings/{fid}", headers=analyst_h)
    assert resp_reload.status_code == 200
    finding_reloaded = resp_reload.json()
    assert finding_reloaded["verdict"] == "reachable_in_model"
    assert len(finding_reloaded["trace"]["paths"]) == 1
    assert finding_reloaded["trace"]["paths"][0]["entrypoint_id"] == "ep-login"

    # 4. Simulate remove_import from app.auth to pkg1@1.0.0
    resp_sim_import = client.post(
        f"/api/repos/{repo_id}/whatif",
        json={
            "finding_id": fid,
            "changes": [
                {
                    "type": "remove_import",
                    "module_id": "app.auth",
                    "package_id": "pkg1@1.0.0",
                }
            ],
        },
        headers=analyst_h,
    )
    assert resp_sim_import.status_code == 200
    sim_import_data = resp_sim_import.json()
    assert sim_import_data["before"]["verdict"] == "reachable_in_model"
    assert sim_import_data["after"]["verdict"] == "no_path_found"
    assert len(sim_import_data["after"]["paths"]) == 0

    # 5. Reload finding again: STILL UNCHANGED
    resp_reload2 = client.get(f"/api/repos/{repo_id}/findings/{fid}", headers=analyst_h)
    assert resp_reload2.status_code == 200
    assert resp_reload2.json()["verdict"] == "reachable_in_model"
    assert len(resp_reload2.json()["trace"]["paths"]) == 1


# ── Verify F8: Timeline Memory & Viewer Access Restrictions ────


def test_verify_f8_memory_timeline_and_viewer_access(
    ready_repo: tuple[str, str, str],
) -> None:
    """Verify F8:
    - After F5 (record decision) and F7 (analyst save investigation) actions, the timeline shows the entries in GET /api/repos/{id}/memory.
    - Create a viewer user, log in as them, check they cannot reach /admin/users (HTTP 403) while being able to view memory (HTTP 200).
    """
    from unittest.mock import patch
    from app.agent.loop import AgentResult

    repo_id, fid, _ = ready_repo
    analyst_h = _auth_headers("analyst")
    admin_h = _auth_headers("admin")

    # 1. Action F5: Record a decision
    resp_dec = client.post(
        f"/api/repos/{repo_id}/findings/{fid}/decisions",
        json={
            "type": "false_positive",
            "reason": "Verified false positive due to unreachable test harness code.",
        },
        headers=analyst_h,
    )
    assert resp_dec.status_code == 200
    dec_id = resp_dec.json()["id"]

    # 2. Action F7: Analyst chats with save=true (saves an investigation)
    mock_agent_result = AgentResult(
        answer=f"Detailed investigation for finding {fid}: No reachable path under production configurations.",
        mode="llm_tools",
        tool_calls=[
            {
                "name": "trace_path",
                "args": {"finding_id": fid},
                "ok": True,
                "summary": "1 path analyzed",
            }
        ],
        evidence={
            "findings": [{"id": fid}],
            "traces": [{"finding_id": fid}],
            "memory": [],
        },
        grounded=True,
        warnings=[],
    )

    with patch("app.agent.router.run_agent", return_value=mock_agent_result):
        resp_chat = client.post(
            f"/api/repos/{repo_id}/agent/chat",
            json={"message": f"Investigate finding {fid}", "save": True},
            headers=analyst_h,
        )
        assert resp_chat.status_code == 200

    # 3. Check memory timeline: GET /api/repos/{repo_id}/memory
    resp_mem = client.get(f"/api/repos/{repo_id}/memory", headers=analyst_h)
    assert resp_mem.status_code == 200
    mem_data = resp_mem.json()

    # Timeline must show both investigations and decisions
    assert "investigations" in mem_data and "decisions" in mem_data
    assert len(mem_data["decisions"]) >= 1
    assert any(
        d["id"] == dec_id
        and d["finding_id"] == fid
        and d["type"] == "false_positive"
        for d in mem_data["decisions"]
    )

    assert len(mem_data["investigations"]) >= 1
    inv = mem_data["investigations"][0]
    assert inv["finding_id"] == fid

    # 4. Create a viewer user via Admin API
    viewer_email = f"viewer_{uuid.uuid4().hex[:6]}@example.com"
    viewer_pwd = "viewerSecurePassword123!"
    resp_create_user = client.post(
        "/api/admin/users",
        json={"email": viewer_email, "password": viewer_pwd, "role": "viewer"},
        headers=admin_h,
    )
    assert resp_create_user.status_code == 201
    created_user = resp_create_user.json()
    assert created_user["email"] == viewer_email
    assert created_user["role"] == "viewer"
    assert created_user["active"] is True

    # 5. Verify viewer credentials and create token
    from app.auth.service import authenticate
    assert authenticate(viewer_email, viewer_pwd) is not None
    viewer_token = create_access_token(created_user["id"], created_user["role"])
    viewer_h = {"Authorization": f"Bearer {viewer_token}"}

    # 6. Verify viewer CAN view memory timeline
    resp_viewer_mem = client.get(f"/api/repos/{repo_id}/memory", headers=viewer_h)
    assert resp_viewer_mem.status_code == 200
    assert len(resp_viewer_mem.json()["decisions"]) >= 1

    # 7. Verify viewer CANNOT reach /admin/users (HTTP 403 Forbidden)
    resp_viewer_admin_list = client.get("/api/admin/users", headers=viewer_h)
    assert resp_viewer_admin_list.status_code == 403
    assert resp_viewer_admin_list.json()["error"]["code"] == 403

    resp_viewer_admin_post = client.post(
        "/api/admin/users",
        json={
            "email": "unauthorized@example.com",
            "password": "password12345",
            "role": "admin",
        },
        headers=viewer_h,
    )
    assert resp_viewer_admin_post.status_code == 403
    assert resp_viewer_admin_post.json()["error"]["code"] == 403

    resp_viewer_admin_patch = client.patch(
        f"/api/admin/users/{created_user['id']}",
        json={"role": "admin"},
        headers=viewer_h,
    )
    assert resp_viewer_admin_patch.status_code == 403
    assert resp_viewer_admin_patch.json()["error"]["code"] == 403

