"""
ReachGuard — Deterministic Intent Planner.

Implements rule-based, deterministic intent routing without an LLM.
Extracts finding IDs and package names, detects user intent via keywords,
and returns an ordered list of (tool_name, args) tuples.
"""

from __future__ import annotations

import re
from typing import Any

from app.agent.tools import ToolContext
from app.graph import queries

FINDING_ID_PATTERN = re.compile(r"\b[a-f0-9]{12}\b", re.IGNORECASE)
OFF_TOPIC_PATTERN = re.compile(
    r"\b(weather|forecast|rain|temperature|recipe|joke|sports|movie|song|poem|crypto|stock\s*price)\b",
    re.IGNORECASE,
)


def is_off_topic(text: str) -> bool:
    """Return True if message is unrelated to security or code repository analysis."""
    lower = text.lower()
    security_keywords = ("finding", "vuln", "cve", "ghsa", "package", "repo", "reach", "auth", "import", "fix", "path")
    if any(sk in lower for sk in security_keywords):
        return False
    return bool(OFF_TOPIC_PATTERN.search(lower))


def extract_finding_ids(text: str) -> list[str]:
    """Extract all 12-character hex finding IDs from text."""
    return [fid.lower() for fid in FINDING_ID_PATTERN.findall(text)]


def extract_referenced_finding(
    repo_id: str,
    text: str,
    all_findings: list[dict[str, Any]] | None = None,
) -> str | None:
    """Find the referenced finding ID by explicit ID or package name."""
    explicit_ids = extract_finding_ids(text)
    if explicit_ids:
        return explicit_ids[0]

    # Check package names against findings in the repo
    if all_findings is None:
        try:
            all_findings = queries.list_findings(repo_id)
        except Exception:  # noqa: BLE001
            all_findings = []

    lower_text = text.lower()
    for f in all_findings:
        pkg = (f.get("package") or "").lower()
        if pkg and re.search(r"\b" + re.escape(pkg) + r"\b", lower_text):
            return str(f.get("id"))

    return None


def plan_intent(
    ctx: ToolContext,
    message: str,
) -> list[tuple[str, dict[str, Any]]]:
    """Analyze user message and return an ordered sequence of (tool_name, kwargs) calls.

    Keyword routing rules:
    - 'why' / 'rank' / 'prioritiz':
      [list_findings, recall, trace_path (referenced or top), score_finding]
    - 'fix first' / 'priority' / 'what should':
      [list_findings, choke_points, trace_path for top 3]
    - 'what if' / 'add auth' / 'remove':
      [simulate] only when a finding ID and entrypoint/module is identifiable, else clarify
    - 'before' / 'history' / 'seen' / 'decid' / 'remember':
      [recall, then trace_path]
    - 'reachable' / 'exploit' / 'path':
      [trace_path] (with recall to ensure memory context)
    - default:
      [list_findings]
    """
    text = message.lower()

    # Check for off-topic non-security queries
    if is_off_topic(message):
        return [("off_topic", {})]

    # Pre-fetch findings to match packages or resolve top findings
    try:
        findings = queries.list_findings(ctx.repo_id)
    except Exception:  # noqa: BLE001
        findings = []

    target_fid = extract_referenced_finding(ctx.repo_id, message, all_findings=findings)
    if not target_fid and findings:
        target_fid = str(findings[0].get("id"))

    # 1. "why" / "rank" / "prioritiz"
    if any(kw in text for kw in ("why", "rank", "prioritiz")):
        plan: list[tuple[str, dict[str, Any]]] = [("list_findings", {})]
        if target_fid:
            plan.extend([
                ("recall", {"finding_id": target_fid}),
                ("trace_path", {"finding_id": target_fid}),
                ("score_finding", {"finding_id": target_fid}),
            ])
        else:
            plan.append(("recall", {}))
        return plan

    # 2. "fix first" / "priority" / "what should"
    if any(kw in text for kw in ("fix first", "priority", "what should")):
        plan = [("list_findings", {}), ("choke_points", {})]
        top_3 = findings[:3]
        for f in top_3:
            fid = f.get("id")
            if fid:
                plan.append(("trace_path", {"finding_id": str(fid)}))
        return plan

    # 3. "what if" / "add auth" / "remove"
    if any(kw in text for kw in ("what if", "add auth", "add_auth", "remove")):
        # Check for add_auth
        ep_match = re.search(r"\b(ep-[a-f0-9]+|[a-f0-9]{12}|/[a-zA-Z0-9_\-\/]+)\b", message)
        if any(kw in text for kw in ("add auth", "add_auth")) and ep_match:
            changes = [{"type": "add_auth", "entrypoint_id": ep_match.group(1)}]
            return [("simulate", {"changes": changes, "finding_id": target_fid})]

        # Check for remove_import
        mod_match = re.search(r"module\s+([a-zA-Z0-9_.]+)", message, re.IGNORECASE)
        pkg_match = re.search(r"package\s+([a-zA-Z0-9_\-@.]+)", message, re.IGNORECASE)
        if mod_match and pkg_match:
            changes = [
                {
                    "type": "remove_import",
                    "module_id": mod_match.group(1),
                    "package_id": pkg_match.group(1),
                }
            ]
            return [("simulate", {"changes": changes, "finding_id": target_fid})]

        # Not identifiable -> return clarification request
        return [("clarify_whatif", {})]

    # 4. "before" / "history" / "seen" / "decid" / "remember"
    if any(kw in text for kw in ("before", "history", "seen", "decid", "remember")):
        plan = [("recall", {"finding_id": target_fid} if target_fid else {})]
        if target_fid:
            plan.append(("trace_path", {"finding_id": target_fid}))
        return plan

    # 5. "reachable" / "exploit" / "path"
    if any(kw in text for kw in ("reachable", "exploit", "path")):
        if target_fid:
            return [
                ("recall", {"finding_id": target_fid}),
                ("trace_path", {"finding_id": target_fid}),
            ]
        return [("list_findings", {})]

    # If an explicit or referenced finding is mentioned, investigate that finding
    if target_fid and (
        extract_finding_ids(message)
        or any((f.get("package") or "").lower() in text for f in findings if f.get("package"))
    ):
        return [
            ("recall", {"finding_id": target_fid}),
            ("trace_path", {"finding_id": target_fid}),
            ("score_finding", {"finding_id": target_fid}),
        ]

    # Default
    return [("list_findings", {})]
