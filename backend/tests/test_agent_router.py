"""
Unit and integration tests for Agent Chat API Router (/api/repos/{repo_id}/agent/chat).
"""

from __future__ import annotations

import uuid
from unittest.mock import patch

import pytest
from app.agent.loop import AgentResult
from app.auth.security import create_access_token
from app.graph.client import meta_graph, run
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


@pytest.fixture()
def ready_repo() -> str:
    """Create a repo in rg_meta with status 'ready'."""
    repo_id = str(uuid.uuid4())
    g = meta_graph()
    run(
        g,
        "MERGE (r:Repo {id: $id}) SET r.status = 'ready', r.source = 'test'",
        params={"id": repo_id},
    )
    return repo_id


def test_viewer_chat_success(ready_repo: str) -> None:
    """Viewer can chat when save=false and receives the contract response shape."""
    headers = _auth_headers(role="viewer")
    mock_result = AgentResult(
        answer="Finding 112233445566 is Reachable in model with score 80.",
        mode="deterministic",
        tool_calls=[{"name": "list_findings", "args": {}, "ok": True, "summary": "list_findings(): 1 findings"}],
        evidence={"findings": [{"id": "112233445566", "score": 80}], "traces": [], "memory": []},
        grounded=True,
        warnings=[],
    )

    with patch("app.agent.router.run_agent", return_value=mock_result):
        resp = client.post(
            f"/api/repos/{ready_repo}/agent/chat",
            json={"message": "What should I fix?", "save": False},
            headers=headers,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "session_id" in data
        assert data["answer"] == mock_result.answer
        assert data["mode"] == "deterministic"
        assert len(data["tool_calls"]) == 1
        assert data["grounded"] is True
        assert data["warnings"] == []


def test_viewer_save_refused_with_403(ready_repo: str) -> None:
    """Viewer requesting save=true receives 403 Forbidden with standard error shape."""
    headers = _auth_headers(role="viewer")
    resp = client.post(
        f"/api/repos/{ready_repo}/agent/chat",
        json={"message": "Investigate and save", "save": True},
        headers=headers,
    )
    assert resp.status_code == 403
    err = resp.json()
    assert "error" in err
    assert err["error"]["code"] == 403
    assert "analysts and admins" in err["error"]["message"].lower()


def test_analyst_save_single_finding_calls_save_investigation(ready_repo: str) -> None:
    """When analyst requests save=true and answer concerns exactly one finding, save_investigation is called."""
    headers = _auth_headers(role="analyst")
    single_fid = "112233445566"
    long_answer = f"Finding {single_fid} is Reachable in model. " + "A" * 600

    mock_result = AgentResult(
        answer=long_answer,
        mode="llm_explain",
        tool_calls=[],
        evidence={"findings": [], "traces": [{"finding_id": single_fid}], "memory": []},
        grounded=True,
        warnings=[],
    )

    with (
        patch("app.agent.router.run_agent", return_value=mock_result),
        patch("app.agent.router.save_investigation_tool", return_value={"ok": True, "investigation_id": "inv-123"}) as mock_save,
    ):
        resp = client.post(
            f"/api/repos/{ready_repo}/agent/chat",
            json={"message": f"Investigate {single_fid}", "save": True},
            headers=headers,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert any(tc.get("name") == "save_investigation" for tc in data["tool_calls"])

        # Check that save_investigation was called with first 500 characters
        mock_save.assert_called_once()
        call_kwargs = mock_save.call_args.kwargs
        assert call_kwargs["finding_id"] == single_fid
        assert len(call_kwargs["summary"]) == 500
        assert call_kwargs["summary"] == long_answer[:500]


def test_save_not_called_when_multiple_findings_discussed(ready_repo: str) -> None:
    """When answer concerns multiple findings, router does NOT call save_investigation."""
    headers = _auth_headers(role="admin")
    mock_result = AgentResult(
        answer="Comparing finding 112233445566 and finding 223344556677.",
        mode="llm_tools",
        tool_calls=[],
        evidence={"findings": [], "traces": [], "memory": []},
        grounded=True,
        warnings=[],
    )

    with (
        patch("app.agent.router.run_agent", return_value=mock_result),
        patch("app.agent.router.save_investigation_tool") as mock_save,
    ):
        resp = client.post(
            f"/api/repos/{ready_repo}/agent/chat",
            json={"message": "Compare top findings", "save": True},
            headers=headers,
        )
        assert resp.status_code == 200
        mock_save.assert_not_called()


def test_repo_not_found_404() -> None:
    """Unknown repo UUID returns 404 in standard error envelope."""
    headers = _auth_headers(role="analyst")
    random_uuid = str(uuid.uuid4())
    resp = client.post(
        f"/api/repos/{random_uuid}/agent/chat",
        json={"message": "Hello"},
        headers=headers,
    )
    assert resp.status_code == 404
    err = resp.json()
    assert err["error"]["code"] == 404
    assert "not found" in err["error"]["message"].lower()


def test_repo_unready_409() -> None:
    """Repo with status != 'ready' returns 409 Conflict in standard error envelope."""
    headers = _auth_headers(role="analyst")
    unready_id = str(uuid.uuid4())
    g = meta_graph()
    run(
        g,
        "MERGE (r:Repo {id: $id}) SET r.status = 'parsing', r.source = 'test'",
        params={"id": unready_id},
    )

    resp = client.post(
        f"/api/repos/{unready_id}/agent/chat",
        json={"message": "Hello"},
        headers=headers,
    )
    assert resp.status_code == 409
    err = resp.json()
    assert err["error"]["code"] == 409
    assert "not ready" in err["error"]["message"].lower()


def test_message_length_validations(ready_repo: str) -> None:
    """Message must be 1 to 2000 characters."""
    headers = _auth_headers(role="analyst")

    # Empty message
    resp_empty = client.post(
        f"/api/repos/{ready_repo}/agent/chat",
        json={"message": ""},
        headers=headers,
    )
    assert resp_empty.status_code == 422

    # Whitespace only
    resp_ws = client.post(
        f"/api/repos/{ready_repo}/agent/chat",
        json={"message": "   "},
        headers=headers,
    )
    assert resp_ws.status_code == 422

    # Exceeds 2000 characters
    resp_too_long = client.post(
        f"/api/repos/{ready_repo}/agent/chat",
        json={"message": "a" * 2001},
        headers=headers,
    )
    assert resp_too_long.status_code == 422


def test_in_memory_session_history_passed_to_agent(ready_repo: str) -> None:
    """Session history is accumulated in-memory and passed to subsequent run_agent calls."""
    headers = _auth_headers(role="analyst")
    session_id = str(uuid.uuid4())

    mock_res1 = AgentResult(answer="Answer 1", mode="deterministic", tool_calls=[], evidence={})
    mock_res2 = AgentResult(answer="Answer 2", mode="deterministic", tool_calls=[], evidence={})

    with patch("app.agent.router.run_agent") as mock_run:
        mock_run.return_value = mock_res1
        # Turn 1
        resp1 = client.post(
            f"/api/repos/{ready_repo}/agent/chat",
            json={"message": "Question 1", "session_id": session_id},
            headers=headers,
        )
        assert resp1.status_code == 200
        assert mock_run.call_args.kwargs["history"] == []

        # Turn 2 with same session_id
        mock_run.return_value = mock_res2
        resp2 = client.post(
            f"/api/repos/{ready_repo}/agent/chat",
            json={"message": "Question 2", "session_id": session_id},
            headers=headers,
        )
        assert resp2.status_code == 200
        history_turn2 = mock_run.call_args.kwargs["history"]
        assert len(history_turn2) == 2
        assert history_turn2[0] == {"role": "user", "content": "Question 1"}
        assert history_turn2[1] == {"role": "assistant", "content": "Answer 1"}


def test_unexpected_exception_returns_500_without_stack_trace(ready_repo: str) -> None:
    """Unexpected exceptions return 500 standard error shape without leaking internal stack trace."""
    headers = _auth_headers(role="analyst")

    with patch("app.agent.router.run_agent", side_effect=RuntimeError("Secret database crash details!")):
        resp = client.post(
            f"/api/repos/{ready_repo}/agent/chat",
            json={"message": "Trigger unexpected crash"},
            headers=headers,
        )
        assert resp.status_code == 500
        err = resp.json()
        assert err["error"]["code"] == 500
        assert err["error"]["message"] == "Internal server error"
        assert "Secret database crash details" not in resp.text


def test_rate_limit_20_per_minute(ready_repo: str) -> None:
    """Rate limit enforces maximum 20 requests per minute per user."""
    headers = _auth_headers(role="analyst")
    mock_result = AgentResult(answer="OK", mode="deterministic", tool_calls=[], evidence={})

    with patch("app.agent.router.run_agent", return_value=mock_result):
        # 20 allowed
        for _ in range(20):
            res = client.post(
                f"/api/repos/{ready_repo}/agent/chat",
                json={"message": "Ping"},
                headers=headers,
            )
            assert res.status_code == 200

        # 21st request should be rate limited
        res21 = client.post(
            f"/api/repos/{ready_repo}/agent/chat",
            json={"message": "Ping"},
            headers=headers,
        )
        assert res21.status_code == 429


# ── Verify F7: Fix first query, deterministic mode, viewer save ────────


def test_verify_f7_fix_first_deterministic_and_viewer_save(ready_repo: str) -> None:
    """Verify F7:

    - Ask "Which finding should I fix first and why?". The answer appears with tool calls under Evidence.
    - Stop Ollama: the next answer shows the "Deterministic" chip (mode='deterministic').
    - As viewer the Save toggle is rejected with 403 (hidden on frontend).
    """
    analyst_h = _auth_headers(role="analyst")
    viewer_h = _auth_headers(role="viewer")

    # 1. Ask "Which finding should I fix first and why?" with active LLM tools
    mock_llm_result = AgentResult(
        answer="You should fix finding 112233445566 first because it has a confirmed path from public entrypoint POST /login and high risk score 85.",
        mode="llm_tools",
        tool_calls=[
            {"name": "list_findings", "args": {}, "ok": True, "summary": "Found 1 finding"},
            {"name": "choke_points", "args": {}, "ok": True, "summary": "Top choke point is pkg1"},
            {"name": "trace_path", "args": {"finding_id": "112233445566"}, "ok": True, "summary": "1 reaching path"},
        ],
        evidence={
            "findings": [{"id": "112233445566", "package": "pkg1", "score": 85, "verdict": "reachable_in_model"}],
            "traces": [{"finding_id": "112233445566", "verdict": "reachable_in_model", "paths": [{}]}],
            "memory": [],
        },
        grounded=True,
        warnings=[],
    )

    with patch("app.agent.router.run_agent", return_value=mock_llm_result):
        resp_llm = client.post(
            f"/api/repos/{ready_repo}/agent/chat",
            json={"message": "Which finding should I fix first and why?"},
            headers=analyst_h,
        )
        assert resp_llm.status_code == 200
        data_llm = resp_llm.json()
        assert data_llm["mode"] == "llm_tools"
        assert len(data_llm["tool_calls"]) == 3
        tool_names = [tc["name"] for tc in data_llm["tool_calls"]]
        assert "list_findings" in tool_names
        assert "choke_points" in tool_names
        assert len(data_llm["evidence"]["traces"]) >= 1

    # 2. Stop Ollama: LLM is unreachable -> next answer returns mode "deterministic"
    mock_deterministic_result = AgentResult(
        answer="Deterministic assessment: Finding 112233445566 on pkg1 has confirmed reachability.",
        mode="deterministic",
        tool_calls=[
            {"name": "list_findings", "args": {}, "ok": True, "summary": "Found 1 finding"},
            {"name": "choke_points", "args": {}, "ok": True, "summary": "pkg1 is choke point"},
        ],
        evidence={
            "findings": [{"id": "112233445566", "package": "pkg1", "score": 85}],
            "traces": [],
            "memory": [],
        },
        grounded=True,
        warnings=[],
    )

    with patch("app.agent.router.run_agent", return_value=mock_deterministic_result):
        resp_det = client.post(
            f"/api/repos/{ready_repo}/agent/chat",
            json={"message": "Which finding should I fix first and why?"},
            headers=analyst_h,
        )
        assert resp_det.status_code == 200
        data_det = resp_det.json()
        assert data_det["mode"] == "deterministic"
        assert len(data_det["tool_calls"]) >= 1

    # 3. As viewer: save=true returns 403 Forbidden (UI hides the toggle for viewers)
    resp_viewer_save = client.post(
        f"/api/repos/{ready_repo}/agent/chat",
        json={"message": "Which finding should I fix first and why?", "save": True},
        headers=viewer_h,
    )
    assert resp_viewer_save.status_code == 403
    assert "analysts and admins" in resp_viewer_save.json()["error"]["message"].lower()

    # 4. As viewer without save: 200 OK
    resp_viewer_ok = client.post(
        f"/api/repos/{ready_repo}/agent/chat",
        json={"message": "Which finding should I fix first and why?", "save": False},
        headers=viewer_h,
    )
    assert resp_viewer_ok.status_code == 200
