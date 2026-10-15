"""
Integration tests for the auth system.

Uses FastAPI TestClient against a real FalkorDB instance.
Each test run uses a unique email prefix to avoid collisions.
"""

from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient

from app.auth.security import create_access_token
from app.auth.service import create_user, get_user_by_email, update_user
from app.graph.client import meta_graph, run

# ── Unique prefix per test run ──────────────────────────────────

_RUN_ID = uuid.uuid4().hex[:8]


def _email(name: str) -> str:
    """Generate a unique email for this test run."""
    return f"{name}_{_RUN_ID}@test.reachguard.dev"


# ── Fixtures ────────────────────────────────────────────────────


@pytest.fixture(scope="module")
def client():
    """Create a TestClient with the full FastAPI app."""
    from app.main import app
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c


@pytest.fixture(scope="module")
def admin_user():
    """Create an admin user for this test run and return its dict."""
    email = _email("admin")
    user = create_user(email, "AdminPass!123", "admin")
    return user


@pytest.fixture(scope="module")
def admin_token(admin_user):
    """Return a valid JWT for the admin user."""
    return create_access_token(admin_user["id"], admin_user["role"])


@pytest.fixture(scope="module")
def viewer_user():
    """Create a viewer user for this test run."""
    email = _email("viewer")
    return create_user(email, "ViewerPass123", "viewer")


@pytest.fixture(scope="module")
def viewer_token(viewer_user):
    """Return a valid JWT for the viewer user."""
    return create_access_token(viewer_user["id"], viewer_user["role"])


def _auth_header(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


# ── Cleanup ─────────────────────────────────────────────────────


@pytest.fixture(scope="module", autouse=True)
def cleanup_test_users():
    """Delete test users and audit events after all tests in this module."""
    yield
    g = meta_graph()
    try:
        g.query(
            "MATCH (u:User) WHERE u.email CONTAINS $run_id DETACH DELETE u",
            params={"run_id": _RUN_ID},
        )
    except Exception:
        pass
    try:
        g.query(
            "MATCH (a:AuditEvent) WHERE a.actor_email CONTAINS $run_id DETACH DELETE a",
            params={"run_id": _RUN_ID},
        )
    except Exception:
        pass


# ══════════════════════════════════════════════════════════════════
# Tests
# ══════════════════════════════════════════════════════════════════


class TestLogin:
    """POST /api/auth/login"""

    def test_login_ok(self, client, admin_user):
        resp = client.post(
            "/api/auth/login",
            json={"email": admin_user["email"], "password": "AdminPass!123"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "access_token" in data
        assert data["token_type"] == "bearer"

    def test_wrong_password_401(self, client, admin_user):
        resp = client.post(
            "/api/auth/login",
            json={"email": admin_user["email"], "password": "WrongPassword1"},
        )
        assert resp.status_code == 401
        body = resp.json()
        # Standard error envelope
        assert "error" in body
        assert body["error"]["code"] == 401

    def test_unknown_email_401(self, client):
        resp = client.post(
            "/api/auth/login",
            json={"email": "nobody@nowhere.dev", "password": "WrongPassword1"},
        )
        assert resp.status_code == 401

    def test_login_error_is_vague(self, client, admin_user):
        """Wrong password and unknown email must return the same message."""
        r1 = client.post(
            "/api/auth/login",
            json={"email": admin_user["email"], "password": "WrongPassword1"},
        )
        r2 = client.post(
            "/api/auth/login",
            json={"email": "nobody@nowhere.dev", "password": "WrongPassword1"},
        )
        assert r1.json()["error"]["message"] == r2.json()["error"]["message"]


class TestMe:
    """GET /api/auth/me"""

    def test_me_ok(self, client, admin_user, admin_token):
        resp = client.get("/api/auth/me", headers=_auth_header(admin_token))
        assert resp.status_code == 200
        data = resp.json()
        assert data["email"] == admin_user["email"]
        assert data["role"] == "admin"
        # Must not leak password hash
        assert "password_hash" not in data

    def test_no_token_401(self, client):
        resp = client.get("/api/auth/me")
        assert resp.status_code == 401


class TestChangePassword:
    """POST /api/auth/change-password"""

    def test_change_password_ok(self, client):
        # Create a temporary user just for this test
        email = _email("changepw")
        user = create_user(email, "OldPassword123", "viewer")
        # Create token directly (avoids rate limiter from earlier login tests)
        token = create_access_token(user["id"], user["role"])
        # Change password
        r2 = client.post(
            "/api/auth/change-password",
            headers=_auth_header(token),
            json={"current_password": "OldPassword123", "new_password": "NewPassword456"},
        )
        assert r2.status_code == 200
        # Verify new password works via service layer
        from app.auth.service import authenticate
        assert authenticate(email, "NewPassword456") is not None
        # Verify old password no longer works
        assert authenticate(email, "OldPassword123") is None


class TestAdminRoutes:
    """GET/POST/PATCH /api/admin/users"""

    def test_viewer_gets_403(self, client, viewer_token):
        resp = client.get("/api/admin/users", headers=_auth_header(viewer_token))
        assert resp.status_code == 403
        body = resp.json()
        assert body["error"]["code"] == 403

    def test_list_users(self, client, admin_token, admin_user):
        resp = client.get("/api/admin/users", headers=_auth_header(admin_token))
        assert resp.status_code == 200
        users = resp.json()
        emails = [u["email"] for u in users]
        assert admin_user["email"] in emails

    def test_create_user(self, client, admin_token):
        email = _email("newuser")
        resp = client.post(
            "/api/admin/users",
            headers=_auth_header(admin_token),
            json={"email": email, "password": "CreateMe123!", "role": "analyst"},
        )
        assert resp.status_code == 201
        assert resp.json()["email"] == email
        assert resp.json()["role"] == "analyst"

    def test_create_duplicate_409(self, client, admin_token, admin_user):
        resp = client.post(
            "/api/admin/users",
            headers=_auth_header(admin_token),
            json={"email": admin_user["email"], "password": "DupeDupe123!", "role": "viewer"},
        )
        assert resp.status_code == 409

    def test_patch_user_role(self, client, admin_token, viewer_user):
        resp = client.patch(
            f"/api/admin/users/{viewer_user['id']}",
            headers=_auth_header(admin_token),
            json={"role": "analyst"},
        )
        assert resp.status_code == 200
        assert resp.json()["role"] == "analyst"

    def test_no_token_on_admin_route(self, client):
        resp = client.get("/api/admin/users")
        assert resp.status_code == 401


class TestLastAdminProtection:
    """Cannot demote or deactivate the last active admin."""

    def test_demote_last_admin_409(self, client):
        """When only one active admin exists, demoting them returns 409."""
        # Create a solo admin
        email = _email("solo_admin")
        solo = create_user(email, "SoloAdmin!123", "admin")
        token = create_access_token(solo["id"], solo["role"])

        # Deactivate the other test admins so this is truly the last one
        # (the module-scoped admin_user may also be active)
        g = meta_graph()
        run(
            g,
            "MATCH (u:User {role: 'admin', active: true}) "
            "WHERE u.id <> $uid SET u.active = false RETURN u.id AS id",
            params={"uid": solo["id"]},
        )

        resp = client.patch(
            f"/api/admin/users/{solo['id']}",
            headers=_auth_header(token),
            json={"role": "viewer"},
        )
        assert resp.status_code == 409

        # Restore: reactivate the other admins
        run(
            g,
            "MATCH (u:User {role: 'admin'}) "
            "WHERE u.email CONTAINS $run_id SET u.active = true RETURN u.id AS id",
            params={"run_id": _RUN_ID},
        )

    def test_deactivate_last_admin_409(self, client):
        """When only one active admin exists, deactivating them returns 409."""
        email = _email("solo_admin2")
        solo = create_user(email, "SoloAdmin!456", "admin")
        token = create_access_token(solo["id"], solo["role"])

        g = meta_graph()
        run(
            g,
            "MATCH (u:User {role: 'admin', active: true}) "
            "WHERE u.id <> $uid SET u.active = false RETURN u.id AS id",
            params={"uid": solo["id"]},
        )

        resp = client.patch(
            f"/api/admin/users/{solo['id']}",
            headers=_auth_header(token),
            json={"active": False},
        )
        assert resp.status_code == 409

        run(
            g,
            "MATCH (u:User {role: 'admin'}) "
            "WHERE u.email CONTAINS $run_id SET u.active = true RETURN u.id AS id",
            params={"run_id": _RUN_ID},
        )


class TestDeactivatedUser:
    """A deactivated user's existing token should be rejected."""

    def test_deactivated_user_token_401(self, client):
        email = _email("deactivated")
        user = create_user(email, "DeactUser!123", "viewer")
        token = create_access_token(user["id"], user["role"])

        # Token works initially
        resp = client.get("/api/auth/me", headers=_auth_header(token))
        assert resp.status_code == 200

        # Deactivate the user directly in the graph
        update_user(user["id"], active=False, actor_email="test")

        # Same token should now be rejected
        resp = client.get("/api/auth/me", headers=_auth_header(token))
        assert resp.status_code == 401


class TestErrorEnvelope:
    """All errors must use {"error": {"code": ..., "message": ...}}."""

    def test_404_envelope(self, client):
        resp = client.get("/nonexistent-route")
        assert resp.status_code in (404, 405)
        body = resp.json()
        assert "error" in body
        assert "code" in body["error"]
        assert "message" in body["error"]
