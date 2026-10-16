"""
ReachGuard — Deterministic Fallback Answer Generator.

Implements Contract Section 5, 6, 10:
Pure Python, template-based answer generation assembled strictly from tool results
without any network calls or LLM dependency.
"""

from __future__ import annotations

from typing import Any

from app.scoring import NO_PROOF_OF_SAFETY_TEXT, label_for_verdict


def format_path(path_dict: dict[str, Any]) -> str:
    """Format a single path into 'POST /x -> module a -> module b -> package p@v'."""
    nodes = path_dict.get("nodes", [])
    if not nodes:
        return path_dict.get("entrypoint", "")
    names = []
    for n in nodes:
        name = n.get("name") or n.get("id") or ""
        names.append(name)
    return " -> ".join(names)


def build_fallback_answer(
    evidence: dict[str, Any],
    tool_results: list[dict[str, Any]] | None = None,
) -> str:
    """Assemble a grounded, template-based answer from evidence and tool outputs.

    Components assembled:
    - Verdict label (Reachable in model / No path found in model / Unknown)
    - Path string ("POST /x -> module a -> package p@v")
    - Risk score and formula breakdown
    - Owner attribution
    - Recall memory ("Previously: <type> by <user> on <date>: <reason>")
    - Approved accept_risk decision visibility
    - "This is not proof of safety..." when no path was found
    - Actionable next steps based on reachability verdict
    """
    traces = evidence.get("traces", [])
    findings = evidence.get("findings", [])
    memory = evidence.get("memory", [])
    paragraphs: list[str] = []

    # 1. Answer based on primary trace
    if traces:
        trace = traces[0]
        fid = trace.get("finding_id", "")
        verdict = trace.get("verdict", "unknown")
        verdict_str = label_for_verdict(verdict)

        # Match finding details
        f_info = next((f for f in findings if f.get("id") == fid), {})
        pkg = f_info.get("package") or ""
        ver = f_info.get("version") or ""
        ident = f"Finding {fid} ({pkg}@{ver})".strip() if pkg else f"Finding {fid}"

        paragraphs.append(f"{ident} is {verdict_str}.")

        # Paths
        paths = trace.get("paths", [])
        if paths:
            path_str = format_path(paths[0])
            reaching_cnt = trace.get("reaching_entrypoints", len(paths))
            paragraphs.append(f"Reachable from {reaching_cnt} public entrypoint(s). Primary path: {path_str}.")

        # Score & formula
        score_bd = trace.get("score_breakdown")
        if not score_bd and f_info.get("score") is not None:
            paragraphs.append(f"Risk score is {f_info.get('score')}/100.")
        elif score_bd:
            score_val = score_bd.get("score", 0)
            formula = score_bd.get("formula", "")
            reach = score_bd.get("reach", 0.0)
            sev = score_bd.get("severity", 0.0)
            exp = score_bd.get("exposure", 0.0)
            paragraphs.append(
                f"Risk score is {score_val}/100 (formula: {formula}, reach: {reach}, severity: {sev}, exposure: {exp})."
            )

        # Owners
        owners = f_info.get("owners", [])
        if owners:
            paragraphs.append(f"Owned by: {', '.join(owners)}.")

        # Recall results & Decisions
        decisions: list[dict[str, Any]] = []
        investigations: list[dict[str, Any]] = []
        for m in memory:
            decisions.extend(m.get("decisions", []))
            investigations.extend(m.get("investigations", []))

        # Check for approved accept_risk
        has_approved_accept_risk = any(
            d.get("type") == "accept_risk" and d.get("status") == "approved"
            for d in decisions
        )
        if has_approved_accept_risk or f_info.get("status") == "risk_accepted":
            paragraphs.append("Status note: Risk has been formally accepted for this finding.")

        for d in decisions:
            d_type = d.get("type", "decision")
            d_by = d.get("by", "user")
            d_date = str(d.get("created_at", ""))[:10]
            d_reason = d.get("reason", "")
            paragraphs.append(f"Previously: {d_type} by {d_by} on {d_date}: {d_reason}")

        for inv in investigations:
            inv_by = inv.get("by", "analyst")
            inv_date = str(inv.get("created_at", ""))[:10]
            inv_summary = inv.get("summary", "")
            paragraphs.append(f"Previous investigation by {inv_by} on {inv_date}: {inv_summary}")

        # No proof of safety
        if verdict == "no_path_found":
            paragraphs.append(NO_PROOF_OF_SAFETY_TEXT)

        # Next steps
        if verdict == "reachable_in_model":
            fixed = f_info.get("fixed_versions", [])
            fixed_str = f" to {', '.join(fixed)}" if fixed else ""
            paragraphs.append(f"Recommended next step: Review the first hop and consider upgrading{fixed_str}.")
        elif verdict == "no_path_found":
            paragraphs.append("Recommended next step: Lower priority, but check blind spots.")
        else:
            paragraphs.append("Recommended next step: Inspect the listed dynamic imports.")

        return " ".join(paragraphs)

    # 2. Check for choke points tool results
    if tool_results:
        for tr in tool_results:
            cps = tr.get("choke_points")
            if cps:
                cp_items = [f"{cp.get('package')}@{cp.get('version', '')} (clears {cp.get('clears_findings', 0)} findings)" for cp in cps]
                return f"Top bottleneck packages to address first: {', '.join(cp_items)}."

            sim = tr.get("simulation")
            if sim:
                changed = sim.get("changed", [])
                if changed:
                    ch_desc = ", ".join(f"finding {c.get('finding_id')}: {c.get('from')} -> {c.get('to')}" for c in changed)
                    return f"Simulation result: Verdicts changed for {ch_desc}."
                return "Simulation result: No reachability verdicts were altered by the proposed change."

    # 3. Overview of findings
    if findings:
        top_list = [f"{f.get('id')} ({f.get('package')}, score: {f.get('score')}, {f.get('verdict')})" for f in findings[:5]]
        return f"Repository findings overview (top {len(top_list)}): {'; '.join(top_list)}."

    return "No findings or paths found in the analyzed graph."
