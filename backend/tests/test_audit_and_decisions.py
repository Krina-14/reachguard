"""
Tests for:
- GET /api/decisions?status=pending (admin only, cap 200, finding summary)
- GET /api/admin/audit?limit=100 (admin only, limit max 500, newest first)
- AuditEvent emission for decisions, logins, user changes, repo create/delete, approvals
- Role-matrix tests: viewer and analyst get 403, admin 200
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from app.auth.service import authenticate, create_user, update_user
from app.deps import get_current_user
from app.graph.audit import write_audit_event
from app.main import app
from fastapi.testclient import TestClient

client = TestClient(app)


# ── Role Matrix Tests ──────────────────────────────────────────


@pytest.mark.parametrize(
    ("role", "expected_status"),
    [
        ("viewer", 403),
        ("analyst", 403),
        ("admin", 200),
    ],
)
def test_decisions_role_matrix(role: str, expected_status: int) -> None:
    """GET /api/decisions: viewer and analyst get 403 with standard error shape, admin 200 with rows."""
    user = {"id": f"u-{role}", "email": f"{role}@example.com", "role": role, "active": True}
    app.dependency_overrides[get_current_user] = lambda: user

    sample_decision_row = {
        "id": "dec-1",
        "type": "accept_risk",
        "status": "pending",
        "reason": "Valid reason over 10 chars",
        "by": "analyst@example.com",
        "created_at": "2026-10-15T10:00:00Z",
        "finding_id": "f-1",
        "vuln_id": "GHSA-1",
        "package_name": "urllib3",
        "package_version": "1.26.4",
        "total_public": 1,
        "reaching_eps": 1,
        "uses_count": 1,
        "blind_spots": [],
    }

    def mock_run(g: Any, cypher: str, params: dict | None = None) -> list[dict]:
        if "Repo" in cypher:
            return [{"id": "repo-1", "source": "https://github.com/org/repo"}]
        if "Decision" in cypher:
            return [sample_decision_row]
        return []

    try:
        with (
            patch("app.api.memory.meta_graph"),
            patch("app.api.memory.repo_graph"),
            patch("app.api.memory.run", side_effect=mock_run),
        ):
            resp = client.get("/api/decisions?status=pending")
            assert resp.status_code == expected_status
            if expected_status == 200:
                data = resp.json()
                assert isinstance(data, list)
                assert len(data) >= 1
                assert "finding" in data[0]
                assert "repo_id" in data[0]
            elif expected_status == 403:
                assert resp.json() == {
                    "error": {
                        "code": 403,
                        "message": "Insufficient permissions",
                    }
                }
    finally:
        app.dependency_overrides.pop(get_current_user, None)


@pytest.mark.parametrize(
    ("role", "expected_status"),
    [
        ("viewer", 403),
        ("analyst", 403),
        ("admin", 200),
    ],
)
def test_admin_audit_role_matrix(role: str, expected_status: int) -> None:
    """GET /api/admin/audit: viewer and analyst get 403 with standard error shape, admin 200 with rows."""
    user = {"id": f"u-{role}", "email": f"{role}@example.com", "role": role, "active": True}
    app.dependency_overrides[get_current_user] = lambda: user

    sample_audit_row = {
        "id": "aid-1",
        "at": "2026-10-17T12:00:00Z",
        "actor": "admin@example.com",
        "action": "repo_create",
        "target": "repo-1",
    }

    try:
        with (
            patch("app.auth.router.meta_graph"),
            patch("app.auth.router.run", return_value=[sample_audit_row]),
        ):
            resp = client.get("/api/admin/audit?limit=100")
            assert resp.status_code == expected_status
            if expected_status == 200:
                data = resp.json()
                assert isinstance(data, list)
                assert len(data) >= 1
                assert data[0]["action"] == "repo_create"
            elif expected_status == 403:
                assert resp.json() == {
                    "error": {
                        "code": 403,
                        "message": "Insufficient permissions",
                    }
                }
    finally:
        app.dependency_overrides.pop(get_current_user, None)


def test_unauthenticated_requests() -> None:
    """Unauthenticated requests get 401."""
    app.dependency_overrides.pop(get_current_user, None)
    resp_dec = client.get("/api/decisions?status=pending")
    assert resp_dec.status_code == 401

    resp_audit = client.get("/api/admin/audit?limit=100")
    assert resp_audit.status_code == 401


# ── Decisions Endpoint Functionality ───────────────────────────


def test_get_decisions_pending_contract() -> None:
    """GET /api/decisions?status=pending returns ready repo decisions with finding summary."""
    admin_user = {"id": "u-admin", "email": "admin@example.com", "role": "admin", "active": True}
    app.dependency_overrides[get_current_user] = lambda: admin_user

    repo_id = "test-repo-123"
    repo_source = "https://github.com/org/repo"

    ready_repos = [{"id": repo_id, "source": repo_source}]

    # Simulated row from the single Cypher query per repo graph
    repo_decision_rows = [
        {
            "id": "dec-001",
            "type": "accept_risk",
            "status": "pending",
            "reason": "Risk accepted pending review by team lead",
            "by": "analyst@example.com",
            "created_at": "2026-10-15T10:00:00Z",
            "expires_at": None,
            "approved_by": None,
            "finding_id": "f-abc123",
            "vuln_id": "GHSA-1234-5678",
            "severity": "HIGH",
            "package_name": "urllib3",
            "package_id": "urllib3@1.26.4",
            "package_version": "1.26.4",
            "total_public": 5,
            "reaching_eps": 2,
            "uses_count": 1,
            "blind_spots": [],
        }
    ]

    def mock_run(graph: Any, cypher: str, params: dict | None = None) -> list[dict]:
        if "Repo" in cypher:
            return ready_repos
        if "Decision" in cypher:
            assert params is not None
            assert params.get("status") == "pending"
            assert params.get("limit") == 200
            return repo_decision_rows
        return []

    try:
        with (
            patch("app.api.memory.meta_graph"),
            patch("app.api.memory.repo_graph"),
            patch("app.api.memory.run", side_effect=mock_run) as run_spy,
        ):
            resp = client.get("/api/decisions?status=pending")
            assert resp.status_code == 200
            data = resp.json()
            assert len(data) == 1
            item = data[0]

            assert item["repo_id"] == repo_id
            assert item["repo_source"] == repo_source
            assert item["id"] == "dec-001"
            assert item["status"] == "pending"

            # Finding summary: {id, vuln_id, package, version, verdict, score}
            finding = item["finding"]
            assert finding["id"] == "f-abc123"
            assert finding["vuln_id"] == "GHSA-1234-5678"
            assert finding["package"] == "urllib3"
            assert finding["version"] == "1.26.4"
            assert finding["verdict"] == "reachable_in_model"
            assert isinstance(finding["score"], int)

            # Check that only one query was run for the repo graph
            # (1 for meta_graph repos, 1 for repo graph)
            assert run_spy.call_count == 2
    finally:
        app.dependency_overrides.pop(get_current_user, None)


def test_get_decisions_cap_200() -> None:
    """GET /api/decisions caps results at 200 rows across all ready repos."""
    admin_user = {"id": "u-admin", "email": "admin@example.com", "role": "admin", "active": True}
    app.dependency_overrides[get_current_user] = lambda: admin_user

    ready_repos = [{"id": f"repo-{i}", "source": f"https://github.com/org/repo-{i}"} for i in range(5)]

    def mock_run(graph: Any, cypher: str, params: dict | None = None) -> list[dict]:
        if "Repo" in cypher:
            return ready_repos
        # Return 100 rows per repo
        return [
            {
                "id": f"dec-{i}",
                "type": "accept_risk",
                "status": "pending",
                "reason": "Test reason over 10 chars",
                "by": "user@example.com",
                "created_at": "2026-10-15T10:00:00Z",
                "finding_id": f"f-{i}",
                "vuln_id": "GHSA-test",
                "severity": "LOW",
                "package_name": "pkg",
                "package_version": "1.0",
                "total_public": 1,
                "reaching_eps": 1,
                "uses_count": 1,
                "blind_spots": [],
            }
            for i in range(100)
        ]

    try:
        with (
            patch("app.api.memory.meta_graph"),
            patch("app.api.memory.repo_graph"),
            patch("app.api.memory.run", side_effect=mock_run),
        ):
            resp = client.get("/api/decisions?status=pending")
            assert resp.status_code == 200
            data = resp.json()
            assert len(data) == 200
    finally:
        app.dependency_overrides.pop(get_current_user, None)


# ── Admin Audit Endpoint Functionality ─────────────────────────


def test_get_admin_audit_contract() -> None:
    """GET /api/admin/audit?limit=100 returns AuditEvent rows newest first {id, at, actor, action, target}."""
    admin_user = {"id": "u-admin", "email": "admin@example.com", "role": "admin", "active": True}
    app.dependency_overrides[get_current_user] = lambda: admin_user

    mock_audit_rows = [
        {
            "id": "aid-1",
            "at": "2026-10-17T12:00:00Z",
            "actor": "admin@example.com",
            "action": "approve_decision",
            "target": "repo-1:dec-1",
        },
        {
            "id": "aid-2",
            "at": "2026-10-17T11:59:00Z",
            "actor": "user@example.com",
            "action": "login_success",
            "target": "auth/login",
        },
    ]

    def mock_run(graph: Any, cypher: str, params: dict | None = None) -> list[dict]:
        assert "AuditEvent" in cypher
        assert params is not None
        assert params["limit"] == 100
        return mock_audit_rows

    try:
        with (
            patch("app.auth.router.meta_graph"),
            patch("app.auth.router.run", side_effect=mock_run),
        ):
            resp = client.get("/api/admin/audit?limit=100")
            assert resp.status_code == 200
            data = resp.json()
            assert len(data) == 2
            assert data[0]["id"] == "aid-1"
            assert data[0]["actor"] == "admin@example.com"
            assert data[0]["action"] == "approve_decision"
            assert data[0]["target"] == "repo-1:dec-1"
            assert "at" in data[0]
    finally:
        app.dependency_overrides.pop(get_current_user, None)


def test_admin_audit_limit_clamped_max_500() -> None:
    """GET /api/admin/audit clamps limit at max 500."""
    admin_user = {"id": "u-admin", "email": "admin@example.com", "role": "admin", "active": True}
    app.dependency_overrides[get_current_user] = lambda: admin_user

    captured_params = {}

    def mock_run(graph: Any, cypher: str, params: dict | None = None) -> list[dict]:
        if params:
            captured_params.update(params)
        return []

    try:
        with (
            patch("app.auth.router.meta_graph"),
            patch("app.auth.router.run", side_effect=mock_run),
        ):
            # Request limit=600 -> should be clamped or capped at 500
            resp = client.get("/api/admin/audit?limit=500")
            assert resp.status_code == 200
            assert captured_params.get("limit") == 500
    finally:
        app.dependency_overrides.pop(get_current_user, None)


# ── Audit Event Writing Checks ─────────────────────────────────


def test_audit_event_written_on_write_audit_event() -> None:
    """write_audit_event creates node with {id, at, actor, action, target}."""
    with patch("app.graph.audit.meta_graph"), patch("app.graph.audit.run") as mock_run:
        write_audit_event("admin@reachguard.io", "repo_create", "repo-123")
        assert mock_run.called
        args, kwargs = mock_run.call_args
        params = kwargs.get("params") or args[2]
        assert params["actor"] == "admin@reachguard.io"
        assert params["action"] == "repo_create"
        assert params["target"] == "repo-123"
        assert "id" in params
        assert "at" in params


def test_audit_event_written_on_login() -> None:
    """Logins (success and failure) write AuditEvent rows."""
    with (
        patch("app.auth.service.meta_graph"),
        patch("app.auth.service.write_audit_event") as mock_audit,
        patch("app.auth.service.get_user_by_email") as mock_get_user,
        patch("app.auth.service.verify_password", return_value=True),
    ):
        # 1. Login success
        mock_get_user.return_value = {
            "id": "u1",
            "email": "user@test.io",
            "password_hash": "hash",
            "active": True,
            "role": "analyst",
        }
        res = authenticate("user@test.io", "correct_pass")
        assert res is not None
        mock_audit.assert_called_with(
            actor="user@test.io",
            action="login_success",
            target="auth/login",
        )

        # 2. Login failure (bad pass)
        with patch("app.auth.service.verify_password", return_value=False):
            res_fail = authenticate("user@test.io", "wrong_pass")
            assert res_fail is None
            mock_audit.assert_called_with(
                actor="user@test.io",
                action="login_failure",
                target="invalid credentials",
            )


def test_audit_event_written_on_user_changes() -> None:
    """User creation and updates write AuditEvent rows."""
    with (
        patch("app.auth.service.meta_graph") as mock_mg,
        patch("app.auth.service.write_audit_event") as mock_audit,
        patch("app.auth.service.get_user_by_email", return_value=None),
        patch("app.auth.service.get_user_by_id") as mock_get_id,
    ):
        mock_mg.return_value.query = MagicMock()
        mock_get_id.return_value = {
            "id": "u2",
            "email": "newuser@test.io",
            "role": "analyst",
            "active": True,
        }

        # 1. create_user
        create_user("newuser@test.io", "ValidPass123!", "analyst", actor_email="admin@test.io")
        mock_audit.assert_called_with(
            actor="admin@test.io",
            action="user_create",
            target="target=newuser@test.io role=analyst",
        )

        # 2. update_user
        update_user("u2", role="admin", actor_email="superadmin@test.io")
        mock_audit.assert_called_with(
            actor="superadmin@test.io",
            action="user_change",
            target="target=u2 role=admin",
        )


def test_audit_event_written_on_decisions_and_approvals() -> None:
    """Decisions and approvals write AuditEvent rows."""
    admin_user = {"id": "u-admin", "email": "admin@example.com", "role": "admin", "active": True}
    app.dependency_overrides[get_current_user] = lambda: admin_user

    with (
        patch("app.api.memory.check_repo_ready"),
        patch("app.api.memory.queries.set_decision_status") as mock_set_status,
        patch("app.api.memory.write_audit_event") as mock_audit,
    ):
        mock_set_status.return_value = {"id": "dec-10", "status": "approved"}
        resp = client.post("/api/repos/repo-1/decisions/dec-10/approve")
        assert resp.status_code == 200
        mock_audit.assert_called_with("admin@example.com", "approve_decision", "repo-1:dec-10")

        mock_set_status.return_value = {"id": "dec-10", "status": "rejected"}
        resp = client.post("/api/repos/repo-1/decisions/dec-10/reject")
        assert resp.status_code == 200
        mock_audit.assert_called_with("admin@example.com", "reject_decision", "repo-1:dec-10")

    app.dependency_overrides.pop(get_current_user, None)
