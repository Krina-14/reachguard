"""
Tests for ReachGuard Grounding Guardrails (Contract Section 5, 6, 10).
"""

from __future__ import annotations

from unittest.mock import MagicMock

from app.agent.guardrails import check_grounding
from app.agent.loop import run_agent
from app.agent.tools import ToolContext


def test_made_up_id_caught() -> None:
    """A made-up finding ID must be caught and grounded=False."""
    evidence = {
        "findings": [
            {
                "id": "112233445566",
                "package": "requests",
                "version": "2.25.0",
                "score": 80,
                "verdict": "reachable_in_model",
            }
        ]
    }
    answer = "Finding a1b2c3d4e5f6 is reachable in model with score 80."
    res = check_grounding(answer, evidence=evidence, tool_results=[])
    assert res["grounded"] is False
    assert any("a1b2c3d4e5f6" in w for w in res["warnings"])


def test_wrong_score_caught() -> None:
    """A score that does not match tool results must be caught."""
    evidence = {
        "findings": [
            {
                "id": "112233445566",
                "package": "requests",
                "version": "2.25.0",
                "score": 80,
                "verdict": "reachable_in_model",
            }
        ]
    }
    answer = "Finding 112233445566 has score 95."
    res = check_grounding(answer, evidence=evidence, tool_results=[])
    assert res["grounded"] is False
    assert any("95" in w and "80" in w for w in res["warnings"])


def test_this_package_is_safe_caught() -> None:
    """Forbidden phrase 'this package is safe' must fail grounding."""
    evidence = {
        "findings": [
            {
                "id": "112233445566",
                "package": "requests",
                "version": "2.25.0",
                "score": 80,
                "verdict": "reachable_in_model",
            }
        ]
    }
    answer = "Finding 112233445566 has score 80. This package is safe."
    res = check_grounding(answer, evidence=evidence, tool_results=[])
    assert res["grounded"] is False
    assert any("is safe" in w.lower() for w in res["warnings"])


def test_forbidden_phrases_variations_caught() -> None:
    """All forbidden phrases must be caught case-insensitively."""
    forbidden_samples = [
        "This is not vulnerable to attack.",
        "There is no risk here.",
        "It is not exploitable in production.",
        "This alert is safe to ignore.",
        "I have applied the fix to entrypoint.",
        "I fixed the vulnerable import.",
        "I patched it yesterday.",
        "I upgraded requests to 2.28.0.",
    ]
    for sample in forbidden_samples:
        res = check_grounding(sample, evidence={}, tool_results=[])
        assert res["grounded"] is False, f"Failed to catch forbidden phrase in: {sample}"


def test_correct_answer_passes() -> None:
    """A correct answer strictly matching tool results must pass with 0 warnings."""
    evidence = {
        "findings": [
            {
                "id": "112233445566",
                "package": "requests",
                "version": "2.25.0",
                "score": 80,
                "verdict": "reachable_in_model",
            }
        ]
    }
    answer = "Finding 112233445566 in requests 2.25.0 has verdict Reachable in model with score 80."
    res = check_grounding(answer, evidence=evidence, tool_results=[])
    assert res["grounded"] is True
    assert res["warnings"] == []


def test_no_path_found_without_contradiction_passes() -> None:
    """A 'no path found' label without contradiction must pass."""
    # Case 1: Finding verdict is no_path_found
    evidence = {
        "findings": [
            {
                "id": "223344556677",
                "package": "urllib3",
                "version": "1.26.4",
                "score": 40,
                "verdict": "no_path_found",
            }
        ]
    }
    answer1 = (
        "Finding 223344556677 has verdict No path found in model with score 40. "
        "Note that no path found in model is not proof of safety."
    )
    res1 = check_grounding(answer1, evidence=evidence, tool_results=[])
    assert res1["grounded"] is True
    assert res1["warnings"] == []

    # Case 2: Finding verdict is reachable_in_model, and 'no path found' appears only in general disclaimer
    evidence2 = {
        "findings": [
            {
                "id": "112233445566",
                "package": "requests",
                "version": "2.25.0",
                "score": 80,
                "verdict": "reachable_in_model",
            }
        ]
    }
    answer2 = (
        "Finding 112233445566 has verdict Reachable in model with score 80. "
        "Remember that no path found in model is not proof of safety."
    )
    res2 = check_grounding(answer2, evidence=evidence2, tool_results=[])
    assert res2["grounded"] is True
    assert res2["warnings"] == []


def test_contradictory_verdict_caught() -> None:
    """A contradictory verdict label near a finding must be rejected."""
    evidence = {
        "findings": [
            {
                "id": "112233445566",
                "package": "requests",
                "version": "2.25.0",
                "score": 80,
                "verdict": "reachable_in_model",
            }
        ]
    }
    answer = "Finding 112233445566 has verdict No path found in model with score 80."
    res = check_grounding(answer, evidence=evidence, tool_results=[])
    assert res["grounded"] is False
    assert any("Contradictory verdict" in w for w in res["warnings"])


def test_generic_answer_warning_when_user_referenced_finding() -> None:
    """If answer mentions no IDs, grounded is True but warning added only if user referenced a finding."""
    evidence = {
        "findings": [
            {"id": "112233445566", "package": "requests", "version": "2.25.0", "score": 80}
        ]
    }
    generic_answer = "Vulnerabilities can be mitigated by reviewing dependency graphs and access controls."

    # User did NOT reference a finding: grounded=True, warnings=[]
    res_no_ref = check_grounding(
        generic_answer,
        evidence=evidence,
        tool_results=[],
        user_message="How do I improve security?",
    )
    assert res_no_ref["grounded"] is True
    assert res_no_ref["warnings"] == []

    # User DID reference a finding: grounded=True, warnings has 1 warning
    res_with_ref = check_grounding(
        generic_answer,
        evidence=evidence,
        tool_results=[],
        user_message="Can you analyze finding 112233445566?",
    )
    assert res_with_ref["grounded"] is True
    assert len(res_with_ref["warnings"]) == 1
    assert "112233445566" in res_with_ref["warnings"][0]


def test_package_version_mismatch_caught() -> None:
    """Package version that contradicts tool results must be rejected."""
    evidence = {
        "findings": [
            {
                "id": "112233445566",
                "package": "requests",
                "version": "2.25.0",
                "score": 80,
                "verdict": "reachable_in_model",
            }
        ]
    }
    answer = "Finding 112233445566 in requests 2.20.0 has score 80."
    res = check_grounding(answer, evidence=evidence, tool_results=[])
    assert res["grounded"] is False
    assert any("version" in w and "2.20.0" in w for w in res["warnings"])


def test_loop_retry_and_switch_to_deterministic() -> None:
    """Loop retries once on grounding failure; on second failure switches to deterministic mode."""
    ctx = ToolContext(
        repo_id="2f7632cb-9e39-43df-a04e-262547d06c72",
        user_role="analyst",
        user_email="analyst@example.com",
        save_allowed=True,
    )

    mock_findings = {
        "ok": True,
        "findings": [
            {
                "id": "112233445566",
                "package": "requests",
                "version": "2.25.0",
                "score": 80,
                "verdict": "reachable_in_model",
            }
        ],
    }

    from unittest.mock import patch

    # 1. Mock LLM that fails grounding on attempt 1, but fixes it on retry (attempt 2)
    mock_client = MagicMock()
    mock_client.health.return_value = {"reachable": True, "mode": "llm"}
    mock_client.chat.side_effect = [
        # Call 1: round 0 of llm_tools (no tool calls -> triggers switch to llm_explain)
        {"content": "Let me explain the finding."},
        # Call 2: llm_explain attempt 1 (bad answer claiming package is safe)
        {"content": "Finding 112233445566 has score 80. This package is safe."},
        # Call 3: llm_explain attempt 2 / retry (corrected answer)
        {"content": "Finding 112233445566 in requests 2.25.0 has verdict Reachable in model with score 80."},
    ]

    with (
        patch("app.agent.loop.plan_intent", return_value=[("list_findings", {})]),
        patch.dict("app.agent.loop.REGISTRY", {"list_findings": lambda _ctx, **_kw: mock_findings}),
    ):
        res = run_agent(ctx, "Analyze finding 112233445566", client=mock_client)
        assert res.mode == "llm_explain"
        assert res.grounded is True
        assert "This package is safe" not in res.answer
        assert "112233445566" in res.answer

    # 2. Mock LLM that fails grounding on BOTH attempts -> must switch to deterministic
    mock_client2 = MagicMock()
    mock_client2.health.return_value = {"reachable": True, "mode": "llm"}
    mock_client2.chat.side_effect = [
        # Call 1: round 0 of llm_tools -> triggers switch to llm_explain
        {"content": "Let me explain."},
        # Call 2: llm_explain attempt 1 -> fails grounding
        {"content": "Finding 112233445566 has score 80. This package is safe."},
        # Call 3: llm_explain attempt 2 -> still fails grounding
        {"content": "Finding 112233445566 has score 80. I fixed it and it is safe."},
    ]

    with (
        patch("app.agent.loop.plan_intent", return_value=[("list_findings", {})]),
        patch.dict("app.agent.loop.REGISTRY", {"list_findings": lambda _ctx, **_kw: mock_findings}),
    ):
        res2 = run_agent(ctx, "Analyze finding 112233445566", client=mock_client2)
        assert res2.mode == "deterministic"
        assert res2.grounded is True
