"""
ReachGuard — Agent Tool Definitions & Schema Registry.

Implements Contract Section 10:
Defines seven tools as plain Python functions callable by the LLM agent:
1. list_findings()
2. trace_path(finding_id)
3. score_finding(finding_id)
4. choke_points()
5. simulate(finding_id, changes)
6. recall(finding_id=None)
7. save_investigation(finding_id, summary)

Rules:
- Calls ONLY app.graph.queries and app.scoring.
- Each tool takes ToolContext + arguments.
- Returns a JSON-serializable dict and never raises to the caller ({"ok": false, "error": ...}).
- Validates every finding_id against ^[a-f0-9]{12}$.
- Exposes TOOL_SCHEMAS (OpenAI format) and REGISTRY (name -> function).
"""

from __future__ import annotations

import json
import logging
import re
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from app.graph import queries
from app.scoring import score as calculate_score

logger = logging.getLogger(__name__)

# ── Finding ID Regex Validator ──────────────────────────────────
FINDING_ID_RE = re.compile(r"^[a-f0-9]{12}$")


def _is_valid_finding_id(finding_id: Any) -> bool:
    """Return True if finding_id is a 12-character hex string."""
    if not isinstance(finding_id, str):
        return False
    return bool(FINDING_ID_RE.match(finding_id))


# ── Tool Execution Context ──────────────────────────────────────
@dataclass
class ToolContext:
    """Context provided to every tool invocation."""

    repo_id: str
    user_role: str = "viewer"
    user_email: str = ""
    save_allowed: bool = False
    session_id: str = ""


# ── 1. list_findings ───────────────────────────────────────────
def list_findings(ctx: ToolContext, **kwargs: Any) -> dict[str, Any]:
    """Return the top 25 findings from queries.list_findings.

    Fields per finding: (id, vuln_id, package, version, severity, verdict, score, status).
    """
    try:
        raw_findings = queries.list_findings(ctx.repo_id)
        top_25 = []
        for f in raw_findings[:25]:
            top_25.append({
                "id": f.get("id"),
                "vuln_id": f.get("vuln_id"),
                "package": f.get("package"),
                "version": f.get("version"),
                "severity": f.get("severity"),
                "verdict": f.get("verdict"),
                "score": f.get("score"),
                "status": f.get("status"),
            })
        return {
            "ok": True,
            "findings": top_25,
            "count": len(top_25),
        }
    except Exception as exc:  # noqa: BLE001
        logger.warning("Error in list_findings: %s", exc)
        return {"ok": False, "error": str(exc)}


# ── 2. trace_path ──────────────────────────────────────────────
def trace_path(ctx: ToolContext, finding_id: str = "", **kwargs: Any) -> dict[str, Any]:
    """Return queries.trace_paths result plus score breakdown from scoring.score."""
    if not _is_valid_finding_id(finding_id):
        return {
            "ok": False,
            "error": f"Invalid finding_id: '{finding_id}'. Expected 12-character hex string matching ^[a-f0-9]{{12}}$.",
        }

    try:
        trace = queries.trace_paths(ctx.repo_id, finding_id)
        verdict = trace.get("verdict", "unknown")
        reaching = trace.get("reaching_entrypoints", 0)
        total = trace.get("total_public_entrypoints", 0)

        # Retrieve severity from finding metadata
        f_info = queries.get_finding(ctx.repo_id, finding_id)
        severity = (f_info.get("severity") if f_info else "UNKNOWN") or "UNKNOWN"

        score_breakdown = calculate_score(
            verdict=verdict,
            severity=severity,
            reaching_entrypoints=reaching,
            total_public_entrypoints=total,
        )

        res = dict(trace)
        res["score_breakdown"] = score_breakdown
        res["score"] = score_breakdown["score"]
        res["ok"] = True

        # Check global recall for cross-repository memory
        pkg_name = (f_info.get("package") if f_info else "") or ""
        if pkg_name:
            global_hits = queries.global_recall(pkg_name)
            if global_hits:
                res["global_hits"] = global_hits
                res["global_recall"] = {
                    "ok": True,
                    "package_name": pkg_name,
                    "hits": global_hits,
                    "count": len(global_hits),
                }

        return res
    except Exception as exc:  # noqa: BLE001
        logger.warning("Error in trace_path(%s): %s", finding_id, exc)
        return {"ok": False, "error": str(exc)}


# ── 3. score_finding ───────────────────────────────────────────
def score_finding(ctx: ToolContext, finding_id: str = "", **kwargs: Any) -> dict[str, Any]:
    """Return deterministic score breakdown only."""
    if not _is_valid_finding_id(finding_id):
        return {
            "ok": False,
            "error": f"Invalid finding_id: '{finding_id}'. Expected 12-character hex string matching ^[a-f0-9]{{12}}$.",
        }

    try:
        trace = queries.trace_paths(ctx.repo_id, finding_id)
        verdict = trace.get("verdict", "unknown")
        reaching = trace.get("reaching_entrypoints", 0)
        total = trace.get("total_public_entrypoints", 0)

        f_info = queries.get_finding(ctx.repo_id, finding_id)
        severity = (f_info.get("severity") if f_info else "UNKNOWN") or "UNKNOWN"

        score_breakdown = calculate_score(
            verdict=verdict,
            severity=severity,
            reaching_entrypoints=reaching,
            total_public_entrypoints=total,
        )

        return {
            "ok": True,
            "finding_id": finding_id,
            "score_breakdown": score_breakdown,
            "score": score_breakdown["score"],
        }
    except Exception as exc:  # noqa: BLE001
        logger.warning("Error in score_finding(%s): %s", finding_id, exc)
        return {"ok": False, "error": str(exc)}


# ── 4. choke_points ────────────────────────────────────────────
def choke_points(ctx: ToolContext, **kwargs: Any) -> dict[str, Any]:
    """Return top choke point packages from queries.choke_points."""
    try:
        points = queries.choke_points(ctx.repo_id)
        return {
            "ok": True,
            "choke_points": points,
            "count": len(points),
        }
    except Exception as exc:  # noqa: BLE001
        logger.warning("Error in choke_points: %s", exc)
        return {"ok": False, "error": str(exc)}


# ── 5. simulate ────────────────────────────────────────────────
def simulate(
    ctx: ToolContext,
    changes: list[dict[str, Any]] | None = None,
    finding_id: str | None = None,
    **kwargs: Any,
) -> dict[str, Any]:
    """Validate changes and role, then call queries.simulate.

    Roles: analyst or admin required. Viewer gets {"ok": false, "error": "forbidden"}.
    Changes allowed:
    - {'type': 'add_auth', 'entrypoint_id': str}
    - {'type': 'remove_import', 'module_id': str, 'package_id': str}
    """
    if ctx.user_role not in ("analyst", "admin"):
        return {"ok": False, "error": "forbidden"}

    if finding_id and not _is_valid_finding_id(finding_id):
        return {
            "ok": False,
            "error": f"Invalid finding_id: '{finding_id}'. Expected 12-character hex string matching ^[a-f0-9]{{12}}$.",
        }

    if not isinstance(changes, list) or not changes:
        return {
            "ok": False,
            "error": "Changes must be a non-empty list of change objects.",
        }

    # Validate each change entry
    for idx, change in enumerate(changes):
        if not isinstance(change, dict):
            return {"ok": False, "error": f"Change item #{idx} must be a dictionary."}

        c_type = change.get("type")
        if c_type == "add_auth":
            eid = change.get("entrypoint_id")
            if not eid or not isinstance(eid, str) or not eid.strip():
                return {
                    "ok": False,
                    "error": f"Change #{idx} of type 'add_auth' requires a non-empty 'entrypoint_id'.",
                }
        elif c_type == "remove_import":
            mid = change.get("module_id")
            pid = change.get("package_id")
            if not mid or not isinstance(mid, str) or not mid.strip():
                return {
                    "ok": False,
                    "error": f"Change #{idx} of type 'remove_import' requires a non-empty 'module_id'.",
                }
            if not pid or not isinstance(pid, str) or not pid.strip():
                return {
                    "ok": False,
                    "error": f"Change #{idx} of type 'remove_import' requires a non-empty 'package_id'.",
                }
        else:
            return {
                "ok": False,
                "error": f"Change #{idx} has invalid type: '{c_type}'. Allowed types: 'add_auth', 'remove_import'.",
            }

    try:
        sim_res = queries.simulate(
            repo_id=ctx.repo_id,
            finding_id=finding_id if finding_id else None,
            changes=changes,
        )
        return {
            "ok": True,
            "simulation": sim_res,
            **sim_res,
        }
    except Exception as exc:  # noqa: BLE001
        logger.warning("Error in simulate: %s", exc)
        return {"ok": False, "error": str(exc)}


# ── 6. recall ──────────────────────────────────────────────────
def recall(ctx: ToolContext, finding_id: str | None = None, **kwargs: Any) -> dict[str, Any]:
    """Return past investigations and decisions from queries.recall."""
    if finding_id and not _is_valid_finding_id(finding_id):
        return {
            "ok": False,
            "error": f"Invalid finding_id: '{finding_id}'. Expected 12-character hex string matching ^[a-f0-9]{{12}}$.",
        }

    try:
        memory = queries.recall(ctx.repo_id, finding_id if finding_id else None)
        return {
            "ok": True,
            "investigations": memory.get("investigations", []),
            "decisions": memory.get("decisions", []),
        }
    except Exception as exc:  # noqa: BLE001
        logger.warning("Error in recall(%s): %s", finding_id, exc)
        return {"ok": False, "error": str(exc)}


# ── 7. save_investigation ──────────────────────────────────────
def save_investigation(
    ctx: ToolContext,
    finding_id: str = "",
    summary: str = "",
    **kwargs: Any,
) -> dict[str, Any]:
    """Save an Investigation node attached to a finding.

    Permissions:
    - Requires ctx.save_allowed is True.
    - Requires role is 'analyst' or 'admin'.

    Re-runs trace_path itself and stores verdict, score, and path_json from THAT
    deterministic calculation, NEVER from model-provided arguments.
    Summary is truncated to 1000 characters.
    """
    if not ctx.save_allowed:
        return {
            "ok": False,
            "error": "Saving investigations is disabled for this chat session (save=false).",
        }

    if ctx.user_role not in ("analyst", "admin"):
        return {"ok": False, "error": "forbidden"}

    if not _is_valid_finding_id(finding_id):
        return {
            "ok": False,
            "error": f"Invalid finding_id: '{finding_id}'. Expected 12-character hex string matching ^[a-f0-9]{{12}}$.",
        }

    truncated_summary = str(summary or "").strip()[:1000]

    try:
        # Re-run trace_paths deterministically
        trace = queries.trace_paths(ctx.repo_id, finding_id)
        verdict = trace.get("verdict", "unknown")
        reaching = trace.get("reaching_entrypoints", 0)
        total = trace.get("total_public_entrypoints", 0)

        f_info = queries.get_finding(ctx.repo_id, finding_id)
        severity = (f_info.get("severity") if f_info else "UNKNOWN") or "UNKNOWN"

        score_breakdown = calculate_score(
            verdict=verdict,
            severity=severity,
            reaching_entrypoints=reaching,
            total_public_entrypoints=total,
        )
        score_val = score_breakdown["score"]
        path_json = json.dumps(trace.get("paths", []))

        inv_id = queries.save_investigation(
            repo_id=ctx.repo_id,
            finding_id=finding_id,
            by=ctx.user_email or "system",
            verdict=verdict,
            score=score_val,
            path_json=path_json,
            summary=truncated_summary,
            session_id=ctx.session_id,
        )

        return {
            "ok": True,
            "investigation_id": inv_id,
            "finding_id": finding_id,
            "verdict": verdict,
            "score": score_val,
            "summary": truncated_summary,
        }
    except Exception as exc:  # noqa: BLE001
        logger.warning("Error in save_investigation(%s): %s", finding_id, exc)
        return {"ok": False, "error": str(exc)}


# ── 8. critical_modules ────────────────────────────────────────
def critical_modules(ctx: ToolContext, **kwargs: Any) -> dict[str, Any]:
    """Return top 10 critical modules scored 0-100 from queries.critical_modules.

    Each item has: {module, score, note}.
    Answers 'which modules are most central/critical'.
    """
    try:
        raw_modules = queries.critical_modules(ctx.repo_id)
        top_10 = []
        for m in raw_modules[:10]:
            score_val = m.get("score", 0.0)
            note = m.get("note") or f"Centrality score: {score_val}"
            top_10.append({
                "module": m.get("module"),
                "score": score_val,
                "note": note,
            })
        return {
            "ok": True,
            "modules": top_10,
            "count": len(top_10),
        }
    except Exception as exc:  # noqa: BLE001
        logger.warning("Error in critical_modules: %s", exc)
        return {"ok": False, "error": str(exc)}


# ── 9. vulnerability_clusters ──────────────────────────────────
def vulnerability_clusters(ctx: ToolContext, **kwargs: Any) -> dict[str, Any]:
    """Return vulnerability clusters from queries.vulnerability_clusters.

    Each item has: {cluster_id, modules, findings}.
    Answers 'can these findings be fixed together / which findings are related'.
    """
    try:
        raw_clusters = queries.vulnerability_clusters(ctx.repo_id)
        clusters = []
        for c in raw_clusters:
            clusters.append({
                "cluster_id": c.get("cluster_id"),
                "modules": c.get("modules", []),
                "findings": c.get("findings", []),
            })
        return {
            "ok": True,
            "clusters": clusters,
            "count": len(clusters),
        }
    except Exception as exc:  # noqa: BLE001
        logger.warning("Error in vulnerability_clusters: %s", exc)
        return {"ok": False, "error": str(exc)}


def global_recall(ctx: ToolContext, package_name: str = "", **kwargs: Any) -> dict[str, Any]:
    """Search rg_global for cross-repository memory on a package or pattern.

    Returns past decisions and patterns learned across repositories.
    """
    pkg = package_name.strip()
    if not pkg:
        return {"ok": False, "error": "package_name is required"}

    try:
        hits = queries.global_recall(pkg)
        return {
            "ok": True,
            "package_name": pkg,
            "hits": hits,
            "count": len(hits),
        }
    except Exception as exc:  # noqa: BLE001
        logger.warning("Error in global_recall(%s): %s", pkg, exc)
        return {"ok": False, "error": str(exc)}


# ── Registry & Tool Schemas ─────────────────────────────────────
REGISTRY: dict[str, Callable[..., dict[str, Any]]] = {
    "list_findings": list_findings,
    "trace_path": trace_path,
    "score_finding": score_finding,
    "choke_points": choke_points,
    "simulate": simulate,
    "recall": recall,
    "save_investigation": save_investigation,
    "critical_modules": critical_modules,
    "vulnerability_clusters": vulnerability_clusters,
    "global_recall": global_recall,
}

TOOL_SCHEMAS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "list_findings",
            "description": (
                "List the top 25 vulnerability findings in the repository sorted by score descending. "
                "Use this tool first to discover available findings, packages, severities, and the 12-character finding IDs."
            ),
            "parameters": {
                "type": "object",
                "properties": {},
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "trace_path",
            "description": (
                "Trace reachable execution paths from public entrypoints to the vulnerable package for a specific finding. "
                "Returns the graph traversal paths, verdict ('reachable_in_model', 'unknown', 'no_path_found'), "
                "reaching entrypoint counts, blind spots, and the deterministic score breakdown. "
                "Use when the user asks how a vulnerability is reached, whether it is exploitable, or requests proof paths."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "finding_id": {
                        "type": "string",
                        "description": "The exact 12-character hex identifier of the finding (obtained from list_findings).",
                    },
                },
                "required": ["finding_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "score_finding",
            "description": (
                "Compute and return only the deterministic risk score breakdown (reach, severity, public exposure weights, "
                "and final 0-100 score) for a finding without returning full path traces. "
                "Use when you only need the numbers or score explanation."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "finding_id": {
                        "type": "string",
                        "description": "The exact 12-character hex identifier of the finding (obtained from list_findings).",
                    },
                },
                "required": ["finding_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "choke_points",
            "description": (
                "Identify high-impact bottleneck packages whose upgrade or removal would clear the most reachable findings. "
                "Use when recommending remediation priorities or asking which package fixes yield the highest security impact."
            ),
            "parameters": {
                "type": "object",
                "properties": {},
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "simulate",
            "description": (
                "Run a what-if simulation on a temporary graph copy to test the effect of architectural changes on reachability. "
                "Supported changes: "
                "1) {'type': 'add_auth', 'entrypoint_id': '<id>'} to mark a public entrypoint as authenticated; "
                "2) {'type': 'remove_import', 'module_id': '<id>', 'package_id': '<id>'} to simulate removing a dependency. "
                "Returns before/after verdict comparisons. Never modifies the real repository graph."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "changes": {
                        "type": "array",
                        "description": "List of change objects to simulate.",
                        "items": {
                            "type": "object",
                            "properties": {
                                "type": {
                                    "type": "string",
                                    "enum": ["add_auth", "remove_import"],
                                    "description": "Type of what-if change.",
                                },
                                "entrypoint_id": {
                                    "type": "string",
                                    "description": "Entrypoint ID for 'add_auth'.",
                                },
                                "module_id": {
                                    "type": "string",
                                    "description": "Module dotted path for 'remove_import'.",
                                },
                                "package_id": {
                                    "type": "string",
                                    "description": "Package ID (name@version) for 'remove_import'.",
                                },
                            },
                            "required": ["type"],
                        },
                    },
                    "finding_id": {
                        "type": "string",
                        "description": "Optional 12-character hex finding ID to simulate impact on a specific finding.",
                    },
                },
                "required": ["changes"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "recall",
            "description": (
                "Recall past investigations, analyst notes, and human risk decisions from memory. "
                "Always call this when the user asks what is known about a finding, whether we have seen it before, or asks about prior decisions or notes."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "finding_id": {
                        "type": "string",
                        "description": "Optional 12-character hex finding ID to recall memory for a specific finding.",
                    },
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "save_investigation",
            "description": (
                "Save an investigation note with current graph verdict and score into repository memory. "
                "Requires analyst or admin permission and save_allowed=True. "
                "Verdicts and scores are always computed deterministically by the system, ignoring model overrides."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "finding_id": {
                        "type": "string",
                        "description": "The 12-character hex finding ID to attach the investigation to.",
                    },
                    "summary": {
                        "type": "string",
                        "description": "Concise summary of the investigation and conclusion (max 1000 characters).",
                    },
                },
                "required": ["finding_id", "summary"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "critical_modules",
            "description": (
                "Identify top 10 central or critical modules in the codebase, their centrality scores (0-100), and algorithm notes. "
                "Answers 'which modules are most central/critical' or questions about module importance and bus factor."
            ),
            "parameters": {
                "type": "object",
                "properties": {},
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "vulnerability_clusters",
            "description": (
                "Group findings into clusters based on shared module entrypoints and code paths. "
                "Answers 'can these findings be fixed together / which findings are related' to plan batched remediations."
            ),
            "parameters": {
                "type": "object",
                "properties": {},
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "global_recall",
            "description": (
                "Search rg_global cross-repository memory for previously approved decisions or patterns on a package. "
                "Answers what past organizational decisions exist for a package across repositories."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "package_name": {
                        "type": "string",
                        "description": "The package or pattern name to search across repositories (e.g. 'requests', 'urllib3').",
                    },
                },
                "required": ["package_name"],
            },
        },
    },
]
