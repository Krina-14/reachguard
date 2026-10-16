"""
ReachGuard — Agent Execution Loop.

Orchestrates multi-turn tool calling, explanation fallbacks, and deterministic resolution.
Implements:
1. Mode 'llm_tools': Native multi-turn tool calling (up to 4 rounds, max 6 tool calls).
2. Mode 'llm_explain': Model explanation from pre-executed tool results.
3. Mode 'deterministic': Fully offline template-based answer generation via fallback.py.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from typing import Any

from app.agent.fallback import build_fallback_answer
from app.agent.llm import LLMClient, LLMUnavailable, get_client
from app.agent.planner import extract_referenced_finding, plan_intent
from app.agent.prompts import EXPLAIN_USER_TEMPLATE, SYSTEM_PROMPT
from app.agent.tools import REGISTRY, TOOL_SCHEMAS, ToolContext, recall

logger = logging.getLogger(__name__)


@dataclass
class AgentResult:
    """Standardized response from the agent execution loop."""

    answer: str
    mode: str  # "llm_tools" | "llm_explain" | "deterministic"
    tool_calls: list[dict[str, Any]]
    evidence: dict[str, Any]
    grounded: bool = True
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "answer": self.answer,
            "mode": self.mode,
            "tool_calls": self.tool_calls,
            "evidence": self.evidence,
            "grounded": self.grounded,
            "warnings": self.warnings,
        }


def _format_tool_summary(name: str, args: dict[str, Any], res: dict[str, Any]) -> str:
    """Format short fixed-format summary for tool calls."""
    if name == "list_findings":
        count = res.get("count", len(res.get("findings", [])))
        return f"list_findings(): {count} findings"
    if name == "trace_path":
        fid = args.get("finding_id", "")
        verdict = res.get("verdict", "unknown")
        paths_cnt = len(res.get("paths", []))
        return f"trace_path({fid}): {verdict}, {paths_cnt} paths"
    if name == "score_finding":
        fid = args.get("finding_id", "")
        score = res.get("score", 0)
        return f"score_finding({fid}): score {score}"
    if name == "choke_points":
        cnt = len(res.get("choke_points", []))
        return f"choke_points(): {cnt} packages"
    if name == "simulate":
        changed_cnt = len(res.get("changed", []))
        return f"simulate(): {changed_cnt} changed"
    if name == "recall":
        fid = args.get("finding_id", "all")
        invs = len(res.get("investigations", []))
        decs = len(res.get("decisions", []))
        return f"recall({fid}): {invs} investigations, {decs} decisions"
    if name == "save_investigation":
        fid = args.get("finding_id", "")
        inv_id = res.get("investigation_id", "")
        return f"save_investigation({fid}): saved {inv_id}"
    return f"{name}(): ok={res.get('ok', True)}"


def _update_evidence(evidence: dict[str, Any], name: str, res: dict[str, Any]) -> None:
    """Accumulate tool results into structured evidence."""
    if name == "list_findings":
        for f in res.get("findings", []):
            if f not in evidence["findings"]:
                evidence["findings"].append(f)
    elif name == "trace_path":
        evidence["traces"].append(res)
    elif name == "recall":
        evidence["memory"].append(res)


def _check_guardrails(answer: str) -> tuple[bool, str | None]:
    """Verify that the model adheres to core safety rules."""
    # Prohibit claims that a package or finding is safe
    if re.search(r"\b(is safe|are safe|package is safe|it is safe)\b", answer, re.IGNORECASE):
        return False, "Answer claimed a package is safe (prohibited)."
    return True, None


def run_agent(
    ctx: ToolContext,
    message: str,
    history: list[dict[str, str]] | None = None,
    client: LLMClient | None = None,
) -> AgentResult:
    """Run the triage agent with fallback hierarchy:

    1. llm_tools: Autonomous tool invocation using OpenAI tool calling.
    2. llm_explain: Planner-driven tool execution with LLM synthesis.
    3. deterministic: Rule-based template generation without LLM.
    """
    llm = client or get_client()
    evidence: dict[str, Any] = {"findings": [], "traces": [], "memory": []}
    executed_tools: list[dict[str, Any]] = []
    warnings: list[str] = []

    # Ensure memory context is always pre-seeded if a finding is referenced
    referenced_fid = extract_referenced_finding(ctx.repo_id, message)
    if referenced_fid:
        mem_res = recall(ctx, finding_id=referenced_fid)
        _update_evidence(evidence, "recall", mem_res)

    # Check LLM health
    try:
        h = llm.health()
        llm_reachable = bool(h.get("reachable"))
    except Exception as exc:  # noqa: BLE001
        logger.warning("LLM health check raised error: %s", exc)
        llm_reachable = False

    # ─────────────────────────────────────────────────────────────
    # Stage 1: Try mode 'llm_tools'
    # ─────────────────────────────────────────────────────────────
    if llm_reachable:
        recent_history = history[-6:] if history else []
        messages: list[dict[str, Any]] = [{"role": "system", "content": SYSTEM_PROMPT}]
        messages.extend(recent_history)
        messages.append({"role": "user", "content": message})

        total_tool_calls = 0
        made_valid_call_round_0 = False

        try:
            for round_idx in range(4):
                resp = llm.chat(messages=messages, tools=TOOL_SCHEMAS)
                tool_calls_requested = resp.get("tool_calls", [])

                if not tool_calls_requested:
                    # Model answered with content
                    content = resp.get("content") or ""
                    if round_idx == 0:
                        # Model made zero tool calls on first round -> switch to llm_explain
                        logger.info("Model made zero tool calls on round 0; switching to llm_explain")
                        break

                    # Validate guardrails
                    passed_guardrail, warn_msg = _check_guardrails(content)
                    if not passed_guardrail and warn_msg:
                        warnings.append(warn_msg)
                        logger.warning("Guardrail failed in llm_tools: %s", warn_msg)
                        break

                    return AgentResult(
                        answer=content,
                        mode="llm_tools",
                        tool_calls=executed_tools,
                        evidence=evidence,
                        grounded=True,
                        warnings=warnings,
                    )

                # Process tool calls
                round_tool_responses: list[dict[str, Any]] = []
                for tc in tool_calls_requested:
                    if total_tool_calls >= 6:
                        break
                    total_tool_calls += 1

                    name = tc.get("name", "")
                    raw_args = tc.get("arguments", {})
                    args = raw_args if isinstance(raw_args, dict) else {}

                    func = REGISTRY.get(name)
                    if not func:
                        err_res = {"ok": False, "error": f"Unknown tool: '{name}'"}
                        round_tool_responses.append({
                            "role": "tool",
                            "name": name,
                            "content": json.dumps(err_res),
                        })
                        executed_tools.append({
                            "name": name,
                            "args": args,
                            "ok": False,
                            "summary": f"{name}(): unknown tool",
                        })
                    else:
                        if round_idx == 0:
                            made_valid_call_round_0 = True
                        res = func(ctx, **args)
                        _update_evidence(evidence, name, res)
                        summary_str = _format_tool_summary(name, args, res)
                        executed_tools.append({
                            "name": name,
                            "args": args,
                            "ok": res.get("ok", True),
                            "summary": summary_str,
                        })
                        round_tool_responses.append({
                            "role": "tool",
                            "name": name,
                            "content": json.dumps(res),
                        })

                if round_idx == 0 and not made_valid_call_round_0:
                    logger.info("No valid tool calls in round 0; switching to llm_explain")
                    break

                # Add assistant message and tool outputs for next round
                messages.append({
                    "role": "assistant",
                    "content": resp.get("content"),
                    "tool_calls": [
                        {
                            "type": "function",
                            "function": {"name": tc.get("name"), "arguments": json.dumps(tc.get("arguments", {}))},
                        }
                        for tc in tool_calls_requested
                    ],
                })
                messages.extend(round_tool_responses)

        except (LLMUnavailable, Exception) as exc:  # noqa: BLE001
            logger.warning("Error in llm_tools stage: %s", exc)

    # ─────────────────────────────────────────────────────────────
    # Stage 2: Mode 'llm_explain' (Planner tool execution + synthesis)
    # ─────────────────────────────────────────────────────────────
    if llm_reachable:
        try:
            planned = plan_intent(ctx, message)

            # Check for clarify question
            if planned and planned[0][0] == "clarify_whatif":
                return AgentResult(
                    answer="To simulate what-if changes, please specify the entrypoint to protect (e.g., 'add auth to /api/login') or the module and package import to remove.",
                    mode="deterministic",
                    tool_calls=[],
                    evidence=evidence,
                    grounded=True,
                )

            tool_results_for_explain: list[dict[str, Any]] = []
            for tool_name, args in planned:
                func = REGISTRY.get(tool_name)
                if func:
                    res = func(ctx, **args)
                    _update_evidence(evidence, tool_name, res)
                    summary_str = _format_tool_summary(tool_name, args, res)
                    executed_tools.append({
                        "name": tool_name,
                        "args": args,
                        "ok": res.get("ok", True),
                        "summary": summary_str,
                    })
                    tool_results_for_explain.append({tool_name: res})

            explain_user_content = EXPLAIN_USER_TEMPLATE.format(
                message=message,
                tool_results_json=json.dumps(tool_results_for_explain, indent=2),
            )

            explain_messages = [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": explain_user_content},
            ]

            resp = llm.chat(messages=explain_messages, tools=None)
            content = resp.get("content")
            if content:
                passed_guardrail, warn_msg = _check_guardrails(content)
                if not passed_guardrail and warn_msg:
                    warnings.append(warn_msg)
                else:
                    return AgentResult(
                        answer=content,
                        mode="llm_explain",
                        tool_calls=executed_tools,
                        evidence=evidence,
                        grounded=True,
                        warnings=warnings,
                    )
        except (LLMUnavailable, Exception) as exc:  # noqa: BLE001
            logger.warning("Error in llm_explain stage: %s", exc)

    # ─────────────────────────────────────────────────────────────
    # Stage 3: Mode 'deterministic' (Zero network fallback)
    # ─────────────────────────────────────────────────────────────
    tool_results_for_fallback: list[dict[str, Any]] = []
    if not executed_tools:
        planned = plan_intent(ctx, message)
        for tool_name, args in planned:
            func = REGISTRY.get(tool_name)
            if func:
                res = func(ctx, **args)
                _update_evidence(evidence, tool_name, res)
                summary_str = _format_tool_summary(tool_name, args, res)
                executed_tools.append({
                    "name": tool_name,
                    "args": args,
                    "ok": res.get("ok", True),
                    "summary": summary_str,
                })
                tool_results_for_fallback.append(res)

    fallback_answer = build_fallback_answer(
        evidence=evidence,
        tool_results=tool_results_for_fallback,
    )

    return AgentResult(
        answer=fallback_answer,
        mode="deterministic",
        tool_calls=executed_tools,
        evidence=evidence,
        grounded=True,
        warnings=warnings,
    )
