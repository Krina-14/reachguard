"""
Unit tests for backend/app/agent/tools.py.

Uses monkeypatched stand-in functions for app.graph.queries.
Tests:
- Permission checks (viewer vs analyst vs admin for simulate & save_investigation)
- Finding ID validation (^([a-f0-9]{12})$) across all relevant tools
- save_investigation refused when save_allowed is False
- save_investigation ignores model-supplied verdicts and recomputes deterministically
- save_investigation truncates summary to 1000 characters
- list_findings returns top 25 trimmed findings
- simulate validates change types and parameters
- Never raises on unexpected exceptions (returns {"ok": false, "error": ...})
- TOOL_SCHEMAS and REGISTRY completeness
"""

from __future__ import annotations

from typing import Any

import pytest
from app.agent.tools import (
    REGISTRY,
    TOOL_SCHEMAS,
    ToolContext,
    choke_points,
    list_findings,
    recall,
    save_investigation,
    score_finding,
    simulate,
    trace_path,
)
from app.graph import queries


@pytest.fixture()
def base_ctx() -> ToolContext:
    """Default analyst context with save allowed."""
    return ToolContext(
        repo_id="test-repo-123",
        user_role="analyst",
        user_email="analyst@example.com",
        save_allowed=True,
        session_id="sess-abc",
    )


def test_list_findings_returns_top_25(monkeypatch: pytest.MonkeyPatch, base_ctx: ToolContext) -> None:
    """list_findings returns at most 25 findings with specific keys."""
    fake_findings = [
        {
            "id": f"find_{i:04d}",
            "vuln_id": f"GHSA-{i}",
            "package": f"pkg-{i}",
            "version": "1.0.0",
            "severity": "HIGH",
            "verdict": "reachable_in_model",
            "score": 85 - i,
            "status": "open",
            "extra_ignored_key": "should_be_stripped",
        }
        for i in range(40)
    ]

    monkeypatch.setattr(queries, "list_findings", lambda repo_id: fake_findings)

    res = list_findings(base_ctx)
    assert res["ok"] is True
    assert res["count"] == 25
    assert len(res["findings"]) == 25

    first = res["findings"][0]
    expected_keys = {"id", "vuln_id", "package", "version", "severity", "verdict", "score", "status"}
    assert set(first.keys()) == expected_keys
    assert "extra_ignored_key" not in first


def test_id_validation_across_tools(base_ctx: ToolContext) -> None:
    """Invalid 12-char hex finding_id is rejected by all relevant tools."""
    invalid_ids = ["not-hex-id", "123", "a1b2c3d4e5f67", "A1B2C3D4E5F6", "", None]

    for bad_id in invalid_ids:
        r_trace = trace_path(base_ctx, finding_id=bad_id)  # type: ignore[arg-type]
        assert r_trace["ok"] is False
        assert "Invalid finding_id" in r_trace["error"]

        r_score = score_finding(base_ctx, finding_id=bad_id)  # type: ignore[arg-type]
        assert r_score["ok"] is False
        assert "Invalid finding_id" in r_score["error"]

        r_save = save_investigation(base_ctx, finding_id=bad_id, summary="summary")  # type: ignore[arg-type]
        assert r_save["ok"] is False
        assert "Invalid finding_id" in r_save["error"]

        if bad_id:  # recall & simulate allow None/omitted, but reject malformed non-empty IDs
            r_recall = recall(base_ctx, finding_id=bad_id)  # type: ignore[arg-type]
            assert r_recall["ok"] is False
            assert "Invalid finding_id" in r_recall["error"]

            r_sim = simulate(base_ctx, changes=[{"type": "add_auth", "entrypoint_id": "ep1"}], finding_id=bad_id)  # type: ignore[arg-type]
            assert r_sim["ok"] is False
            assert "Invalid finding_id" in r_sim["error"]


def test_trace_path_and_score_finding_success(
    monkeypatch: pytest.MonkeyPatch,
    base_ctx: ToolContext,
) -> None:
    """trace_path returns trace + score_breakdown, score_finding returns breakdown only."""
    valid_id = "a1b2c3d4e5f6"

    def mock_trace_paths(repo_id: str, fid: str) -> dict[str, Any]:
        return {
            "finding_id": fid,
            "verdict": "reachable_in_model",
            "reason": "Reachable from 2 public entrypoint(s)",
            "paths": [{"entrypoint": "GET /api"}],
            "reaching_entrypoints": 2,
            "total_public_entrypoints": 4,
            "blind_spots": [],
            "searched_scope": {},
        }

    def mock_get_finding(repo_id: str, fid: str) -> dict[str, Any]:
        return {"id": fid, "severity": "CRITICAL"}

    monkeypatch.setattr(queries, "trace_paths", mock_trace_paths)
    monkeypatch.setattr(queries, "get_finding", mock_get_finding)

    # 1. Test trace_path
    r_trace = trace_path(base_ctx, finding_id=valid_id)
    assert r_trace["ok"] is True
    assert r_trace["verdict"] == "reachable_in_model"
    assert "score_breakdown" in r_trace
    # reach=1.0 (0.5), severity=1.0 (0.3), exposure=0.5 (0.1) -> 0.9 -> 90
    assert r_trace["score_breakdown"]["score"] == 90
    assert r_trace["score"] == 90

    # 2. Test score_finding
    r_score = score_finding(base_ctx, finding_id=valid_id)
    assert r_score["ok"] is True
    assert r_score["finding_id"] == valid_id
    assert r_score["score_breakdown"]["score"] == 90
    assert "paths" not in r_score


def test_choke_points(monkeypatch: pytest.MonkeyPatch, base_ctx: ToolContext) -> None:
    """choke_points returns top choke point packages."""
    monkeypatch.setattr(
        queries,
        "choke_points",
        lambda repo_id: [{"package": "requests", "version": "2.25.0", "clears_findings": 4}],
    )
    res = choke_points(base_ctx)
    assert res["ok"] is True
    assert res["count"] == 1
    assert res["choke_points"][0]["package"] == "requests"


def test_simulate_permissions_and_validation(
    monkeypatch: pytest.MonkeyPatch,
    base_ctx: ToolContext,
) -> None:
    """simulate requires analyst or admin, and validates change structures."""
    # 1. Viewer is forbidden
    viewer_ctx = ToolContext(repo_id="r1", user_role="viewer")
    r_viewer = simulate(viewer_ctx, changes=[{"type": "add_auth", "entrypoint_id": "ep1"}])
    assert r_viewer["ok"] is False
    assert r_viewer["error"] == "forbidden"

    # 2. Analyst / Admin allowed
    monkeypatch.setattr(
        queries,
        "simulate",
        lambda repo_id, finding_id, changes: {"before": "reachable_in_model", "after": "no_path_found", "changed": []},
    )

    valid_changes = [{"type": "add_auth", "entrypoint_id": "ep1"}]
    r_analyst = simulate(base_ctx, changes=valid_changes)
    assert r_analyst["ok"] is True
    assert r_analyst["before"] == "reachable_in_model"

    # 3. Validation: empty changes
    r_empty = simulate(base_ctx, changes=[])
    assert r_empty["ok"] is False

    # 4. Validation: add_auth missing entrypoint_id
    r_bad_auth = simulate(base_ctx, changes=[{"type": "add_auth"}])
    assert r_bad_auth["ok"] is False
    assert "entrypoint_id" in r_bad_auth["error"]

    # 5. Validation: remove_import missing package_id
    r_bad_imp = simulate(base_ctx, changes=[{"type": "remove_import", "module_id": "app.api"}])
    assert r_bad_imp["ok"] is False
    assert "package_id" in r_bad_imp["error"]

    # 6. Validation: invalid change type
    r_bad_type = simulate(base_ctx, changes=[{"type": "unknown_action"}])
    assert r_bad_type["ok"] is False
    assert "invalid type" in r_bad_type["error"]


def test_save_investigation_refused_when_save_not_allowed(base_ctx: ToolContext) -> None:
    """save_investigation is refused if ctx.save_allowed is False."""
    no_save_ctx = ToolContext(
        repo_id="r1",
        user_role="analyst",
        save_allowed=False,
    )
    res = save_investigation(no_save_ctx, finding_id="a1b2c3d4e5f6", summary="test")
    assert res["ok"] is False
    assert "disabled" in res["error"].lower()


def test_save_investigation_role_permissions(base_ctx: ToolContext) -> None:
    """save_investigation requires analyst or admin."""
    viewer_ctx = ToolContext(
        repo_id="r1",
        user_role="viewer",
        save_allowed=True,
    )
    res = save_investigation(viewer_ctx, finding_id="a1b2c3d4e5f6", summary="test")
    assert res["ok"] is False
    assert res["error"] == "forbidden"


def test_save_investigation_ignores_model_supplied_verdicts(
    monkeypatch: pytest.MonkeyPatch,
    base_ctx: ToolContext,
) -> None:
    """save_investigation recomputes verdict & score deterministically, ignoring any caller kwargs."""
    valid_id = "a1b2c3d4e5f6"
    captured_save_args: dict[str, Any] = {}

    def mock_trace_paths(repo_id: str, fid: str) -> dict[str, Any]:
        return {
            "finding_id": fid,
            "verdict": "reachable_in_model",
            "paths": [{"entrypoint": "GET /"}],
            "reaching_entrypoints": 5,
            "total_public_entrypoints": 5,
        }

    def mock_get_finding(repo_id: str, fid: str) -> dict[str, Any]:
        return {"id": fid, "severity": "CRITICAL"}

    def mock_save_investigation(
        repo_id: str,
        finding_id: str,
        by: str,
        verdict: str,
        score: int,
        path_json: str,
        summary: str,
        session_id: str,
    ) -> str:
        captured_save_args.update({
            "repo_id": repo_id,
            "finding_id": finding_id,
            "by": by,
            "verdict": verdict,
            "score": score,
            "path_json": path_json,
            "summary": summary,
            "session_id": session_id,
        })
        return "inv-12345678"

    monkeypatch.setattr(queries, "trace_paths", mock_trace_paths)
    monkeypatch.setattr(queries, "get_finding", mock_get_finding)
    monkeypatch.setattr(queries, "save_investigation", mock_save_investigation)

    # Pass malicious/hallucinated verdict="no_path_found" and score=0 as model might try to pass
    res = save_investigation(
        base_ctx,
        finding_id=valid_id,
        summary="Verified reachable critical vulnerability.",
        verdict="no_path_found",
        score=0,
    )

    assert res["ok"] is True
    assert res["investigation_id"] == "inv-12345678"
    assert res["verdict"] == "reachable_in_model"
    assert res["score"] == 100

    # Ensure what was actually stored in graph DB was the recomputed true verdict and score
    assert captured_save_args["verdict"] == "reachable_in_model"
    assert captured_save_args["score"] == 100
    assert captured_save_args["by"] == "analyst@example.com"


def test_save_investigation_truncates_summary(
    monkeypatch: pytest.MonkeyPatch,
    base_ctx: ToolContext,
) -> None:
    """Summary is truncated to 1000 characters."""
    valid_id = "a1b2c3d4e5f6"
    stored_summary: list[str] = []

    monkeypatch.setattr(
        queries,
        "trace_paths",
        lambda r, f: {"verdict": "unknown", "reaching_entrypoints": 0, "total_public_entrypoints": 1, "paths": []},
    )
    monkeypatch.setattr(queries, "get_finding", lambda r, f: {"severity": "LOW"})
    monkeypatch.setattr(
        queries,
        "save_investigation",
        lambda repo_id, finding_id, by, verdict, score, path_json, summary, session_id: stored_summary.append(summary) or "inv-1",
    )

    long_summary = "A" * 1500
    res = save_investigation(base_ctx, finding_id=valid_id, summary=long_summary)
    assert res["ok"] is True
    assert len(stored_summary[0]) == 1000
    assert len(res["summary"]) == 1000


def test_recall_tool(monkeypatch: pytest.MonkeyPatch, base_ctx: ToolContext) -> None:
    """recall calls queries.recall and returns investigations and decisions."""
    monkeypatch.setattr(
        queries,
        "recall",
        lambda repo_id, fid: {"investigations": [{"id": "inv1"}], "decisions": [{"id": "dec1"}]},
    )
    res = recall(base_ctx, finding_id="a1b2c3d4e5f6")
    assert res["ok"] is True
    assert len(res["investigations"]) == 1
    assert len(res["decisions"]) == 1


def test_tool_never_raises_on_internal_exception(
    monkeypatch: pytest.MonkeyPatch,
    base_ctx: ToolContext,
) -> None:
    """Tools return {'ok': False, 'error': ...} instead of raising when a query fails."""
    def crash(*args: Any, **kwargs: Any) -> None:
        raise RuntimeError("Database connection lost")

    monkeypatch.setattr(queries, "list_findings", crash)
    monkeypatch.setattr(queries, "trace_paths", crash)

    r_list = list_findings(base_ctx)
    assert r_list["ok"] is False
    assert "Database connection lost" in r_list["error"]

    r_trace = trace_path(base_ctx, finding_id="a1b2c3d4e5f6")
    assert r_trace["ok"] is False
    assert "Database connection lost" in r_trace["error"]


def test_tool_schemas_and_registry() -> None:
    """TOOL_SCHEMAS and REGISTRY contain all seven Contract Section 10 tools."""
    expected_tools = {
        "list_findings",
        "trace_path",
        "score_finding",
        "choke_points",
        "simulate",
        "recall",
        "save_investigation",
    }

    assert set(REGISTRY.keys()) == expected_tools
    for func in REGISTRY.values():
        assert callable(func)

    schema_names = {s["function"]["name"] for s in TOOL_SCHEMAS}
    assert schema_names == expected_tools

    for s in TOOL_SCHEMAS:
        fn = s["function"]
        assert fn["name"] in expected_tools
        assert isinstance(fn["description"], str) and len(fn["description"]) > 10
        assert "parameters" in fn
        assert fn["parameters"]["type"] == "object"
