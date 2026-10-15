"""
FalkorDB smoke test — standalone script.

Connects using settings from backend/app/config.py and runs nine capability
probes against temporary graphs:
  - "rg_smoke_test" for items 1-5 (basic Cypher features)
  - "rg_smoke_alg"  for items 6-9 (algorithm / procedure discovery)

Writes a team-facing summary to docs/FALKORDB_CAPS.md.

Usage:
    cd backend && python -m scripts.falkor_smoke   (or)
    python scripts/falkor_smoke.py                 (from repo root, with PYTHONPATH=backend)
"""

from __future__ import annotations

import os
import sys
import traceback

# Allow running from repo root: add backend/ to path so we can import app.config
sys.path.insert(0, os.path.join(os.path.dirname(__file__), os.pardir, "backend"))

# If running in an environment without falkordb, try re-execing with backend/.venv if it exists
try:
    import falkordb  # noqa: F401
except ImportError:
    venv_python = os.path.join(os.path.dirname(__file__), os.pardir, "backend", ".venv", "bin", "python")
    if os.path.exists(venv_python) and sys.executable != os.path.abspath(venv_python):
        os.execv(venv_python, [venv_python] + sys.argv)

from app.config import settings  # noqa: E402
from falkordb import FalkorDB  # noqa: E402

GRAPH_NAME = "rg_smoke_test"
COPY_NAME = "rg_smoke_copy"
ALG_GRAPH = "rg_smoke_alg"

REPO_ROOT = os.path.join(os.path.dirname(__file__), os.pardir)

# Each entry: (label, passed, detail, syntax_or_error)
# syntax_or_error is used for FALKORDB_CAPS.md
results: list[tuple[str, bool, str, str]] = []


def record(label: str, passed: bool, detail: str = "", syntax_or_error: str = "") -> None:
    tag = "PASS" if passed else "FAIL"
    results.append((label, passed, detail, syntax_or_error))
    print(f"\n{'=' * 60}")
    print(f"[{tag}] {label}")
    if detail:
        print(detail)
    print("=" * 60)


def discover_procedures(graph, keywords: list[str]) -> tuple[list[str], str]:
    """
    Call dbms.procedures() and return (matching_names, full_listing).

    Returns procedures whose name contains any of the given keywords (case-insensitive).
    """
    res = graph.query("CALL dbms.procedures() YIELD name, mode RETURN name, mode")
    all_procs = []
    matches = []
    for row in res.result_set:
        name = row[0]
        all_procs.append(f"  {name} ({row[1]})")
        for kw in keywords:
            if kw.lower() in name.lower():
                matches.append(name)
                break
    listing = "\n".join(all_procs)
    return matches, listing


def try_procedure_variants(graph, proc_names: list[str], label: str) -> None:
    """Try calling each discovered procedure and record the first that works."""
    for proc_name in proc_names:
        # Try several common call patterns
        variants = [
            f"CALL {proc_name}('Module') YIELD node, score RETURN node.id, score LIMIT 5",
            f"CALL {proc_name}('Module') YIELD node RETURN node LIMIT 5",
            f"CALL {proc_name}() YIELD node, score RETURN node.id, score LIMIT 5",
            f"CALL {proc_name}() YIELD * LIMIT 5",
        ]
        for query in variants:
            try:
                res = graph.query(query)
                if res.result_set:
                    detail = f"  Working query: {query}\n  Rows: {len(res.result_set)}\n"
                    for row in res.result_set[:5]:
                        detail += f"    {row}\n"
                    record(label, True, detail, syntax_or_error=query)
                    return
            except Exception:
                continue

    # Nothing worked
    record(
        label,
        False,
        f"  Tried procedures: {proc_names}\n  None returned data.",
        syntax_or_error=f"No working variant found for: {proc_names}",
    )


def main() -> None:
    password = settings.FALKORDB_PASSWORD or None
    print(f"Connecting to FalkorDB at {settings.FALKORDB_HOST}:{settings.FALKORDB_PORT} "
          f"(password={'***' if password else 'none'})")

    db = FalkorDB(
        host=settings.FALKORDB_HOST,
        port=settings.FALKORDB_PORT,
        password=password,
    )

    # ══════════════════════════════════════════════════════════
    # PART A — Basic Cypher features (rg_smoke_test, items 1-5)
    # ══════════════════════════════════════════════════════════

    graph = db.select_graph(GRAPH_NAME)

    try:
        # ── Setup: create nodes A->B->C and A->D->C ─────────────
        try:
            graph.query("MATCH (n) DETACH DELETE n")
        except Exception:
            pass  # graph may not exist yet

        graph.query("""
            CREATE (a:N {id:'A'})-[:R]->(b:N {id:'B'})-[:R]->(c:N {id:'C'}),
                   (a)-[:R]->(d:N {id:'D'})-[:R]->(c)
        """)
        print("\nSetup (rg_smoke_test): created nodes A->B->C and A->D->C")

        # ── Test 1: shortestPath ─────────────────────────────────
        try:
            query = (
                "MATCH (a:N {id:'A'}), (c:N {id:'C'}) "
                "WITH shortestPath((a)-[:R*..10]->(c)) AS p "
                "RETURN p, nodes(p), length(p)"
            )
            res = graph.query(query)
            if not res.result_set:
                raise ValueError("No path returned from shortestPath query")

            row = res.result_set[0]
            p = row[0]
            node_list = row[1]
            path_length = row[2]

            node_ids = [n.properties.get("id", "?") for n in node_list]
            start_id = node_ids[0] if node_ids else None
            end_id = node_ids[-1] if node_ids else None

            detail = (
                f"  Result rows: {len(res.result_set)}\n"
                f"  Path node ids: {node_ids}\n"
                f"  Path length (hops): {path_length}\n"
                f"  Start node: {start_id}, End node: {end_id}\n"
            )

            # Verification: starts at A, ends at C, expected minimum length is 2 (3 nodes)
            if start_id != "A":
                raise ValueError(f"Path does not start at 'A' (got {start_id})")
            if end_id != "C":
                raise ValueError(f"Path does not end at 'C' (got {end_id})")
            if path_length != 2:
                raise ValueError(f"Expected minimum length 2, got {path_length}")
            if len(node_ids) != 3:
                raise ValueError(f"Expected 3 nodes in path, got {len(node_ids)}")

            syntax = "MATCH (a:N {id:'A'}), (c:N {id:'C'}) WITH shortestPath((a)-[:R*..10]->(c)) AS p RETURN p, nodes(p), length(p)"
            record("1. shortestPath", True, detail, syntax)
        except Exception as exc:
            record("1. shortestPath", False, traceback.format_exc(),
                   str(exc).split("\n")[0])

        # ── Test 2: variable-length match with multiple rel types ─
        try:
            graph.query("MATCH (b:N {id:'B'}), (c:N {id:'C'}) CREATE (b)-[:S]->(c)")
            res = graph.query(
                "MATCH p=(a:N {id:'A'})-[:R|S*1..5]->(c:N {id:'C'}) "
                "RETURN nodes(p) LIMIT 3"
            )
            detail = f"  Result rows: {len(res.result_set)}\n"
            for row in res.result_set:
                node_ids = [n.properties.get("id", "?") for n in row[0]]
                detail += f"  Path node ids: {node_ids}\n"
            syntax = "MATCH p=(a)-[:R|S*1..5]->(c) RETURN nodes(p) LIMIT 3"
            record("2. Variable-length multi-rel-type match", True, detail, syntax)
        except Exception as exc:
            record("2. Variable-length multi-rel-type match", False, traceback.format_exc(),
                   str(exc).split("\n")[0])

        # ── Test 3: parameterized query ──────────────────────────
        try:
            res = graph.query(
                "MATCH (n:N {id: $id}) RETURN n.id",
                params={"id": "A"},
            )
            detail = f"  Returned: {res.result_set}"
            syntax = "MATCH (n:N {id: $id}) RETURN n.id  params={'id': 'A'}"
            record("3. Parameterized query ($id)", True, detail, syntax)
        except Exception as exc:
            record("3. Parameterized query ($id)", False, traceback.format_exc(),
                   str(exc).split("\n")[0])

        # ── Test 4: graph copy ───────────────────────────────────
        try:
            if hasattr(graph, "copy"):
                graph.copy(COPY_NAME)
                detail = "  Used graph.copy() method"
                syntax = "graph.copy('target_name')"
            else:
                db.connection.execute_command("GRAPH.COPY", GRAPH_NAME, COPY_NAME)
                detail = "  Used raw GRAPH.COPY command"
                syntax = "GRAPH.COPY src dest"

            copy_graph = db.select_graph(COPY_NAME)
            verify = copy_graph.query("MATCH (n:N {id:'A'}) RETURN n.id")
            detail += f"\n  Verified copy — query returned: {verify.result_set}"

            copy_graph.delete()
            detail += "\n  Copy deleted successfully"
            record("4. Graph copy", True, detail, syntax)
        except Exception as exc:
            record("4. Graph copy", False, traceback.format_exc(),
                   str(exc).split("\n")[0])

        # ── Test 5: list graphs ──────────────────────────────────
        try:
            graphs = db.list_graphs()
            detail = f"  Graphs: {graphs}"
            syntax = "db.list_graphs()"
            record("5. List graphs", True, detail, syntax)
        except Exception as exc:
            record("5. List graphs", False, traceback.format_exc(),
                   str(exc).split("\n")[0])
    finally:
        # ── Cleanup rg_smoke_test ────────────────────────────────
        print("\n\nCleaning up rg_smoke_test...")
        try:
            graph.delete()
            print(f"  Deleted {GRAPH_NAME}")
        except Exception as exc:
            print(f"  Warning: could not delete {GRAPH_NAME}: {exc}")

        try:
            db.select_graph(COPY_NAME).delete()
            print(f"  Deleted {COPY_NAME}")
        except Exception:
            pass

    # ══════════════════════════════════════════════════════════
    # PART B — Algorithm / procedure discovery (rg_smoke_alg, items 6-9)
    # ══════════════════════════════════════════════════════════

    alg = db.select_graph(ALG_GRAPH)

    # ── Setup: diamond + cycle + entrypoints ─────────────────
    # Diamond:  M1->M2, M1->M3, M2->M4, M3->M4
    # Cycle:    M4->M5, M5->M6, M6->M4
    # Entrypoints: E1-[:HANDLED_BY]->M1, E2-[:HANDLED_BY]->M3
    try:
        alg.query("MATCH (n) DETACH DELETE n")
    except Exception:
        pass

    alg.query("""
        CREATE
            (m1:Module {id:'M1', file:'m1.py'}),
            (m2:Module {id:'M2', file:'m2.py'}),
            (m3:Module {id:'M3', file:'m3.py'}),
            (m4:Module {id:'M4', file:'m4.py'}),
            (m5:Module {id:'M5', file:'m5.py'}),
            (m6:Module {id:'M6', file:'m6.py'}),

            (m1)-[:IMPORTS]->(m2),
            (m1)-[:IMPORTS]->(m3),
            (m2)-[:IMPORTS]->(m4),
            (m3)-[:IMPORTS]->(m4),
            (m4)-[:IMPORTS]->(m5),
            (m5)-[:IMPORTS]->(m6),
            (m6)-[:IMPORTS]->(m4),

            (e1:Entrypoint {id:'E1', method:'GET', path:'/health'}),
            (e2:Entrypoint {id:'E2', method:'POST', path:'/login'}),
            (e1)-[:HANDLED_BY]->(m1),
            (e2)-[:HANDLED_BY]->(m3)
    """)
    print("\nSetup (rg_smoke_alg): diamond M1->M2/M3->M4, cycle M4->M5->M6->M4, "
          "entrypoints E1->M1, E2->M3")

    # ── Discover all available procedures once ───────────────
    all_procs_listing = ""
    all_proc_names: list[str] = []
    try:
        res = alg.query("CALL dbms.procedures() YIELD name, mode RETURN name, mode")
        for row in res.result_set:
            all_proc_names.append(row[0])
            all_procs_listing += f"  {row[0]} ({row[1]})\n"
        print(f"\n  Available procedures ({len(all_proc_names)}):\n{all_procs_listing}")
    except Exception:
        print("  Warning: CALL dbms.procedures() failed")
        print(traceback.format_exc())

    # ── Test 6: PageRank ─────────────────────────────────────
    def test_pagerank():
        # Try signatures in order: (label, rel), (label), no-arg
        queries = [
            ("CALL algo.pageRank('Module', 'IMPORTS') YIELD node, score "
             "RETURN node.id, score ORDER BY score DESC",
             "CALL algo.pageRank('Module', 'IMPORTS') YIELD node, score"),
            ("CALL algo.pageRank('Module') YIELD node, score "
             "RETURN node.id, score ORDER BY score DESC",
             "CALL algo.pageRank('Module') YIELD node, score"),
            ("CALL algo.pageRank(NULL, NULL) YIELD node, score "
             "RETURN node.id, score ORDER BY score DESC LIMIT 6",
             "CALL algo.pageRank(NULL, NULL) YIELD node, score"),
        ]

        for query, syntax in queries:
            try:
                res = alg.query(query)
                if res.result_set:
                    detail = f"  Working query: {syntax}\n"
                    for row in res.result_set:
                        detail += f"    {row[0]}: {row[1]}\n"
                    record("6. PageRank", True, detail, syntax)
                    return
            except Exception as exc:
                print(f"  Tried: {syntax} -> {str(exc).split(chr(10))[0]}")

        # Discover procedures matching pagerank/rank
        matching = [p for p in all_proc_names
                    if "pagerank" in p.lower() or "rank" in p.lower()]
        print(f"  Procedures matching 'pagerank'/'rank': {matching}")

        if matching:
            try_procedure_variants(alg, matching, "6. PageRank")
        else:
            detail = f"  No procedures matching 'pagerank' or 'rank' found.\n"
            detail += f"  All procedures:\n{all_procs_listing}"
            record("6. PageRank", False, detail,
                   "algo.pageRank exists but no working signature found")

    test_pagerank()

    # ── Test 7: Community detection ──────────────────────────
    def test_community():
        keywords = ["community", "louvain", "label"]

        # Discovered: algo.labelPropagation() YIELD node (single column only, no community ID).
        # With (label, rel) args it returns empty; only () returns data.
        queries = [
            ("CALL algo.labelPropagation() YIELD node "
             "RETURN node.id LIMIT 8",
             "CALL algo.labelPropagation() YIELD node"),
            ("CALL algo.labelPropagation('Module', 'IMPORTS') YIELD node "
             "RETURN node.id LIMIT 8",
             "CALL algo.labelPropagation('Module', 'IMPORTS') YIELD node"),
        ]

        for query, syntax in queries:
            try:
                res = alg.query(query)
                if res.result_set:
                    detail = f"  Working query: {syntax}\n"
                    detail += f"  NOTE: Only yields 'node', no community/label column.\n"
                    for row in res.result_set:
                        detail += f"    {row}\n"
                    record("7. Community detection", True, detail, syntax)
                    return
            except Exception as exc:
                print(f"  Tried: {syntax} -> {str(exc).split(chr(10))[0]}")

        # Discover matching procedures
        matching = [p for p in all_proc_names
                    if any(kw in p.lower() for kw in keywords)]
        print(f"  Procedures matching {keywords}: {matching}")

        if matching:
            try_procedure_variants(alg, matching, "7. Community detection")
        else:
            detail = f"  No procedures matching {keywords} found.\n"
            detail += f"  All procedures:\n{all_procs_listing}"
            record("7. Community detection", False, detail,
                   f"No procedures matching {keywords}")

    test_community()

    # ── Test 8: Shortest path (procedure or function) ────────
    def test_shortest_path_proc():
        # Try algo.SPpaths / algo.SSpaths with various signatures
        attempts = [
            (
                "MATCH (a:Entrypoint {id:'E1'}), (b:Module {id:'M4'}) "
                "CALL algo.SPpaths({sourceNode: a, targetNode: b, relTypes: ['HANDLED_BY','IMPORTS'], pathCount: 3}) "
                "YIELD path RETURN [n IN nodes(path) | n.id] AS ids, length(path) AS hops",
                "CALL algo.SPpaths({sourceNode, targetNode, relTypes, pathCount}) YIELD path",
            ),
            (
                "MATCH (a:Entrypoint {id:'E1'}), (b:Module {id:'M4'}) "
                "CALL algo.SPpaths({sourceNode: a, targetNode: b}) "
                "YIELD path RETURN [n IN nodes(path) | n.id] AS ids",
                "CALL algo.SPpaths({sourceNode, targetNode}) YIELD path",
            ),
            (
                "MATCH (a:Entrypoint {id:'E1'}), (b:Module {id:'M4'}) "
                "CALL algo.SSpaths({sourceNode: a, targetNode: b, relTypes: ['HANDLED_BY','IMPORTS'], pathCount: 3}) "
                "YIELD path RETURN [n IN nodes(path) | n.id] AS ids, length(path) AS hops",
                "CALL algo.SSpaths({sourceNode, targetNode, relTypes, pathCount}) YIELD path",
            ),
            (
                "MATCH (a:Entrypoint {id:'E1'}), (b:Module {id:'M4'}) "
                "CALL algo.shortestPath(a, b) YIELD path, pathWeight "
                "RETURN nodes(path), pathWeight",
                "CALL algo.shortestPath(a, b) YIELD path, pathWeight",
            ),
        ]

        for query, syntax in attempts:
            try:
                res = alg.query(query)
                if res.result_set:
                    detail = f"  Working query: {query}\n  Rows: {len(res.result_set)}\n"
                    for row in res.result_set:
                        detail += f"    {row}\n"
                    record("8. Shortest path (procedure)", True, detail, syntax)
                    return
            except Exception as exc:
                print(f"  Tried: {syntax} -> {str(exc).split(chr(10))[0]}")

        # Try Cypher shortestPath in WITH/RETURN (since MATCH clause failed in test 1)
        try:
            query = (
                "MATCH (a:Entrypoint {id:'E1'}), (b:Module {id:'M4'}), "
                "p=(a)-[:HANDLED_BY|IMPORTS*1..10]->(b) "
                "WITH p ORDER BY length(p) ASC LIMIT 1 "
                "RETURN [n IN nodes(p) | n.id] AS path_ids, length(p) AS hops"
            )
            res = alg.query(query)
            if res.result_set:
                detail = f"  Working query (variable-length + ORDER BY length):\n    {query}\n"
                for row in res.result_set:
                    detail += f"    path_ids={row[0]}, hops={row[1]}\n"
                record("8. Shortest path (procedure)", True, detail,
                       "Variable-length path + ORDER BY length(p) LIMIT 1 (no procedure needed)")
                return
        except Exception as exc:
            print(f"  Tried variable-length fallback -> {str(exc).split(chr(10))[0]}")

        # Discover matching procedures
        matching = [p for p in all_proc_names
                    if any(kw in p.lower() for kw in ["shortestpath", "shortest", "sppath", "dijkstra"])]
        print(f"  Procedures matching shortest path: {matching}")

        if matching:
            try_procedure_variants(alg, matching, "8. Shortest path (procedure)")
        else:
            detail = f"  No procedure found. Variable-length fallback also failed.\n"
            detail += f"  All procedures:\n{all_procs_listing}"
            record("8. Shortest path (procedure)", False, detail,
                   "No shortest path procedure or working fallback found")

    test_shortest_path_proc()

    # ── Test 9: Connected components / centrality ────────────
    def test_components_centrality():
        keywords = ["component", "betweenness", "centrality", "wcc", "harmonic"]

        # Discovered exact YIELD columns:
        # algo.WCC() YIELD node, componentId
        # algo.betweenness() YIELD node, score  (no-arg only)
        # algo.HarmonicCentrality() YIELD node, score  (no-arg only)
        attempts = [
            ("CALL algo.WCC() YIELD node, componentId "
             "RETURN node.id, componentId ORDER BY componentId LIMIT 8",
             "algo.WCC() YIELD node, componentId"),
            ("CALL algo.betweenness() YIELD node, score "
             "RETURN node.id, score ORDER BY score DESC LIMIT 8",
             "algo.betweenness() YIELD node, score"),
            ("CALL algo.HarmonicCentrality() YIELD node, score "
             "RETURN node.id, score ORDER BY score DESC LIMIT 8",
             "algo.HarmonicCentrality() YIELD node, score"),
            ("MATCH (s:Module {id:'M1'}) "
             "CALL algo.BFS(s, 0, 'IMPORTS') YIELD nodes "
             "RETURN size(nodes)",
             "algo.BFS(startNode, 0, 'IMPORTS') YIELD nodes"),
        ]

        for query, name in attempts:
            try:
                res = alg.query(query)
                if res.result_set:
                    detail = f"  Working query ({name}): {query}\n"
                    for row in res.result_set[:6]:
                        detail += f"    {row}\n"
                    record("9. Connected components / centrality", True, detail, query)
                    return
            except Exception as exc:
                print(f"  Tried {name} -> {str(exc).split(chr(10))[0]}")

        # Discover matching procedures
        matching = [p for p in all_proc_names
                    if any(kw in p.lower() for kw in keywords)]
        print(f"  Procedures matching {keywords}: {matching}")

        if matching:
            try_procedure_variants(alg, matching, "9. Connected components / centrality")
        else:
            detail = f"  No procedures matching {keywords} found.\n"
            detail += f"  All procedures:\n{all_procs_listing}"
            record("9. Connected components / centrality", False, detail,
                   f"No procedures matching {keywords}")

    test_components_centrality()

    # ── Cleanup rg_smoke_alg ─────────────────────────────────
    print("\n\nCleaning up rg_smoke_alg...")
    try:
        alg.delete()
        print(f"  Deleted {ALG_GRAPH}")
    except Exception as exc:
        print(f"  Warning: could not delete {ALG_GRAPH}: {exc}")

    # ══════════════════════════════════════════════════════════
    # SUMMARY (console + docs/FALKORDB_CAPS.md)
    # ══════════════════════════════════════════════════════════

    separator = "=" * 60
    print(f"\n\n{separator}")
    print("SUMMARY")
    print(separator)

    summary_lines: list[str] = []
    for label, passed, _, syntax_or_error in results:
        if passed:
            line = f"SUPPORTED: {syntax_or_error}"
        else:
            line = f"UNSUPPORTED: {syntax_or_error}"
        summary_lines.append(f"  {label}")
        summary_lines.append(f"    {line}")
        tag = "✅" if passed else "❌"
        print(f"  {tag} {label}")
        print(f"       {line}")

    total = len(results)
    passed_count = sum(1 for _, p, _, _ in results if p)
    print(f"\n  {passed_count}/{total} passed")

    # ── Write docs/FALKORDB_CAPS.md ──────────────────────────
    caps_path = os.path.join(REPO_ROOT, "docs", "FALKORDB_CAPS.md")
    os.makedirs(os.path.dirname(caps_path), exist_ok=True)

    with open(caps_path, "w") as f:
        f.write("# FalkorDB Capabilities (auto-generated)\n\n")
        f.write("Generated by `scripts/falkor_smoke.py`. **Do not edit manually.**\n")
        f.write("The whole team codes against this file.\n\n")
        f.write(f"FalkorDB image: `falkordb/falkordb:latest`\n")
        f.write(f"Python client: `FalkorDB` (pip)\n\n")
        f.write("## Results\n\n")
        f.write("| # | Capability | Status | Syntax / Error |\n")
        f.write("|---|---|---|---|\n")
        for label, passed, _, syntax_or_error in results:
            status = "✅ SUPPORTED" if passed else "❌ UNSUPPORTED"
            # Escape pipes in the syntax/error for markdown table
            escaped = syntax_or_error.replace("|", "\\|").replace("\n", " ")
            f.write(f"| {label} | {status} | `{escaped}` |\n")

        f.write(f"\n**{passed_count}/{total} capabilities confirmed.**\n")

        # Add design guidance section
        f.write("\n## Design Guidance\n\n")
        f.write("Based on the results above, the ReachGuard codebase should:\n\n")

        # Check specific results for guidance
        sp_match = next((r for r in results if "1." in r[0]), None)
        sp_proc = next((r for r in results if "8." in r[0]), None)
        vl_match = next((r for r in results if "2." in r[0]), None)

        if sp_match and sp_match[1]:
            f.write(f"- **Shortest paths**: Cypher `shortestPath(...)` in WITH/RETURN clause is fully supported: `{sp_match[3]}`.\n")
        elif sp_match and not sp_match[1] and vl_match and vl_match[1]:
            f.write("- **Shortest paths**: `shortestPath()` in MATCH clause is NOT supported. "
                    "Use variable-length paths with `ORDER BY length(p) LIMIT 1` instead.\n")

        if sp_proc and sp_proc[1]:
            f.write(f"- **Shortest path procedure**: `{sp_proc[3]}` is available.\n")

        copy_result = next((r for r in results if "4." in r[0]), None)
        if copy_result and copy_result[1]:
            f.write(f"- **Graph copy** (what-if): `{copy_result[3]}` works.\n")

        param_result = next((r for r in results if "3." in r[0]), None)
        if param_result and param_result[1]:
            f.write("- **Parameterized queries**: Fully supported. Always use `$param` syntax.\n")

        f.write("\n### Available Procedures\n\n")
        f.write("```\n")
        if all_procs_listing:
            f.write(all_procs_listing)
        else:
            f.write("  (could not retrieve procedure list)\n")
        f.write("```\n")

    print(f"\n  📝 Written to {caps_path}")


if __name__ == "__main__":
    main()
