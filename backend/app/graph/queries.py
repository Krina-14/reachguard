"""
FalkorDB graph queries — single source of truth for reachability, findings,
subgraphs, choke points, what-if simulations, and investigation/decision memory.

Implements all queries defined in Contract Section 9 according to Section 4, 5, 6, 8.
"""

from __future__ import annotations

import datetime
import json
import logging
import re
import time
import uuid
from typing import Any

from falkordb import Graph

from app.graph.client import (
    delete_graph_if_exists,
    get_db,
    global_graph,
    meta_graph,
    repo_graph,
    run,
    sim_graph_name,
)
from app.ingest.owners import deduplicate_owners

logger = logging.getLogger(__name__)

_NORM_RE = re.compile(r"[-_.]+")


def _normalize_name(name: str) -> str:
    """Normalize a package/import name per PEP 503."""
    return _NORM_RE.sub("-", name).lower()


def _select_graph(repo_id: str, graph_name: str | None = None) -> Graph:
    """Return the specified graph_name or the repo graph for repo_id."""
    if graph_name:
        return get_db().select_graph(graph_name)
    return repo_graph(repo_id)


def _score_fallback(
    verdict: str,
    severity: str,
    reaching_public: int,
    total_public: int,
) -> dict[str, Any]:
    """Contract Section 6 scoring formula fallback."""
    reach_map = {
        "reachable_in_model": 1.0,
        "unknown": 0.5,
        "no_path_found": 0.15,
    }
    reach_val = reach_map.get(verdict, 0.15)

    sev_map = {
        "CRITICAL": 1.0,
        "HIGH": 0.75,
        "MODERATE": 0.5,
        "LOW": 0.25,
        "UNKNOWN": 0.4,
    }
    sev_val = sev_map.get((severity or "").upper(), 0.4)

    exposure_val = (reaching_public / total_public) if total_public > 0 else 0.0

    score_val = round(100 * (0.5 * reach_val + 0.3 * sev_val + 0.2 * exposure_val))

    return {
        "reach": reach_val,
        "severity": sev_val,
        "exposure": exposure_val,
        "weights": {"reach": 0.5, "severity": 0.3, "exposure": 0.2},
        "score": score_val,
    }


def _calculate_score(
    verdict: str,
    severity: str,
    reaching_public: int,
    total_public: int,
) -> dict[str, Any]:
    """Call app.scoring.score if it exists, else use _score_fallback."""
    try:
        from app.scoring import score as score_func

        res = score_func(
            verdict=verdict,
            severity=severity,
            reaching_public=reaching_public,
            total_public=total_public,
        )
        if isinstance(res, dict):
            return res
    except (ImportError, AttributeError) as exc:
        logger.debug("app.scoring not available, using fallback: %s", exc)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Error calling app.scoring.score: %s", exc)
    return _score_fallback(verdict, severity, reaching_public, total_public)


# ── Entrypoint stats ───────────────────────────────────────────


def entrypoint_stats(repo_id: str, graph_name: str | None = None) -> dict[str, Any]:
    """Count total and public entrypoints."""
    g = _select_graph(repo_id, graph_name)
    cypher = """
    MATCH (e:Entrypoint)
    RETURN count(e) as total,
           sum(CASE WHEN e.public = true THEN 1 ELSE 0 END) as total_public
    """
    res = run(g, cypher)
    if res and res[0]["total"] is not None:
        return {
            "total": int(res[0]["total"]),
            "total_public": int(res[0]["total_public"] or 0),
        }
    return {"total": 0, "total_public": 0}


# ── Trace paths (Contract Section 8) ───────────────────────────


def trace_paths(
    repo_id: str,
    finding_id: str,
    max_paths: int = 3,
    graph_name: str | None = None,
) -> dict[str, Any]:
    """Find up to max_paths shortest paths from public entrypoints to finding's Package.

    Returns TraceResult shape per Section 8.
    """
    g = _select_graph(repo_id, graph_name)

    finding_rows = run(
        g,
        """
        MATCH (f:Finding {id: $finding_id})-[:ON_PACKAGE]->(p:Package)
        OPTIONAL MATCH (f)-[:ABOUT]->(v:Vulnerability)
        RETURN f.id as finding_id,
               p.id as package_id,
               p.name as package_name,
               p.version as package_version,
               v.id as vuln_id,
               v.severity as severity
        """,
        {"finding_id": finding_id},
    )

    if not finding_rows:
        raise ValueError(f"Finding '{finding_id}' not found in repo '{repo_id}'")

    f_info = finding_rows[0]
    package_id = f_info["package_id"]
    package_name = f_info["package_name"] or ""

    # 1. Total public entrypoints
    total_public_res = run(
        g,
        "MATCH (e:Entrypoint {public: true}) RETURN count(e) as total_public",
    )
    total_public_ep = int(total_public_res[0]["total_public"]) if total_public_res else 0

    if total_public_ep == 0:
        verdict = "unknown"
        reason = "no_entrypoints_detected"
        paths: list[dict[str, Any]] = []
        reaching_entrypoints = 0
        blind_spots: list[dict[str, Any]] = []
        trace_ms = 0
    else:
        # 2. Query reaching paths
        path_cypher = """
        MATCH p = (e:Entrypoint {public: true})-[:HANDLED_BY|IMPORTS|USES|DEPENDS_ON*1..20]->(pkg:Package {id: $package_id})
        RETURN p, length(p) as len
        ORDER BY len ASC
        LIMIT $max_paths
        """
        t0 = time.perf_counter()
        path_rows = run(g, path_cypher, {"package_id": package_id, "max_paths": max_paths})
        trace_ms = round((time.perf_counter() - t0) * 1000)
        logger.info("Trace finding %s completed in %d ms (repo=%s)", finding_id, trace_ms, repo_id)

        paths = []
        for row in path_rows:
            path_obj = row["p"]
            nodes = path_obj.nodes()
            edges = path_obj.edges()

            first_node = nodes[0]
            ep_props = first_node.properties
            ep_id = str(ep_props.get("id", ""))
            method = ep_props.get("method", "")
            p_str = ep_props.get("path", "")
            entrypoint_desc = f"{method} {p_str}".strip()

            path_nodes = []
            for n in nodes:
                lbl = n.labels[0] if n.labels else ""
                n_id = str(n.properties.get("id", ""))
                if lbl == "Entrypoint":
                    name = f"{n.properties.get('method', '')} {n.properties.get('path', '')}".strip()
                elif lbl == "Package":
                    name = n.properties.get("name") or n_id
                elif lbl == "Module":
                    name = n_id
                else:
                    name = n.properties.get("name") or n_id
                path_nodes.append({"id": n_id, "label": lbl, "name": name})

            path_edges = []
            for e in edges:
                rel = getattr(e, "relation", None) or getattr(e, "type", "")
                path_edges.append({"id": str(getattr(e, "id", "")), "type": rel})

            paths.append({
                "entrypoint_id": ep_id,
                "entrypoint": entrypoint_desc,
                "nodes": path_nodes,
                "edges": path_edges,
            })

        # 3. Distinct reaching public entrypoints
        reaching_ep_res = run(
            g,
            """
            MATCH (e:Entrypoint {public: true})-[:HANDLED_BY|IMPORTS|USES|DEPENDS_ON*1..20]->(pkg:Package {id: $package_id})
            RETURN count(DISTINCT e) as reaching_count
            """,
            {"package_id": package_id},
        )
        reaching_entrypoints = int(reaching_ep_res[0]["reaching_count"]) if reaching_ep_res else 0

        # 4. Blind spots touching the reachable region (modules reachable from any public entrypoint)
        bs_cypher = """
        MATCH (e:Entrypoint {public: true})-[:HANDLED_BY]->(h:Module)-[:IMPORTS*0..20]->(m:Module)-[:HAS_BLINDSPOT]->(b:BlindSpot)
        RETURN DISTINCT m.id as module_id,
                        b.kind as kind,
                        b.file as file,
                        b.line as line,
                        b.reason as reason,
                        b.name as name
        """
        bs_rows = run(g, bs_cypher)

        blind_spots = []
        seen_bs = set()
        for row in bs_rows:
            bs_key = (row.get("kind"), row.get("file"), row.get("line"))
            if bs_key not in seen_bs:
                seen_bs.add(bs_key)
                blind_spots.append({
                    "kind": row.get("kind"),
                    "file": row.get("file"),
                    "line": row.get("line"),
                    "reason": row.get("reason"),
                })

        # 5. Verdict and Reason calculation per Section 5
        if len(paths) > 0:
            verdict = "reachable_in_model"
            reason = f"Reachable from {reaching_entrypoints} public entrypoint(s)"
        else:
            # If package is only in lockfile and never imported, verdict is no_path_found with declared_not_imported
            uses_res = run(
                g,
                "MATCH (:Module)-[:USES]->(p:Package {id: $package_id}) RETURN count(*) as c",
                {"package_id": package_id},
            )
            is_imported = uses_res and uses_res[0]["c"] > 0

            if not is_imported:
                verdict = "no_path_found"
                reason = "declared_not_imported"
            else:
                # Package is imported by some module, but no path from public entrypoint.
                # Check blind spots touching the reachable region
                dynamic_bs = next(
                    (b for b in bs_rows if b.get("kind") in ("dynamic_import", "unparsed_file")),
                    None,
                )
                unresolved_match = None
                for b in bs_rows:
                    if (
                        b.get("kind") == "unresolved_import"
                        and b.get("name")
                        and _normalize_name(b["name"]) == _normalize_name(package_name)
                    ):
                        unresolved_match = b
                        break

                if dynamic_bs is not None:
                    verdict = "unknown"
                    k = dynamic_bs.get("kind")
                    m_or_f = dynamic_bs.get("module_id") or dynamic_bs.get("file")
                    reason = f"{k} in {m_or_f}"
                elif unresolved_match is not None:
                    verdict = "unknown"
                    reason = f"unresolved_import {unresolved_match['name']} matches package {package_name}"
                else:
                    verdict = "no_path_found"
                    reason = "No path found from public entrypoints"

    # 6. Searched scope
    mod_count_res = run(g, "MATCH (m:Module) RETURN count(m) as mod_count")
    total_modules = int(mod_count_res[0]["mod_count"]) if mod_count_res else 0

    stats: dict[str, Any] = {}
    try:
        mg = meta_graph()
        m_res = run(mg, "MATCH (r:Repo {id: $id}) RETURN r.stats_json as stats_json", {"id": repo_id})
        if m_res and m_res[0].get("stats_json"):
            stats = json.loads(m_res[0]["stats_json"])
    except Exception as exc:  # noqa: BLE001
        logger.debug("Could not read stats_json for repo %s: %s", repo_id, exc)

    searched_scope = {
        "modules": stats.get("modules", total_modules),
        "files_parsed": stats.get("files_parsed", total_modules),
        "files_failed": stats.get("files_failed", 0),
        "max_depth": 20,
        "lockfile_kind": stats.get("lockfile_kind", "none"),
        "transitive_available": stats.get("transitive_available", False),
    }

    return {
        "finding_id": finding_id,
        "verdict": verdict,
        "reason": reason,
        "paths": paths,
        "reaching_entrypoints": reaching_entrypoints,
        "total_public_entrypoints": total_public_ep,
        "blind_spots": blind_spots,
        "searched_scope": searched_scope,
        "trace_ms": trace_ms,
    }


# ── List / Get findings ────────────────────────────────────────


def list_findings(repo_id: str) -> list[dict[str, Any]]:
    """Return all findings in the repository sorted by score desc, risk_accepted last."""
    g = repo_graph(repo_id)
    now_iso = datetime.datetime.now(datetime.UTC).isoformat()

    cypher = """
    MATCH (f:Finding)-[:ON_PACKAGE]->(p:Package)
    OPTIONAL MATCH (f)-[:ABOUT]->(v:Vulnerability)
    RETURN f.id as id,
           f.status as status,
           v.id as vuln_id,
           v.aliases as aliases,
           v.summary as summary,
           v.severity as severity,
           v.fixed_versions as fixed_versions,
           p.id as package_id,
           p.name as package_name,
           p.version as package_version
    """
    rows = run(g, cypher)
    results = []

    for r in rows:
        fid = r["id"]
        trace = trace_paths(repo_id, fid)
        verdict = trace["verdict"]
        reaching_ep = trace["reaching_entrypoints"]
        total_ep = trace["total_public_entrypoints"]
        severity = r["severity"] or "UNKNOWN"

        score_dict = _calculate_score(verdict, severity, reaching_ep, total_ep)
        score = score_dict["score"]

        # Check for approved accept_risk decision
        dec_rows = run(
            g,
            """
            MATCH (f:Finding {id: $fid})-[:HAS_DECISION]->(d:Decision {type: "accept_risk", status: "approved"})
            RETURN d.expires_at as expires_at, d.by as by, d.approved_by as approved_by
            """,
            {"fid": fid},
        )
        is_risk_accepted = False
        risk_accepted_by = None
        for dec in dec_rows:
            exp = dec.get("expires_at")
            if not exp or exp > now_iso:
                is_risk_accepted = True
                risk_accepted_by = dec.get("approved_by") or dec.get("by")
                break

        finding_status = "risk_accepted" if is_risk_accepted else (r["status"] or "open")

        # Owners
        pkg_id = r["package_id"]
        owner_rows = run(
            g,
            """
            MATCH (m:Module)-[:USES]->(p:Package {id: $pkg_id}), (m)-[:OWNED_BY]->(o:Owner)
            RETURN DISTINCT o.name as name
            """,
            {"pkg_id": pkg_id},
        )
        raw_owners = [o["name"] for o in owner_rows if o.get("name")]
        owners = deduplicate_owners(raw_owners)

        results.append({
            "id": fid,
            "vuln_id": r["vuln_id"] or "",
            "aliases": r["aliases"] or [],
            "summary": r["summary"] or "",
            "severity": severity,
            "package": r["package_name"] or "",
            "version": r["package_version"] or "",
            "fixed_versions": r["fixed_versions"] or [],
            "verdict": verdict,
            "score": score,
            "status": finding_status,
            "owners": owners,
            "risk_accepted_by": risk_accepted_by,
        })


    # Sort: score desc, risk_accepted last
    results.sort(
        key=lambda item: (
            1 if item["status"] == "risk_accepted" else 0,
            -item["score"],
        )
    )
    return results


def get_finding(repo_id: str, finding_id: str) -> dict[str, Any] | None:
    """Return finding row plus trace, score_breakdown, investigations, decisions."""
    g = repo_graph(repo_id)
    now_iso = datetime.datetime.now(datetime.UTC).isoformat()

    cypher = """
    MATCH (f:Finding {id: $fid})-[:ON_PACKAGE]->(p:Package)
    OPTIONAL MATCH (f)-[:ABOUT]->(v:Vulnerability)
    RETURN f.id as id,
           f.status as status,
           v.id as vuln_id,
           v.aliases as aliases,
           v.summary as summary,
           v.severity as severity,
           v.fixed_versions as fixed_versions,
           p.id as package_id,
           p.name as package_name,
           p.version as package_version
    """
    rows = run(g, cypher, {"fid": finding_id})
    if not rows:
        return None

    r = rows[0]
    trace = trace_paths(repo_id, finding_id)
    verdict = trace["verdict"]
    reaching_ep = trace["reaching_entrypoints"]
    total_ep = trace["total_public_entrypoints"]
    severity = r["severity"] or "UNKNOWN"

    score_dict = _calculate_score(verdict, severity, reaching_ep, total_ep)

    # Check for approved accept_risk decision
    dec_rows = run(
        g,
        """
        MATCH (f:Finding {id: $fid})-[:HAS_DECISION]->(d:Decision {type: "accept_risk", status: "approved"})
        RETURN d.expires_at as expires_at
        """,
        {"fid": finding_id},
    )
    is_risk_accepted = False
    for dec in dec_rows:
        exp = dec.get("expires_at")
        if not exp or exp > now_iso:
            is_risk_accepted = True
            break

    finding_status = "risk_accepted" if is_risk_accepted else (r["status"] or "open")

    # Owners
    pkg_id = r["package_id"]
    owner_rows = run(
        g,
        """
        MATCH (m:Module)-[:USES]->(p:Package {id: $pkg_id}), (m)-[:OWNED_BY]->(o:Owner)
        RETURN DISTINCT o.name as name
        """,
        {"pkg_id": pkg_id},
    )
    raw_owners = [o["name"] for o in owner_rows if o.get("name")]
    owners = deduplicate_owners(raw_owners)

    # Investigations
    inv_rows = run(
        g,
        """
        MATCH (f:Finding {id: $fid})-[:HAD_INVESTIGATION]->(inv:Investigation)
        RETURN inv.id as id,
               inv.created_at as created_at,
               inv.by as by,
               inv.verdict as verdict,
               inv.score as score,
               inv.path_json as path_json,
               inv.summary as summary,
               inv.session_id as session_id
        ORDER BY inv.created_at DESC
        """,
        {"fid": finding_id},
    )

    # Decisions
    decision_rows = run(
        g,
        """
        MATCH (f:Finding {id: $fid})-[:HAS_DECISION]->(d:Decision)
        RETURN d.id as id,
               d.type as type,
               d.reason as reason,
               d.by as by,
               d.status as status,
               d.approved_by as approved_by,
               d.created_at as created_at,
               d.expires_at as expires_at
        ORDER BY d.created_at DESC
        """,
        {"fid": finding_id},
    )

    return {
        "id": finding_id,
        "vuln_id": r["vuln_id"] or "",
        "aliases": r["aliases"] or [],
        "summary": r["summary"] or "",
        "severity": severity,
        "package": r["package_name"] or "",
        "version": r["package_version"] or "",
        "fixed_versions": r["fixed_versions"] or [],
        "verdict": verdict,
        "score": score_dict["score"],
        "status": finding_status,
        "owners": owners,
        "trace": trace,
        "score_breakdown": score_dict,
        "investigations": inv_rows,
        "decisions": decision_rows,
    }


# ── Subgraph (Contract Section 7) ──────────────────────────────


def subgraph(repo_id: str, finding_id: str | None) -> dict[str, Any]:
    """Return nodes/edges for the UI graph view.

    With finding_id: union of path nodes plus one-hop neighbors capped at 80 nodes.
    Without finding_id: summary graph capped at 300 nodes with truncated: true.
    """
    g = repo_graph(repo_id)

    if finding_id is not None:
        trace = trace_paths(repo_id, finding_id)
        path_node_ids: set[str] = set()
        path_edge_ids: set[str] = set()

        nodes_dict: dict[str, dict[str, Any]] = {}
        edges_list: list[dict[str, Any]] = []

        # 1. Pre-seed with all nodes and edges directly from trace paths
        for p in trace.get("paths", []):
            p_nodes = p.get("nodes", [])
            for n in p_nodes:
                nid = str(n.get("id", ""))
                if nid:
                    path_node_ids.add(nid)
                    if nid not in nodes_dict:
                        nodes_dict[nid] = {
                            "id": nid,
                            "label": n.get("label", ""),
                            "name": n.get("name", nid),
                            "props": {},
                        }
            p_edges = p.get("edges", [])
            for idx in range(min(len(p_nodes) - 1, len(p_edges))):
                src = str(p_nodes[idx].get("id", ""))
                dst = str(p_nodes[idx + 1].get("id", ""))
                edge_obj = p_edges[idx]
                eid = str(edge_obj.get("id") or f"e_{src}_{dst}")
                etype = str(edge_obj.get("type") or "CONNECTS_TO")
                if eid:
                    path_edge_ids.add(eid)
                if src and dst and not any(e["source"] == src and e["target"] == dst for e in edges_list):
                    edges_list.append({
                        "id": eid,
                        "source": src,
                        "target": dst,
                        "type": etype,
                    })

        if path_node_ids:
            neighbor_rows = run(
                g,
                """
                MATCH (n) WHERE n.id IN $ids
                OPTIONAL MATCH (n)-[r]-(neighbor)
                RETURN n, neighbor
                """,
                {"ids": list(path_node_ids)},
            )
            for row in neighbor_rows:
                for obj in (row.get("n"), row.get("neighbor")):
                    if obj is not None:
                        obj_id = str(obj.properties.get("id", ""))
                        if obj_id and obj_id not in nodes_dict and len(nodes_dict) < 80:
                            lbl = obj.labels[0] if obj.labels else ""
                            name = (
                                f"{obj.properties.get('method', '')} {obj.properties.get('path', '')}".strip()
                                if lbl == "Entrypoint"
                                else obj.properties.get("name") or obj_id
                            )
                            nodes_dict[obj_id] = {
                                "id": obj_id,
                                "label": lbl,
                                "name": name,
                                "props": obj.properties,
                            }

            node_id_list = list(nodes_dict.keys())
            edge_rows = run(
                g,
                """
                MATCH (a)-[r]->(b)
                WHERE a.id IN $ids AND b.id IN $ids
                RETURN a.id as src, b.id as dst, r
                """,
                {"ids": node_id_list},
            )
            for er in edge_rows:
                src = er["src"]
                dst = er["dst"]
                eid = str(getattr(er["r"], "id", ""))
                etype = getattr(er["r"], "relation", None) or getattr(er["r"], "type", "")
                if not any(e["source"] == src and e["target"] == dst for e in edges_list):
                    edges_list.append({
                        "id": eid,
                        "source": src,
                        "target": dst,
                        "type": etype,
                    })
        else:
            direct_rows = run(
                g,
                """
                MATCH (f:Finding {id: $fid})-[:ON_PACKAGE]->(p:Package)
                OPTIONAL MATCH (f)-[:ABOUT]->(v:Vulnerability)
                OPTIONAL MATCH (p)-[r]-(neighbor)
                RETURN f, p, v, neighbor
                """,
                {"fid": finding_id},
            )
            for row in direct_rows:
                for key in ("f", "p", "v", "neighbor"):
                    obj = row.get(key)
                    if obj is not None:
                        obj_id = str(obj.properties.get("id", ""))
                        if obj_id and obj_id not in nodes_dict and len(nodes_dict) < 80:
                            lbl = obj.labels[0] if obj.labels else ""
                            name = obj.properties.get("name") or obj_id
                            nodes_dict[obj_id] = {
                                "id": obj_id,
                                "label": lbl,
                                "name": name,
                                "props": obj.properties,
                            }
            node_id_list = list(nodes_dict.keys())
            edge_rows = run(
                g,
                """
                MATCH (a)-[r]->(b)
                WHERE a.id IN $ids AND b.id IN $ids
                RETURN a.id as src, b.id as dst, r
                """,
                {"ids": node_id_list},
            )
            edges_list = [
                {
                    "id": str(getattr(er["r"], "id", "")),
                    "source": er["src"],
                    "target": er["dst"],
                    "type": getattr(er["r"], "relation", None) or getattr(er["r"], "type", ""),
                }
                for er in edge_rows
            ]

        return {
            "nodes": list(nodes_dict.values()),
            "edges": edges_list,
            "highlight": {
                "nodes": list(path_node_ids),
                "edges": list(path_edge_ids),
            },
        }

    else:
        summary_rows = run(
            g,
            """
            MATCH (e:Entrypoint {public: true})-[:HANDLED_BY]->(m:Module)
            OPTIONAL MATCH (m)-[:IMPORTS]->(m2:Module)
            OPTIONAL MATCH (m)-[:USES]->(p:Package)
            RETURN e, m, m2, p
            LIMIT 300
            """,
        )
        nodes_dict = {}
        for row in summary_rows:
            for key in ("e", "m", "m2", "p"):
                obj = row.get(key)
                if obj is not None:
                    obj_id = str(obj.properties.get("id", ""))
                    if obj_id and obj_id not in nodes_dict and len(nodes_dict) < 300:
                        lbl = obj.labels[0] if obj.labels else ""
                        name = (
                            f"{obj.properties.get('method', '')} {obj.properties.get('path', '')}".strip()
                            if lbl == "Entrypoint"
                            else obj.properties.get("name") or obj_id
                        )
                        nodes_dict[obj_id] = {
                            "id": obj_id,
                            "label": lbl,
                            "name": name,
                            "props": obj.properties,
                        }

        node_id_list = list(nodes_dict.keys())
        edge_rows = run(
            g,
            """
            MATCH (a)-[r]->(b)
            WHERE a.id IN $ids AND b.id IN $ids
            RETURN a.id as src, b.id as dst, r
            """,
            {"ids": node_id_list},
        )
        edges_list = [
            {
                "id": str(getattr(er["r"], "id", "")),
                "source": er["src"],
                "target": er["dst"],
                "type": getattr(er["r"], "relation", None) or getattr(er["r"], "type", ""),
            }
            for er in edge_rows
        ]

        return {
            "nodes": list(nodes_dict.values()),
            "edges": edges_list,
            "highlight": {"nodes": [], "edges": []},
            "truncated": len(nodes_dict) >= 300,
        }


# ── Critical modules (PageRank) ────────────────────────────────


def critical_modules(
    repo_id: str,
    graph_name: str | None = None,
) -> list[dict[str, Any]]:
    """Return top 10 critical modules scored 0-100 using PageRank.

    If PageRank is not supported or returns no scores, falls back to a deterministic
    reach_centrality approximation based on public-entrypoint shortest paths.
    """
    g = _select_graph(repo_id, graph_name)
    try:
        cypher = """
        CALL algo.pageRank('Module', 'IMPORTS') YIELD node, score
        RETURN node.id as module, score
        ORDER BY score DESC
        LIMIT 10
        """
        rows = run(g, cypher)
        if rows:
            max_score = max(r["score"] for r in rows)
            results = []
            for r in rows:
                mid = r["module"]
                norm_score = round((r["score"] / max_score) * 100.0, 2) if max_score > 0 else 0.0
                owner_rows = run(
                    g,
                    "MATCH (m:Module {id: $mid})-[:OWNED_BY]->(o:Owner) RETURN o.name as name",
                    {"mid": mid},
                )
                owners = [o["name"] for o in owner_rows if o.get("name")]
                owner_str = f"Owner: {', '.join(owners)}" if owners else "No owner assigned"
                results.append({
                    "module": mid,
                    "score": norm_score,
                    "note": f"Algorithm: PageRank on IMPORTS edges. {owner_str}.",
                    "owners": owners,
                })
            return results
    except Exception as exc:  # noqa: BLE001
        logger.warning("algo.pageRank failed, using reach_centrality fallback: %s", exc)

    # Deterministic approximation: count distinct public-entrypoint shortest paths through each module
    mod_count: dict[str, int] = {}
    finding_rows = run(g, "MATCH (f:Finding) RETURN f.id as fid")
    for fr in finding_rows:
        fid = fr["fid"]
        trace = trace_paths(repo_id, fid, max_paths=1, graph_name=graph_name)
        for p in trace.get("paths", []):
            for n in p.get("nodes", []):
                if n.get("label") == "Module":
                    mid = n["id"]
                    mod_count[mid] = mod_count.get(mid, 0) + 1

    if not mod_count:
        all_mods = run(g, "MATCH (m:Module) RETURN m.id as mid LIMIT 10")
        results = []
        for m in all_mods:
            mid = m["mid"]
            owner_rows = run(
                g,
                "MATCH (m:Module {id: $mid})-[:OWNED_BY]->(o:Owner) RETURN o.name as name",
                {"mid": mid},
            )
            owners = [o["name"] for o in owner_rows if o.get("name")]
            owner_str = f"Owner: {', '.join(owners)}" if owners else "No owner assigned"
            results.append({
                "module": mid,
                "reach_centrality": 0,
                "score": 0.0,
                "note": f"Algorithm: reach_centrality fallback (0 paths). {owner_str}.",
                "owners": owners,
            })
        return results

    max_c = max(mod_count.values())
    sorted_mods = sorted(mod_count.items(), key=lambda x: -x[1])[:10]
    results = []
    for mid, count in sorted_mods:
        score = round((count / max_c) * 100.0, 2) if max_c > 0 else 0.0
        owner_rows = run(
            g,
            "MATCH (m:Module {id: $mid})-[:OWNED_BY]->(o:Owner) RETURN o.name as name",
            {"mid": mid},
        )
        owners = [o["name"] for o in owner_rows if o.get("name")]
        owner_str = f"Owner: {', '.join(owners)}" if owners else "No owner assigned"
        results.append({
            "module": mid,
            "reach_centrality": count,
            "score": score,
            "note": f"Algorithm: reach_centrality fallback ({count} reachable entrypoint paths). {owner_str}.",
            "owners": owners,
        })
    return results


# ── Choke points (Contract Section 7) ──────────────────────────


def choke_points_counting(
    repo_id: str,
    graph_name: str | None = None,
) -> list[dict[str, Any]]:
    """Existing path-counting method for choke points."""
    g = _select_graph(repo_id, graph_name)

    reachable_f_rows = run(
        g,
        """
        MATCH (e:Entrypoint {public: true})-[:HANDLED_BY|IMPORTS|USES|DEPENDS_ON*1..20]->(p:Package)<-[:ON_PACKAGE]-(f:Finding)
        RETURN DISTINCT f.id as fid
        """,
    )

    pkg_finding_map: dict[str, set[str]] = {}
    pkg_info_map: dict[str, tuple[str, str]] = {}

    for row in reachable_f_rows:
        fid = row["fid"]
        trace = trace_paths(repo_id, fid, max_paths=1, graph_name=graph_name)
        for p in trace.get("paths", []):
            for node in p.get("nodes", []):
                if node.get("label") == "Package":
                    pid = node["id"]
                    if pid not in pkg_finding_map:
                        pkg_finding_map[pid] = set()
                    pkg_finding_map[pid].add(fid)

    if not pkg_finding_map:
        return []

    pkg_rows = run(
        g,
        "MATCH (p:Package) WHERE p.id IN $pids RETURN p.id as id, p.name as name, p.version as version",
        {"pids": list(pkg_finding_map.keys())},
    )
    for pr in pkg_rows:
        pkg_info_map[pr["id"]] = (pr["name"] or "", pr["version"] or "")

    results = []
    for pid, fids in pkg_finding_map.items():
        name, ver = pkg_info_map.get(pid, (pid, ""))
        results.append({
            "package": name,
            "version": ver,
            "clears_findings": len(fids),
            "finding_ids": sorted(fids),
        })

    results.sort(key=lambda x: -x["clears_findings"])
    return results[:5]


def choke_points_algorithm(
    repo_id: str,
    graph_name: str | None = None,
) -> list[dict[str, Any]]:
    """FalkorDB procedure algo.SPpaths version for choke points."""
    g = _select_graph(repo_id, graph_name)
    pkgs_with_f = run(
        g,
        """
        MATCH (f:Finding)-[:ON_PACKAGE]->(p:Package)
        RETURN DISTINCT p.id as pid, p.name as name, p.version as version
        """,
    )
    if not pkgs_with_f:
        return []

    pkg_finding_map: dict[str, set[str]] = {}
    pkg_info_map: dict[str, tuple[str, str]] = {}

    for pr in pkgs_with_f:
        pid = pr["pid"]
        name = pr["name"] or ""
        ver = pr["version"] or ""
        pkg_info_map[pid] = (name, ver)

        sp_res = run(
            g,
            """
            MATCH (e:Entrypoint {public: true}), (p:Package {id: $pid})
            CALL algo.SPpaths({sourceNode: e, targetNode: p, relTypes: ['HANDLED_BY', 'IMPORTS', 'USES', 'DEPENDS_ON'], pathCount: 1}) YIELD path
            RETURN path LIMIT 1
            """,
            {"pid": pid},
        )
        if sp_res:
            f_rows = run(
                g,
                "MATCH (f:Finding)-[:ON_PACKAGE]->(p:Package {id: $pid}) RETURN f.id as fid",
                {"pid": pid},
            )
            for fr in f_rows:
                pkg_finding_map.setdefault(pid, set()).add(fr["fid"])

    results = []
    for pid, fids in pkg_finding_map.items():
        name, ver = pkg_info_map.get(pid, (pid, ""))
        results.append({
            "package": name,
            "version": ver,
            "clears_findings": len(fids),
            "finding_ids": sorted(fids),
        })

    results.sort(key=lambda x: -x["clears_findings"])
    return results[:5]


def choke_points(
    repo_id: str,
    graph_name: str | None = None,
) -> list[dict[str, Any]]:
    """Return top 5 packages whose upgrade or removal clears the most reachable findings.

    Tries the FalkorDB algorithm (algo.SPpaths) first; falls back to counting method if needed.
    """
    try:
        return choke_points_algorithm(repo_id, graph_name=graph_name)
    except Exception as exc:  # noqa: BLE001
        logger.warning("choke_points_algorithm failed, falling back to counting: %s", exc)
        return choke_points_counting(repo_id, graph_name=graph_name)


# ── Vulnerability clusters ─────────────────────────────────────


def vulnerability_clusters(
    repo_id: str,
    graph_name: str | None = None,
) -> list[dict[str, Any]]:
    """Group modules that share a public entrypoint ancestor within 2 hops (fallback),
    and list reachable findings inside each cluster.
    """
    g = _select_graph(repo_id, graph_name)
    rows = run(
        g,
        """
        MATCH (e:Entrypoint {public: true})-[:HANDLED_BY]->(h:Module)
        OPTIONAL MATCH (h)-[:IMPORTS]->(m:Module)
        RETURN e.id as ep_id, h.id as h_id, m.id as m_id
        """,
    )

    ep_mods: dict[str, set[str]] = {}
    for r in rows:
        eid = r["ep_id"]
        if eid not in ep_mods:
            ep_mods[eid] = set()
        if r["h_id"]:
            ep_mods[eid].add(r["h_id"])
        if r["m_id"]:
            ep_mods[eid].add(r["m_id"])

    parent: dict[str, str] = {}

    def find(x: str) -> str:
        if x not in parent:
            parent[x] = x
        if parent[x] != x:
            parent[x] = find(parent[x])
        return parent[x]

    def union(x: str, y: str) -> None:
        rx, ry = find(x), find(y)
        if rx != ry:
            parent[rx] = ry

    for mods in ep_mods.values():
        mod_list = sorted(mods)
        for i in range(1, len(mod_list)):
            union(mod_list[0], mod_list[i])

    clusters_map: dict[str, set[str]] = {}
    for mods in ep_mods.values():
        for m in mods:
            root = find(m)
            clusters_map.setdefault(root, set()).add(m)

    results = []
    sorted_cluster_roots = sorted(clusters_map.keys())
    for idx, root in enumerate(sorted_cluster_roots, start=1):
        mod_list = sorted(clusters_map[root])
        f_rows = run(
            g,
            """
            MATCH (m:Module)-[:IMPORTS|USES|DEPENDS_ON*0..10]->(p:Package)<-[:ON_PACKAGE]-(f:Finding)
            WHERE m.id IN $mids
            RETURN DISTINCT f.id as fid
            """,
            {"mids": mod_list},
        )
        finding_ids = sorted(fr["fid"] for fr in f_rows)
        results.append({
            "cluster_id": f"cluster_{idx}",
            "modules": mod_list,
            "findings": finding_ids,
        })

    return results


# ── What-if simulate (Contract Section 7 & 9) ──────────────────


def simulate(
    repo_id: str,
    finding_id: str | None,
    changes: list[dict[str, Any]],
) -> dict[str, Any]:
    """Run what-if simulation on a temporary copy graph.

    Supported changes:
    - {'type': 'add_auth', 'entrypoint_id': str}
    - {'type': 'remove_import', 'module_id': str, 'package_id': str}
    """
    source_g = repo_graph(repo_id)
    sim_name = sim_graph_name()
    db = get_db()

    # Create temporary copy of the repo graph
    try:
        source_g.copy(sim_name)
    except Exception as exc:  # noqa: BLE001
        try:
            db.connection.execute_command("GRAPH.COPY", source_g.name, sim_name)
        except Exception:  # noqa: BLE001
            raise NotImplementedError(f"GRAPH.COPY is not supported: {exc}") from exc

    try:
        sim_g = db.select_graph(sim_name)

        # Apply changes on the simulation copy
        for change in changes:
            c_type = change.get("type")
            if c_type == "add_auth":
                eid = change.get("entrypoint_id")
                if eid:
                    run(
                        sim_g,
                        "MATCH (e:Entrypoint {id: $eid}) SET e.public = false",
                        {"eid": eid},
                    )
            elif c_type == "remove_import":
                mid = change.get("module_id")
                pid = change.get("package_id")
                if mid and pid:
                    run(
                        sim_g,
                        "MATCH (m:Module {id: $mid})-[r:USES]->(p:Package {id: $pid}) DELETE r",
                        {"mid": mid, "pid": pid},
                    )

        if finding_id is not None:
            before_trace = trace_paths(repo_id, finding_id)
            after_trace = trace_paths(repo_id, finding_id, graph_name=sim_name)
            changed = []
            if before_trace["verdict"] != after_trace["verdict"]:
                changed.append({
                    "finding_id": finding_id,
                    "from": before_trace["verdict"],
                    "to": after_trace["verdict"],
                })
            return {
                "before": before_trace,
                "after": after_trace,
                "changed": changed,
            }
        else:
            finding_rows = run(source_g, "MATCH (f:Finding) RETURN f.id as id")
            before_map = {}
            after_map = {}
            changed = []
            for fr in finding_rows:
                fid = fr["id"]
                b_tr = trace_paths(repo_id, fid)
                a_tr = trace_paths(repo_id, fid, graph_name=sim_name)
                before_map[fid] = b_tr["verdict"]
                after_map[fid] = a_tr["verdict"]
                if b_tr["verdict"] != a_tr["verdict"]:
                    changed.append({
                        "finding_id": fid,
                        "from": b_tr["verdict"],
                        "to": a_tr["verdict"],
                    })
            return {
                "before": before_map,
                "after": after_map,
                "changed": changed,
            }
    finally:
        delete_graph_if_exists(sim_name)


# ── Memory: Recall, Investigation & Decision ───────────────────


def recall(repo_id: str, finding_id: str | None) -> dict[str, Any]:
    """Return past investigations and decisions."""
    g = repo_graph(repo_id)

    if finding_id is not None:
        inv_rows = run(
            g,
            """
            MATCH (f:Finding {id: $fid})-[:HAD_INVESTIGATION]->(inv:Investigation)
            RETURN inv.id as id,
                   inv.created_at as created_at,
                   inv.by as by,
                   inv.verdict as verdict,
                   inv.score as score,
                   inv.path_json as path_json,
                   inv.summary as summary,
                   inv.session_id as session_id,
                   f.id as finding_id
            ORDER BY inv.created_at DESC
            """,
            {"fid": finding_id},
        )
        dec_rows = run(
            g,
            """
            MATCH (f:Finding {id: $fid})-[:HAS_DECISION]->(d:Decision)
            RETURN d.id as id,
                   d.type as type,
                   d.reason as reason,
                   d.by as by,
                   d.status as status,
                   d.approved_by as approved_by,
                   d.created_at as created_at,
                   d.expires_at as expires_at,
                   f.id as finding_id
            ORDER BY d.created_at DESC
            """,
            {"fid": finding_id},
        )
    else:
        inv_rows = run(
            g,
            """
            MATCH (inv:Investigation)
            OPTIONAL MATCH (f:Finding)-[:HAD_INVESTIGATION]->(inv)
            RETURN inv.id as id,
                   inv.created_at as created_at,
                   inv.by as by,
                   inv.verdict as verdict,
                   inv.score as score,
                   inv.path_json as path_json,
                   inv.summary as summary,
                   inv.session_id as session_id,
                   f.id as finding_id
            ORDER BY inv.created_at DESC
            LIMIT 50
            """,
        )
        dec_rows = run(
            g,
            """
            MATCH (d:Decision)
            OPTIONAL MATCH (f:Finding)-[:HAS_DECISION]->(d)
            RETURN d.id as id,
                   d.type as type,
                   d.reason as reason,
                   d.by as by,
                   d.status as status,
                   d.approved_by as approved_by,
                   d.created_at as created_at,
                   d.expires_at as expires_at,
                   f.id as finding_id
            ORDER BY d.created_at DESC
            LIMIT 50
            """,
        )

    return {"investigations": inv_rows, "decisions": dec_rows}


def save_investigation(
    repo_id: str,
    finding_id: str,
    by: str,
    verdict: str,
    score: int,
    path_json: str,
    summary: str,
    session_id: str,
) -> str:
    """Save an Investigation node attached to a finding. Returns the investigation ID."""
    g = repo_graph(repo_id)
    inv_id = uuid.uuid4().hex[:12]
    created_at = datetime.datetime.now(datetime.UTC).isoformat()

    cypher = """
    MATCH (f:Finding {id: $finding_id})
    CREATE (inv:Investigation {
        id: $id,
        created_at: $created_at,
        by: $by,
        verdict: $verdict,
        score: $score,
        path_json: $path_json,
        summary: $summary,
        session_id: $session_id
    })
    CREATE (f)-[:HAD_INVESTIGATION]->(inv)
    RETURN inv.id as id
    """
    res = run(
        g,
        cypher,
        {
            "finding_id": finding_id,
            "id": inv_id,
            "created_at": created_at,
            "by": by,
            "verdict": verdict,
            "score": score,
            "path_json": path_json,
            "summary": summary,
            "session_id": session_id,
        },
    )
    if not res:
        raise ValueError(f"Finding {finding_id} not found to save investigation")
    return inv_id


def create_decision(
    repo_id: str,
    finding_id: str,
    by: str,
    type: str,
    reason: str,
    expires_at: str | None,
) -> dict[str, Any]:
    """Create a Decision node attached to a finding.

    accept_risk starts pending; other types start approved.
    """
    g = repo_graph(repo_id)
    dec_id = uuid.uuid4().hex[:12]
    created_at = datetime.datetime.now(datetime.UTC).isoformat()

    if type == "accept_risk":
        status = "pending"
        approved_by = None
    else:
        status = "approved"
        approved_by = by

    cypher = """
    MATCH (f:Finding {id: $finding_id})
    CREATE (d:Decision {
        id: $id,
        type: $type,
        reason: $reason,
        by: $by,
        status: $status,
        approved_by: $approved_by,
        created_at: $created_at,
        expires_at: $expires_at
    })
    CREATE (f)-[:HAS_DECISION]->(d)
    RETURN d.id as id,
           d.type as type,
           d.reason as reason,
           d.by as by,
           d.status as status,
           d.approved_by as approved_by,
           d.created_at as created_at,
           d.expires_at as expires_at
    """
    res = run(
        g,
        cypher,
        {
            "finding_id": finding_id,
            "id": dec_id,
            "type": type,
            "reason": reason,
            "by": by,
            "status": status,
            "approved_by": approved_by,
            "created_at": created_at,
            "expires_at": expires_at,
        },
    )
    if not res:
        raise ValueError(f"Finding {finding_id} not found to create decision")
    return res[0]


def _is_admin_user(user_identifier: str) -> bool:
    """Return True if user_identifier belongs to an admin user."""
    try:
        mg = meta_graph()
        rows = run(
            mg,
            "MATCH (u:User) WHERE u.email = $id OR u.id = $id RETURN u.role as role",
            {"id": user_identifier},
        )
        if rows:
            return rows[0].get("role") == "admin"
    except Exception:
        pass
    # Fallback for tests where users are not seeded in rg_meta
    return "admin" in user_identifier.lower()


def _normalize_pattern_name(
    decision_type: str,
    package_name: str | None,
    vuln_id: str | None,
    aliases: list[str] | None,
) -> str | None:
    """Extract normalized pattern name: package name for accept_risk/false_positive, or vuln alias prefix for fixed."""
    pkg = (package_name or "").strip().lower()
    if decision_type in ("accept_risk", "false_positive"):
        return pkg or None
    elif decision_type == "fixed":
        if aliases and isinstance(aliases, list):
            for alias in aliases:
                alias_str = str(alias).strip()
                if not alias_str:
                    continue
                parts = alias_str.split("-")
                if len(parts) >= 3:
                    return f"{parts[0]}-{parts[1]}".lower()
                elif len(parts) == 2:
                    return parts[0].lower()
                return alias_str.lower()
        if vuln_id:
            parts = str(vuln_id).strip().split("-")
            if len(parts) >= 3:
                return f"{parts[0]}-{parts[1]}".lower()
            elif len(parts) == 2:
                return parts[0].lower()
            return str(vuln_id).strip().lower()
        return pkg or None
    return pkg or None


def set_decision_status(
    repo_id: str,
    decision_id: str,
    status: str,
    by: str,
) -> dict[str, Any]:
    """Update decision status. Only pending decisions can be transitioned.

    When approved by an admin, UPSERT (:Pattern)-[:LEARNED_FROM]->(:Decision copy)
    into rg_global. Viewers/analysts never write to rg_global.
    """
    g = repo_graph(repo_id)

    check_rows = run(
        g,
        "MATCH (d:Decision {id: $id}) RETURN d.status as status",
        {"id": decision_id},
    )
    if not check_rows:
        raise ValueError(f"Decision '{decision_id}' not found")

    current_status = check_rows[0]["status"]
    if current_status != "pending":
        raise ValueError(f"Decision '{decision_id}' is not pending (current status: '{current_status}')")

    now_iso = datetime.datetime.now(datetime.UTC).isoformat()
    cypher = """
    MATCH (d:Decision {id: $id})
    SET d.status = $status,
        d.approved_by = $by,
        d.approved_at = $approved_at
    RETURN d.id as id,
           d.type as type,
           d.reason as reason,
           d.by as by,
           d.status as status,
           d.approved_by as approved_by,
           d.created_at as created_at,
           d.approved_at as approved_at,
           d.expires_at as expires_at
    """
    res = run(g, cypher, {"id": decision_id, "status": status, "by": by, "approved_at": now_iso})
    updated = res[0]

    # Rule: rg_global is written ONLY on admin-approved decisions.
    if status == "approved" and _is_admin_user(by):
        finding_info = run(
            g,
            """
            MATCH (f:Finding)-[:HAS_DECISION]->(d:Decision {id: $id})
            OPTIONAL MATCH (f)-[:ON_PACKAGE]->(p:Package)
            OPTIONAL MATCH (f)-[:ABOUT]->(v:Vulnerability)
            RETURN f.id as finding_id,
                   p.name as package_name,
                   v.id as vuln_id,
                   v.aliases as aliases
            """,
            {"id": decision_id},
        )
        if finding_info:
            f_row = finding_info[0]
            pkg_name = f_row.get("package_name") or ""
            vuln_id = f_row.get("vuln_id")
            aliases = f_row.get("aliases")
            pattern_name = _normalize_pattern_name(
                decision_type=updated.get("type", ""),
                package_name=pkg_name,
                vuln_id=vuln_id,
                aliases=aliases,
            )
            if pattern_name:
                gg = global_graph()
                upsert_cypher = """
                MERGE (p:Pattern {name: $pattern_name})
                MERGE (d:Decision {id: $decision_id, repo_id: $repo_id})
                SET d.type = $type,
                    d.reason = $reason,
                    d.by = $by,
                    d.status = 'approved',
                    d.approved_by = $approved_by,
                    d.created_at = $created_at,
                    d.approved_at = $approved_at,
                    d.expires_at = $expires_at,
                    d.finding_id = $finding_id,
                    d.package_name = $package_name
                MERGE (p)-[:LEARNED_FROM]->(d)
                """
                run(
                    gg,
                    upsert_cypher,
                    {
                        "pattern_name": pattern_name,
                        "decision_id": decision_id,
                        "repo_id": repo_id,
                        "type": updated.get("type"),
                        "reason": updated.get("reason"),
                        "by": updated.get("by"),
                        "approved_by": by,
                        "created_at": updated.get("created_at"),
                        "approved_at": updated.get("approved_at") or now_iso,
                        "expires_at": updated.get("expires_at"),
                        "finding_id": f_row.get("finding_id"),
                        "package_name": pkg_name,
                    },
                )

    return updated


def global_recall(package_name: str) -> list[dict[str, Any]]:
    """Search rg_global for cross-repository memory matching package_name or pattern.

    Returns past decisions and patterns.
    """
    g = global_graph()
    pkg_clean = (package_name or "").strip().lower()
    if not pkg_clean:
        return []

    cypher = """
    MATCH (p:Pattern)-[:LEARNED_FROM]->(d:Decision)
    WHERE toLower(p.name) = $pkg
       OR toLower(d.package_name) = $pkg
       OR ($pkg STARTS WITH toLower(p.name) AND length(p.name) >= 3)
    RETURN p.name as pattern_name,
           d.id as id,
           d.type as type,
           d.reason as reason,
           d.by as by,
           d.status as status,
           d.approved_by as approved_by,
           d.created_at as created_at,
           d.approved_at as approved_at,
           d.repo_id as repo_id,
           d.finding_id as finding_id,
           d.package_name as package_name
    ORDER BY coalesce(d.approved_at, d.created_at) DESC
    """
    try:
        return run(g, cypher, {"pkg": pkg_clean})
    except Exception as exc:
        logger.warning("Error querying rg_global in global_recall(%s): %s", package_name, exc)
        return []

