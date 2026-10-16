"""
Unit tests for ReachGuard Agent Loop, Planner, and Fallback.

Tests:
1. Mode 'llm_tools': Model returns tool calls, loop executes them, model provides final answer.
2. Mode 'llm_explain': Model returns zero tool calls on round 0, loop executes planned tools and asks model for explanation.
3. Mode 'deterministic': LLM is unreachable or raises LLMUnavailable; loop generates template answer via fallback.py.
4. Deterministic content validation:
   - For 'no_path_found' verdict, answer includes 'not proof of safety'.
   - Recalled decision is visibly present in the answer text.
5. Guardrail enforcement: Prohibits claims that a package is safe.
"""

from __future__ import annotations

from typing import Any

import pytest
from app.agent.loop import AgentResult, run_agent
from app.agent.tools import ToolContext
from app.graph import queries


class FakeLLMClient:
    """Mock LLMClient for unit testing without network dependencies."""

    def __init__(
        self,
        reachable: bool = True,
        chat_responses: list[dict[str, Any]] | None = None,
        should_raise: Exception | None = None,
    ) -> None:
        self.reachable = reachable
        self.chat_responses = list(chat_responses or [])
        self.should_raise = should_raise
        self.chat_calls: list[dict[str, Any]] = []

    def health(self) -> dict[str, Any]:
        return {
            "provider": "mock",
            "model": "mock-model",
            "reachable": self.reachable,
            "mode": "llm" if self.reachable else "deterministic",
        }

    def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        self.chat_calls.append({"messages": messages, "tools": tools})
        if self.should_raise:
            raise self.should_raise
        if self.chat_responses:
            return self.chat_responses.pop(0)
        return {"content": "Default mock response", "tool_calls": [], "raw_finish_reason": "stop"}


def test_llm_tools_mode_success(monkeypatch: pytest.MonkeyPatch) -> None:
    """Model requests a tool call, tool executes, model provides grounded final response."""
    valid_fid = "a1b2c3d4e5f6"

    # Mock queries.trace_paths and queries.get_finding
    monkeypatch.setattr(
        queries,
        "trace_paths",
        lambda repo_id, fid: {
            "finding_id": fid,
            "verdict": "reachable_in_model",
            "paths": [{"entrypoint": "GET /api/v1/resource"}],
            "reaching_entrypoints": 2,
            "total_public_entrypoints": 5,
        },
    )
    monkeypatch.setattr(queries, "get_finding", lambda r, f: {"severity": "HIGH", "package": "requests", "version": "2.25.0"})
    monkeypatch.setattr(queries, "recall", lambda r, f: {"investigations": [], "decisions": []})

    # Turn 1: model calls trace_path; Turn 2: model answers
    fake_client = FakeLLMClient(
        reachable=True,
        chat_responses=[
            {
                "content": None,
                "tool_calls": [{"name": "trace_path", "arguments": {"finding_id": valid_fid}}],
                "raw_finish_reason": "tool_calls",
            },
            {
                "content": f"Finding {valid_fid} is Reachable in model from GET /api/v1/resource with score 80.",
                "tool_calls": [],
                "raw_finish_reason": "stop",
            },
        ],
    )

    ctx = ToolContext(repo_id="test-repo", user_role="analyst")
    res: AgentResult = run_agent(ctx, f"Is finding {valid_fid} reachable?", client=fake_client)

    assert res.mode == "llm_tools"
    assert "Reachable in model" in res.answer
    assert len(res.tool_calls) == 1
    assert res.tool_calls[0]["name"] == "trace_path"
    assert res.tool_calls[0]["ok"] is True
    assert len(res.evidence["traces"]) == 1


def test_zero_tool_calls_falls_to_llm_explain(monkeypatch: pytest.MonkeyPatch) -> None:
    """When model outputs zero tool calls on round 0, loop switches to llm_explain."""
    valid_fid = "a1b2c3d4e5f6"

    monkeypatch.setattr(
        queries,
        "list_findings",
        lambda r: [{"id": valid_fid, "package": "urllib3", "version": "1.26.4", "severity": "CRITICAL", "verdict": "reachable_in_model", "score": 95, "status": "open"}],
    )
    monkeypatch.setattr(
        queries,
        "trace_paths",
        lambda r, f: {"finding_id": f, "verdict": "reachable_in_model", "reaching_entrypoints": 1, "total_public_entrypoints": 1, "paths": [{"entrypoint": "GET /"}]},
    )
    monkeypatch.setattr(queries, "get_finding", lambda r, f: {"severity": "CRITICAL"})
    monkeypatch.setattr(queries, "recall", lambda r, f: {"investigations": [], "decisions": []})

    # Response 1 (round 0 of llm_tools): zero tool calls
    # Response 2 (llm_explain synthesis): explanation based on provided JSON
    fake_client = FakeLLMClient(
        reachable=True,
        chat_responses=[
            {"content": "I am answering without calling any tools.", "tool_calls": []},
            {"content": f"Based on graph analysis, finding {valid_fid} in urllib3 is Reachable in model with score 95.", "tool_calls": []},
        ],
    )

    ctx = ToolContext(repo_id="test-repo", user_role="analyst")
    res = run_agent(ctx, f"Why is {valid_fid} ranked high?", client=fake_client)

    assert res.mode == "llm_explain"
    assert "Reachable in model" in res.answer
    assert any(tc["name"] == "list_findings" for tc in res.tool_calls)


def test_llm_unreachable_falls_to_deterministic(monkeypatch: pytest.MonkeyPatch) -> None:
    """When LLM is unreachable, run_agent generates answer via fallback.py."""
    valid_fid = "a1b2c3d4e5f6"

    monkeypatch.setattr(
        queries,
        "list_findings",
        lambda r: [{"id": valid_fid, "package": "flask", "version": "2.0.1", "severity": "HIGH", "verdict": "reachable_in_model", "score": 90, "status": "open"}],
    )
    monkeypatch.setattr(
        queries,
        "trace_paths",
        lambda r, f: {
            "finding_id": f,
            "verdict": "reachable_in_model",
            "reaching_entrypoints": 3,
            "total_public_entrypoints": 3,
            "paths": [{"nodes": [{"name": "GET /login"}, {"name": "app.views"}, {"name": "flask@2.0.1"}]}],
        },
    )
    monkeypatch.setattr(queries, "get_finding", lambda r, f: {"severity": "HIGH", "package": "flask", "version": "2.0.1"})
    monkeypatch.setattr(queries, "recall", lambda r, f: {"investigations": [], "decisions": []})

    fake_client = FakeLLMClient(reachable=False)

    ctx = ToolContext(repo_id="test-repo", user_role="viewer")
    res = run_agent(ctx, f"Check path for {valid_fid}", client=fake_client)

    assert res.mode == "deterministic"
    assert "Reachable in model" in res.answer
    assert "GET /login -> app.views -> flask@2.0.1" in res.answer
    assert "Review the first hop" in res.answer


def test_deterministic_no_proof_of_safety_and_recalled_decision(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """For 'no_path_found', answer includes 'not proof of safety' and decision text."""
    valid_fid = "b2c3d4e5f6a1"

    monkeypatch.setattr(
        queries,
        "list_findings",
        lambda r: [{"id": valid_fid, "package": "certifi", "version": "2020.12.5", "severity": "LOW", "verdict": "no_path_found", "score": 15, "status": "risk_accepted"}],
    )
    monkeypatch.setattr(
        queries,
        "trace_paths",
        lambda r, f: {
            "finding_id": f,
            "verdict": "no_path_found",
            "reaching_entrypoints": 0,
            "total_public_entrypoints": 4,
            "paths": [],
        },
    )
    monkeypatch.setattr(queries, "get_finding", lambda r, f: {"severity": "LOW", "package": "certifi", "version": "2020.12.5"})
    monkeypatch.setattr(
        queries,
        "recall",
        lambda r, f: {
            "investigations": [],
            "decisions": [
                {
                    "type": "accept_risk",
                    "by": "security_lead@reachguard.io",
                    "status": "approved",
                    "created_at": "2026-03-01T10:00:00Z",
                    "reason": "Compensating TLS termination WAF rule active.",
                }
            ],
        },
    )

    fake_client = FakeLLMClient(reachable=False)

    ctx = ToolContext(repo_id="test-repo", user_role="analyst")
    res = run_agent(ctx, f"Tell me about {valid_fid}", client=fake_client)

    assert res.mode == "deterministic"
    assert "No path found in model" in res.answer
    # Must contain the exact Contract Section 5 / 6 safety text
    assert "This is not proof of safety. It only means no path was found in the analyzed graph." in res.answer
    # Must contain decision text
    assert "Compensating TLS termination WAF rule active." in res.answer
    assert "security_lead@reachguard.io" in res.answer
    assert "Risk has been formally accepted" in res.answer


def test_guardrail_violation_falls_to_deterministic(monkeypatch: pytest.MonkeyPatch) -> None:
    """Model claiming a package is safe is intercepted by guardrails and falls back."""
    valid_fid = "a1b2c3d4e5f6"

    monkeypatch.setattr(
        queries,
        "list_findings",
        lambda r: [{"id": valid_fid, "package": "flask", "version": "2.0.1", "severity": "LOW", "verdict": "no_path_found", "score": 15}],
    )
    monkeypatch.setattr(
        queries,
        "trace_paths",
        lambda r, f: {"finding_id": f, "verdict": "no_path_found", "paths": []},
    )
    monkeypatch.setattr(queries, "get_finding", lambda r, f: {"severity": "LOW"})
    monkeypatch.setattr(queries, "recall", lambda r, f: {"investigations": [], "decisions": []})

    # Model attempts to say "This package is safe"
    fake_client = FakeLLMClient(
        reachable=True,
        chat_responses=[
            {
                "content": None,
                "tool_calls": [{"name": "trace_path", "arguments": {"finding_id": valid_fid}}],
            },
            {
                "content": "Don't worry, this package is safe because no path was found.",
                "tool_calls": [],
            },
            {
                "content": "Synthesized: package is safe.",
                "tool_calls": [],
            },
        ],
    )

    ctx = ToolContext(repo_id="test-repo", user_role="analyst")
    res = run_agent(ctx, f"Is {valid_fid} okay?", client=fake_client)

    # Should fall back to deterministic and warn
    assert res.mode == "deterministic"
    assert len(res.warnings) > 0
    assert "This is not proof of safety" in res.answer
