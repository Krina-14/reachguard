"""
ReachGuard — Ingestion Graph Builder Pipeline.

Orchestrates repository ingestion:
1. Clones repository or unzips archive.
2. Parses Python files via static AST analysis (parse_python).
3. Parses dependency lockfiles (lockfiles).
4. Resolves imports to first-party modules and third-party packages (importmap).
5. Queries vulnerability database (osv).
6. Resolves module ownership (owners).
7. Populates FalkorDB repo graph using batched UNWIND Cypher queries.
8. Computes and records repository statistics.
"""

from __future__ import annotations

import hashlib
import json
import logging
import shutil
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.graph.client import (
    delete_graph_if_exists,
    meta_graph,
    repo_graph,
    repo_graph_name,
    run,
)
from app.graph.schema import ensure_repo_schema
from app.ingest.fetch import find_dependency_files, iter_python_files
from app.ingest.importmap import resolve_import
from app.ingest.lockfiles import (
    LockResult,
    parse_pipfile_lock,
    parse_poetry_lock,
    parse_requirements,
)
from app.ingest.osv import OsvUnavailable, query_vulns
from app.ingest.owners import from_codeowners, resolve_module_owners
from app.ingest.parse_python import ModuleInfo, parse_python_file

logger = logging.getLogger(__name__)

BATCH_SIZE = 500


def _make_id(*parts: str) -> str:
    """Compute 12-char SHA1 hex digest for deterministic IDs."""
    data = "|".join(parts).encode("utf-8")
    return hashlib.sha1(data).hexdigest()[:12]


def _batch_unwind(graph: Any, cypher: str, items: list[dict[str, Any]], batch_size: int = BATCH_SIZE) -> None:
    """Execute a Cypher query using UNWIND over items in chunks."""
    if not items:
        return
    for i in range(0, len(items), batch_size):
        chunk = items[i : i + batch_size]
        run(graph, cypher, params={"rows": chunk})


def update_repo_status(
    repo_id: str,
    status: str,
    stage_detail: str | None = None,
    error: str | None = None,
    stats: dict[str, Any] | None = None,
) -> None:
    """Update Repo node status, stage_detail, error, and stats in rg_meta graph."""
    g = meta_graph()
    cypher = """
    MATCH (r:Repo {id: $repo_id})
    SET r.status = $status,
        r.stage_detail = $stage_detail,
        r.error = $error
    """
    params: dict[str, Any] = {
        "repo_id": repo_id,
        "status": status,
        "stage_detail": stage_detail,
        "error": error,
    }
    if stats is not None:
        cypher += ", r.stats_json = $stats_json"
        params["stats_json"] = json.dumps(stats)

    run(g, cypher, params=params)


def build_repo_graph(
    repo_id: str,
    root_dir: str | Path,
    update_status: Callable[[str, str | None], None] | None = None,
    is_git: bool = True,
) -> dict[str, Any]:
    """
    Run the ingestion pipeline to build a repository graph.

    Args:
        repo_id: UUID4 of the repository.
        root_dir: Directory containing cloned repository or extracted zip.
        update_status: Callback to update stage/status.
        is_git: True if cloned via git (enabling git log author inspection).

    Returns:
        Computed repository stats dict.
    """
    root_path = Path(root_dir).resolve()
    rg_name = repo_graph_name(repo_id)
    g = repo_graph(repo_id)

    status_ready = False

    def notify(stage: str, detail: str | None = None) -> None:
        if update_status:
            update_status(stage, detail)
        update_repo_status(repo_id, status=stage, stage_detail=detail)

    try:
        # Reset and prepare schema for repository graph
        delete_graph_if_exists(rg_name)
        ensure_repo_schema(g)

        # ── STAGE 1: PARSING ─────────────────────────────────────────
        notify("parsing", "Parsing Python source files")

        files_parsed = 0
        files_failed = 0
        modules: list[ModuleInfo] = []

        for rel_file in iter_python_files(root_path):
            abs_file = root_path / rel_file
            mod = parse_python_file(abs_file, root_path)
            modules.append(mod)
            if mod.failed:
                files_failed += 1
            else:
                files_parsed += 1

        first_party_module_names = {m.name for m in modules if m.name}
        # Also include top-level module segments as first-party
        first_party_roots = {m.name.split(".")[0] for m in modules if m.name}
        all_first_party = first_party_module_names | first_party_roots

        # ── STAGE 2: SCANNING ─────────────────────────────────────────
        notify("scanning", "Scanning lockfiles and dependencies")

        # Discover and parse lockfiles
        dep_result = find_dependency_files(root_path)
        lockfile_kind = dep_result.kind
        lock_res: LockResult

        if dep_result.kind == "poetry.lock" and dep_result.candidates:
            lock_res = parse_poetry_lock(dep_result.candidates[0])
        elif dep_result.kind == "Pipfile.lock" and dep_result.candidates:
            lock_res = parse_pipfile_lock(dep_result.candidates[0])
        elif dep_result.kind == "requirements.txt" and dep_result.candidates:
            lock_res = parse_requirements(dep_result.candidates[0])
        else:
            lock_res = LockResult(kind="none", packages=[], edges=[], transitive_available=False)

        known_packages_map = {pkg.name: pkg for pkg in lock_res.packages}
        known_package_names = set(known_packages_map.keys())

        # Query OSV for package vulnerabilities
        packages_to_query = [(pkg.name, pkg.version) for pkg in lock_res.packages]
        try:
            vulns_by_pkg = query_vulns(packages_to_query)
        except OsvUnavailable as exc:
            logger.error("OSV unavailable during scan of repo %s: %s", repo_id, exc)
            raise

        # ── STAGE 3: POPULATE GRAPH ──────────────────────────────────
        notify("scanning", "Populating graph nodes and edges")

        # 1. Module nodes
        module_rows = [
            {"id": m.name, "file": m.file, "lines": m.lines}
            for m in modules
            if m.name
        ]
        _batch_unwind(
            g,
            """
            UNWIND $rows AS r
            MERGE (m:Module {id: r.id})
            SET m.file = r.file, m.lines = r.lines
            """,
            module_rows,
        )

        # 2. Entrypoint nodes and HANDLED_BY edges
        entrypoint_rows: list[dict[str, Any]] = []
        for m in modules:
            for ep in m.entrypoints:
                entrypoint_rows.append(
                    {
                        "id": ep.id,
                        "method": ep.method,
                        "path": ep.path,
                        "file": ep.file,
                        "line": ep.line,
                        "framework": ep.framework,
                        "public": ep.public,
                        "auth_hint": ep.auth_hint,
                        "handler_module": ep.handler_module,
                    }
                )

        _batch_unwind(
            g,
            """
            UNWIND $rows AS r
            MERGE (e:Entrypoint {id: r.id})
            SET e.method = r.method, e.path = r.path, e.file = r.file, e.line = r.line,
                e.framework = r.framework, e.public = r.public, e.auth_hint = r.auth_hint
            WITH e, r
            MATCH (m:Module {id: r.handler_module})
            MERGE (e)-[:HANDLED_BY]->(m)
            """,
            entrypoint_rows,
        )

        # 3. Package nodes
        package_rows: list[dict[str, Any]] = []
        for pkg in lock_res.packages:
            ver_display = pkg.version if pkg.version is not None else "unpinned"
            pkg_id = f"{pkg.name}@{ver_display}"
            package_rows.append(
                {
                    "id": pkg_id,
                    "name": pkg.name,
                    "version": ver_display,
                    "direct": pkg.direct,
                }
            )

        _batch_unwind(
            g,
            """
            UNWIND $rows AS r
            MERGE (p:Package {id: r.id})
            SET p.name = r.name, p.version = r.version, p.direct = r.direct, p.ecosystem = 'PyPI'
            """,
            package_rows,
        )

        # 4. Package DEPENDS_ON edges
        pkg_depends_rows = [
            {"from_id": edge[0], "to_id": edge[1]} for edge in lock_res.edges
        ]
        _batch_unwind(
            g,
            """
            UNWIND $rows AS r
            MATCH (p1:Package {id: r.from_id}), (p2:Package {id: r.to_id})
            MERGE (p1)-[:DEPENDS_ON]->(p2)
            """,
            pkg_depends_rows,
        )

        # 5. Imports resolution: Module-IMPORTS->Module and Module-USES->Package
        module_imports_rows: list[dict[str, str]] = []
        module_uses_rows: list[dict[str, str]] = []
        blind_spot_rows: list[dict[str, Any]] = []

        # Collect blindspots from parser
        for m in modules:
            for bs in m.blind_spots:
                blind_spot_rows.append(
                    {
                        "id": bs.id,
                        "kind": bs.kind,
                        "reason": bs.reason,
                        "file": bs.file,
                        "line": bs.line,
                        "name": bs.name,
                        "module_id": m.name,
                    }
                )

        # Resolve each import
        for m in modules:
            if not m.name:
                continue

            for imp in m.imports:
                target_str = imp.target
                resolved = resolve_import(
                    top_level_name=target_str,
                    known_packages=known_package_names,
                    first_party_modules=all_first_party,
                )

                if resolved == "STDLIB":
                    continue

                if resolved == "FIRST_PARTY":
                    # Determine exact matching first-party module
                    matched_mod = target_str
                    if matched_mod not in first_party_module_names:
                        # Try matching prefix
                        parts = target_str.split(".")
                        for k in range(len(parts) - 1, 0, -1):
                            prefix = ".".join(parts[:k])
                            if prefix in first_party_module_names:
                                matched_mod = prefix
                                break

                    if matched_mod in first_party_module_names and matched_mod != m.name:
                        module_imports_rows.append(
                            {"from_id": m.name, "to_id": matched_mod}
                        )
                    continue

                if resolved in known_packages_map:
                    pkg_spec = known_packages_map[resolved]
                    ver_display = (
                        pkg_spec.version if pkg_spec.version is not None else "unpinned"
                    )
                    pkg_id = f"{pkg_spec.name}@{ver_display}"
                    module_uses_rows.append(
                        {"module_id": m.name, "package_id": pkg_id}
                    )
                    continue

                # Unresolved third-party-looking import
                bs_id = _make_id("unresolved_import", m.file, str(imp.line), target_str)
                blind_spot_rows.append(
                    {
                        "id": bs_id,
                        "kind": "unresolved_import",
                        "reason": f"Could not resolve imported module '{target_str}' to a known package",
                        "file": m.file,
                        "line": imp.line,
                        "name": target_str,
                        "module_id": m.name,
                    }
                )

        # Insert Module-IMPORTS->Module
        _batch_unwind(
            g,
            """
            UNWIND $rows AS r
            MATCH (m1:Module {id: r.from_id}), (m2:Module {id: r.to_id})
            MERGE (m1)-[:IMPORTS]->(m2)
            """,
            module_imports_rows,
        )

        # Insert Module-USES->Package
        _batch_unwind(
            g,
            """
            UNWIND $rows AS r
            MATCH (m:Module {id: r.module_id}), (p:Package {id: r.package_id})
            MERGE (m)-[:USES]->(p)
            """,
            module_uses_rows,
        )

        # 6. BlindSpot nodes and HAS_BLINDSPOT edges
        _batch_unwind(
            g,
            """
            UNWIND $rows AS r
            MERGE (b:BlindSpot {id: r.id})
            SET b.kind = r.kind, b.reason = r.reason, b.file = r.file, b.line = r.line, b.name = r.name
            WITH b, r
            MATCH (m:Module {id: r.module_id})
            MERGE (m)-[:HAS_BLINDSPOT]->(b)
            """,
            blind_spot_rows,
        )

        # 7. Vulnerabilities, Findings, ABOUT, ON_PACKAGE, AFFECTS
        finding_rows: list[dict[str, Any]] = []
        now_iso = datetime.now(UTC).isoformat()

        for pkg in lock_res.packages:
            if pkg.version is None:
                continue
            ver_display = pkg.version
            pkg_id = f"{pkg.name}@{ver_display}"
            pkg_vulns = vulns_by_pkg.get((pkg.name, pkg.version), [])

            for v in pkg_vulns:
                vuln_id = v["id"]
                finding_id = _make_id(vuln_id, pkg_id)
                finding_rows.append(
                    {
                        "finding_id": finding_id,
                        "vuln_id": vuln_id,
                        "package_id": pkg_id,
                        "aliases": v.get("aliases", []),
                        "summary": v.get("summary", ""),
                        "severity": v.get("severity", "UNKNOWN"),
                        "fixed_versions": v.get("fixed_versions", []),
                        "published": v.get("published", ""),
                        "first_seen": now_iso,
                    }
                )

        _batch_unwind(
            g,
            """
            UNWIND $rows AS r
            MERGE (v:Vulnerability {id: r.vuln_id})
            SET v.aliases = r.aliases, v.summary = r.summary, v.severity = r.severity,
                v.fixed_versions = r.fixed_versions, v.published = r.published
            WITH v, r
            MATCH (p:Package {id: r.package_id})
            MERGE (v)-[:AFFECTS]->(p)
            MERGE (f:Finding {id: r.finding_id})
            SET f.status = 'open', f.first_seen = r.first_seen
            MERGE (f)-[:ABOUT]->(v)
            MERGE (f)-[:ON_PACKAGE]->(p)
            """,
            finding_rows,
        )

        # 8. Owners per module
        codeowners_fn = from_codeowners(root_path)
        owner_rows: list[dict[str, Any]] = []

        for m in modules:
            if not m.name:
                continue
            owners = resolve_module_owners(root_path, m.file, is_git=is_git, codeowners_fn=codeowners_fn)
            for o in owners:
                owner_id = _make_id(o["kind"], o["name"])
                owner_rows.append(
                    {
                        "owner_id": owner_id,
                        "name": o["name"],
                        "kind": o["kind"],
                        "module_id": m.name,
                    }
                )

        _batch_unwind(
            g,
            """
            UNWIND $rows AS r
            MERGE (o:Owner {id: r.owner_id})
            SET o.name = r.name, o.kind = r.kind
            WITH o, r
            MATCH (m:Module {id: r.module_id})
            MERGE (m)-[:OWNED_BY]->(o)
            """,
            owner_rows,
        )

        # ── STAGE 4: READY ───────────────────────────────────────────
        total_entrypoints = len(entrypoint_rows)
        public_entrypoints = sum(1 for ep in entrypoint_rows if ep["public"])
        direct_packages = sum(1 for p in lock_res.packages if p.direct)

        stats: dict[str, Any] = {
            "files_parsed": files_parsed,
            "files_failed": files_failed,
            "modules": len(modules),
            "entrypoints": total_entrypoints,
            "public_entrypoints": public_entrypoints,
            "packages": len(lock_res.packages),
            "direct_packages": direct_packages,
            "findings": len(finding_rows),
            "blind_spots": len(blind_spot_rows),
            "lockfile_kind": lockfile_kind,
            "transitive_available": lock_res.transitive_available,
        }

        notify("ready", None)
        update_repo_status(repo_id, status="ready", stage_detail=None, error=None, stats=stats)
        status_ready = True
        return stats

    except Exception as exc:
        err_msg = str(exc)
        logger.exception("Failed to build repository graph for %s: %s", repo_id, err_msg)
        update_repo_status(repo_id, status="failed", stage_detail=None, error=err_msg)
        if not status_ready:
            # Drop incomplete partial graph
            delete_graph_if_exists(rg_name)
        raise

    finally:
        # Delete temporary cloned/extracted repository folder
        if root_path.exists():
            try:
                shutil.rmtree(root_path, ignore_errors=True)
                logger.debug("Cleaned up directory %s for repo %s", root_path, repo_id)
            except OSError as clean_err:
                logger.warning("Failed to remove temp directory %s: %s", root_path, clean_err)
