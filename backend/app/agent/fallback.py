"""
ReachGuard — Deterministic Fallback Answer Generator.

Implements Contract Section 5, 6, 10:
Pure Python, template-based answer generation assembled strictly from tool results
without any network calls or LLM dependency.
"""

from __future__ import annotations

import re
from typing import Any

from app.scoring import NO_PROOF_OF_SAFETY_TEXT, label_for_verdict


def format_path(path_dict: dict[str, Any], is_viewer: bool = False) -> str:
    """Format a single path into 'POST /x -> module a -> module b -> package p@v'."""
    nodes = path_dict.get("nodes", [])
    if not nodes:
        return path_dict.get("entrypoint", "")
    names = []
    for n in nodes:
        name = n.get("name") or n.get("id") or ""
        if is_viewer:
            # Strip any node labels or Cypher prefix from names
            name = re.sub(r"^\(?[a-zA-Z0-9_]*:(?:Module|Entrypoint|Package)\s*", "", name).strip()
        names.append(name)
    return " -> ".join(names)


def build_fallback_answer(
    evidence: dict[str, Any],
    tool_results: list[dict[str, Any]] | None = None,
    is_off_topic: bool = False,
    role: str | None = None,
) -> str:
    """Assemble a grounded, template-based answer from evidence and tool outputs.

    Components assembled:
    - Verdict label (Reachable in model / No path found in model / Unknown)
    - Handling for reason "no_entrypoints_detected" (plain statement, no safety implied)
    - Path string ("POST /x -> module a -> package p@v" or plain web route path)
    - Risk score and formula breakdown (simplified for viewer)
    - Owner attribution
    - Recall memory ("Previously: <type> by <user> on <date>: <reason>")
    - Approved accept_risk decision visibility
    - "This is not proof of safety..." when no path was found
    - Actionable next steps based on reachability verdict
    - Role-aware plain language when role is "viewer" (no Cypher or node-type jargon)
    """
    user_role = (role or evidence.get("user_role") or "analyst").lower()
    is_viewer = user_role == "viewer"

    if is_off_topic:
        scope_term = "code" if is_viewer else "graph"
        return (
            f"I am ReachGuard's triage assistant focused strictly on repository vulnerability reachability and {scope_term} analysis. "
            "I only handle repository security findings, call paths, and remediation priorities, and cannot assist with general topics such as weather."
        )

    traces = evidence.get("traces", [])
    findings = evidence.get("findings", [])
    memory = evidence.get("memory", [])
    paragraphs: list[str] = []

    # Check if reason is no_entrypoints_detected across traces, findings, or tool results
    has_no_entrypoints_reason = (
        any(t.get("reason") == "no_entrypoints_detected" for t in traces if isinstance(t, dict))
        or any(f.get("reason") == "no_entrypoints_detected" for f in findings if isinstance(f, dict))
        or bool(
            tool_results
            and any(
                isinstance(tr, dict)
                and (
                    tr.get("reason") == "no_entrypoints_detected"
                    or any(
                        isinstance(v, dict) and v.get("reason") == "no_entrypoints_detected"
                        for v in tr.values()
                    )
                )
                for tr in tool_results
            )
        )
    )

    # 1. Answer based on primary trace
    if traces:
        trace = traces[0]
        fid = trace.get("finding_id", "")
        verdict = trace.get("verdict", "unknown")
        verdict_str = label_for_verdict(verdict)
        trace_reason = trace.get("reason", "")

        # Match finding details
        f_info = next((f for f in findings if f.get("id") == fid), {})
        pkg = f_info.get("package") or ""
        ver = f_info.get("version") or ""
        ident = f"Finding {fid} ({pkg}@{ver})".strip() if pkg else f"Finding {fid}"

        paragraphs.append(f"{ident} is {verdict_str}.")

        # Handle reason "no_entrypoints_detected"
        if trace_reason == "no_entrypoints_detected" or (has_no_entrypoints_reason and verdict == "unknown"):
            paragraphs.append(
                "No web routes were found in this repository, so the tool cannot judge reachability. "
                "This is not proof of safety. It only means no web entrypoints were detected in the analyzed code."
            )
        else:
            # Paths
            paths = trace.get("paths", [])
            if paths:
                path_str = format_path(paths[0], is_viewer=is_viewer)
                reaching_cnt = trace.get("reaching_entrypoints", len(paths))
                if is_viewer:
                    paragraphs.append(f"Reachable from {reaching_cnt} public web route(s). Path: {path_str}.")
                else:
                    paragraphs.append(f"Reachable from {reaching_cnt} public entrypoint(s). Primary path: {path_str}.")

        # Score & formula
        score_bd = trace.get("score_breakdown")
        if not score_bd and f_info.get("score") is not None:
            paragraphs.append(f"Risk score is {f_info.get('score')}/100.")
        elif score_bd:
            score_val = score_bd.get("score", 0)
            if is_viewer:
                paragraphs.append(f"Risk score is {score_val}/100 based on reachability and severity.")
            else:
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
            d_status = d.get("status", "")
            status_tag = f" ({d_status})" if d_status else ""
            paragraphs.append(f"Prior decision: {d_type}{status_tag} by {d_by} on {d_date} with reason: '{d_reason}'.")

        for inv in investigations:
            inv_by = inv.get("by", "analyst")
            inv_date = str(inv.get("created_at", ""))[:10]
            inv_summary = inv.get("summary", "")
            paragraphs.append(f"Previous investigation by {inv_by} on {inv_date}: {inv_summary}")

        # Global pattern memory (latest hit)
        global_hits = evidence.get("global_recall", [])
        if not global_hits and trace.get("global_hits"):
            global_hits = trace.get("global_hits", [])
        if global_hits:
            hit = global_hits[0]
            d_type = hit.get("type", "decision")
            d_date = str(hit.get("approved_at") or hit.get("created_at") or "")[:10]
            d_user = hit.get("approved_by") or hit.get("by") or "admin"
            d_reason = hit.get("reason", "")
            paragraphs.append(f"This pattern was previously {d_type} on {d_date} by {d_user}: {d_reason}")

        # No proof of safety
        if verdict == "no_path_found":
            if is_viewer:
                paragraphs.append("This is not proof of safety. It only means no path was found in the analyzed code.")
            else:
                paragraphs.append(NO_PROOF_OF_SAFETY_TEXT)

        # Next steps
        if trace_reason == "no_entrypoints_detected":
            paragraphs.append("Recommended next step: Add public web routes (Flask or FastAPI) or inspect direct entrypoints.")
        elif verdict == "reachable_in_model":
            fixed = f_info.get("fixed_versions", [])
            fixed_str = f" to {', '.join(fixed)}" if fixed else ""
            paragraphs.append(f"Recommended next step: Review the first hop and consider upgrading{fixed_str}.")
        elif verdict == "no_path_found":
            if is_viewer:
                paragraphs.append("Recommended next step: Lower priority, but check uninspected code areas.")
            else:
                paragraphs.append("Recommended next step: Lower priority, but check blind spots.")
        else:
            if is_viewer:
                paragraphs.append("Recommended next step: Inspect dynamic or unresolved imports.")
            else:
                paragraphs.append("Recommended next step: Inspect the listed dynamic imports.")

        return " ".join(paragraphs)

    # 2. Memory / Global pattern response
    global_hits = evidence.get("global_recall", [])
    if memory or global_hits:
        decisions = []
        investigations = []
        for m in memory:
            decisions.extend(m.get("decisions", []))
            investigations.extend(m.get("investigations", []))

        mem_parts: list[str] = []
        has_approved_accept_risk = any(
            d.get("type") == "accept_risk" and d.get("status") == "approved"
            for d in decisions
        )
        if has_approved_accept_risk:
            mem_parts.append("Status note: Risk has been formally accepted for this finding.")

        for d in decisions:
            d_type = d.get("type", "decision")
            d_by = d.get("by", "user")
            d_date = str(d.get("created_at", ""))[:10]
            d_reason = d.get("reason", "")
            d_status = d.get("status", "")
            status_tag = f" ({d_status})" if d_status else ""
            mem_parts.append(f"Prior decision: {d_type}{status_tag} by {d_by} on {d_date} with reason: '{d_reason}'.")

        for inv in investigations:
            inv_by = inv.get("by", "analyst")
            inv_date = str(inv.get("created_at", ""))[:10]
            inv_summary = inv.get("summary", "")
            mem_parts.append(f"Previous investigation by {inv_by} on {inv_date}: {inv_summary}")

        if global_hits:
            hit = global_hits[0]
            d_type = hit.get("type", "decision")
            d_date = str(hit.get("approved_at") or hit.get("created_at") or "")[:10]
            d_user = hit.get("approved_by") or hit.get("by") or "admin"
            d_reason = hit.get("reason", "")
            mem_parts.append(f"This pattern was previously {d_type} on {d_date} by {d_user}: {d_reason}")

        if mem_parts:
            return " ".join(mem_parts)

    # 3. Check for choke points tool results
    if tool_results:
        for tr in tool_results:
            cps = tr.get("choke_points")
            if cps:
                cp_items = [f"{cp.get('package')}@{cp.get('version', '')} (clears {cp.get('clears_findings', 0)} findings)" for cp in cps]
                if is_viewer:
                    return f"Key dependencies to address first: {', '.join(cp_items)}."
                return f"Top bottleneck packages to address first: {', '.join(cp_items)}."

            sim = tr.get("simulation")
            if sim:
                changed = sim.get("changed", [])
                if changed:
                    ch_desc = ", ".join(f"finding {c.get('finding_id')}: {c.get('from')} -> {c.get('to')}" for c in changed)
                    return f"Simulation result: Verdicts changed for {ch_desc}."
                return "Simulation result: No reachability verdicts were altered by the proposed change."

            crit_mods = tr.get("modules")
            if crit_mods:
                if is_viewer:
                    mod_items = [
                        f"file '{m.get('module')}' (score: {int(m.get('score', 0))}, {m.get('note', '')})"
                        for m in crit_mods[:5]
                    ]
                    return f"Top critical files in the codebase: {'; '.join(mod_items)}."
                mod_items = [
                    f"module '{m.get('module')}' (score: {int(m.get('score', 0))}, {m.get('note', '')})"
                    for m in crit_mods[:5]
                ]
                return f"Top critical modules in the codebase: {'; '.join(mod_items)}."

            clusters = tr.get("clusters")
            if clusters:
                if is_viewer:
                    cluster_items = [
                        f"Group {c.get('cluster_id')} containing {len(c.get('modules', []))} file(s) and {len(c.get('findings', []))} finding(s)"
                        for c in clusters
                    ]
                    return f"Vulnerability groups: {'; '.join(cluster_items)}."
                cluster_items = [
                    f"Cluster {c.get('cluster_id')} containing {len(c.get('modules', []))} module(s) and {len(c.get('findings', []))} finding(s)"
                    for c in clusters
                ]
                return f"Vulnerability clusters (remediation batches): {'; '.join(cluster_items)}."

    # Evidence-based modules or clusters fallback
    evidence_mods = evidence.get("modules", [])
    if evidence_mods:
        if is_viewer:
            mod_items = [
                f"file '{m.get('module')}' (score: {int(m.get('score', 0))}, {m.get('note', '')})"
                for m in evidence_mods[:5]
            ]
            return f"Top critical files in the codebase: {'; '.join(mod_items)}."
        mod_items = [
            f"module '{m.get('module')}' (score: {int(m.get('score', 0))}, {m.get('note', '')})"
            for m in evidence_mods[:5]
        ]
        return f"Top critical modules in the codebase: {'; '.join(mod_items)}."

    evidence_clusters = evidence.get("clusters", [])
    if evidence_clusters:
        if is_viewer:
            cluster_items = [
                f"Group {c.get('cluster_id')} containing {len(c.get('modules', []))} file(s) and {len(c.get('findings', []))} finding(s)"
                for c in evidence_clusters
            ]
            return f"Vulnerability groups: {'; '.join(cluster_items)}."
        cluster_items = [
            f"Cluster {c.get('cluster_id')} containing {len(c.get('modules', []))} module(s) and {len(c.get('findings', []))} finding(s)"
            for c in evidence_clusters
        ]
        return f"Vulnerability clusters (remediation batches): {'; '.join(cluster_items)}."

    if has_no_entrypoints_reason:
        return (
            "No web routes were found in this repository, so the tool cannot judge reachability. "
            "This is not proof of safety. It only means no web entrypoints were detected in the analyzed code."
        )

    # 4. Overview of findings
    if findings:
        top_list = [f"{f.get('id')} ({f.get('package')}, score: {f.get('score')}, {f.get('verdict')})" for f in findings[:5]]
        return f"Repository findings overview (top {len(top_list)}): {'; '.join(top_list)}."

    if is_viewer:
        return "No findings or paths found in the analyzed code."
    return "No findings or paths found in the analyzed graph."
