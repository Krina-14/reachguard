"""
FalkorDB smoke tests (pytest).

Uses temporary graphs and cleans them up after all tests run:
  - "rg_smoke_test" for items 1-5 (basic Cypher features)
  - "rg_smoke_alg"  for items 6-9 (algorithm / procedure discovery)

Tests are numbered to match the standalone script in scripts/falkor_smoke.py.
"""

from __future__ import annotations

import pytest
from falkordb import FalkorDB

from app.config import settings

GRAPH_NAME = "rg_smoke_test"
COPY_NAME = "rg_smoke_copy"
ALG_GRAPH = "rg_smoke_alg"


@pytest.fixture(scope="module")
def db() -> FalkorDB:
    """Create a FalkorDB connection for the test module."""
    return FalkorDB(
        host=settings.FALKORDB_HOST,
        port=settings.FALKORDB_PORT,
        password=settings.FALKORDB_PASSWORD or None,
    )


@pytest.fixture(scope="module")
def graph(db: FalkorDB):
    """
    Create and seed the smoke-test graph.

    Yields the graph handle, then deletes it after all tests in this module.
    """
    g = db.select_graph(GRAPH_NAME)

    # Clean slate
    try:
        g.query("MATCH (n) DETACH DELETE n")
    except Exception:
        pass

    # Seed: A->B->C and A->D->C via :R, plus B-[:S]->C for multi-type test
    g.query("""
        CREATE (a:N {id:'A'})-[:R]->(b:N {id:'B'})-[:R]->(c:N {id:'C'}),
               (a)-[:R]->(d:N {id:'D'})-[:R]->(c),
               (b)-[:S]->(c)
    """)

    yield g

    # Teardown — delete the smoke graph
    try:
        g.delete()
    except Exception:
        pass

    # Also clean up any leftover copy graph
    try:
        db.select_graph(COPY_NAME).delete()
    except Exception:
        pass


@pytest.fixture(scope="module")
def alg_graph(db: FalkorDB):
    """
    Create the algorithm test graph: diamond + cycle + entrypoints.

    Diamond:  M1->M2, M1->M3, M2->M4, M3->M4
    Cycle:    M4->M5, M5->M6, M6->M4
    Entrypoints: E1-[:HANDLED_BY]->M1, E2-[:HANDLED_BY]->M3

    Yields the graph handle, then deletes it after all tests in this module.
    """
    g = db.select_graph(ALG_GRAPH)

    try:
        g.query("MATCH (n) DETACH DELETE n")
    except Exception:
        pass

    g.query("""
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

    yield g

    try:
        g.delete()
    except Exception:
        pass


@pytest.fixture(scope="module")
def available_procedures(alg_graph) -> list[str]:
    """Return the list of all procedure names from dbms.procedures()."""
    try:
        res = alg_graph.query(
            "CALL dbms.procedures() YIELD name RETURN name"
        )
        return [row[0] for row in res.result_set]
    except Exception:
        return []


# ══════════════════════════════════════════════════════════════════
# Tests 1-5: Basic Cypher features (rg_smoke_test)
# ══════════════════════════════════════════════════════════════════


# ── Test 1: shortestPath ─────────────────────────────────────────


def test_shortest_path(graph) -> None:
    """shortestPath with variable-length :R edges.

    NOTE: FalkorDB may not support shortestPath in MATCH clause.
    This test documents the current behavior — xfail if not supported.
    """
    try:
        res = graph.query(
            "MATCH p=shortestPath((a:N {id:'A'})-[:R*..10]->(c:N {id:'C'})) "
            "RETURN nodes(p)"
        )
    except Exception as exc:
        pytest.xfail(f"shortestPath in MATCH clause not supported: {exc}")

    assert len(res.result_set) >= 1, "Expected at least one shortest path"

    first_path_nodes = res.result_set[0][0]
    node_ids = [n.properties["id"] for n in first_path_nodes]

    assert node_ids[0] == "A", f"Path should start at A, got {node_ids[0]}"
    assert node_ids[-1] == "C", f"Path should end at C, got {node_ids[-1]}"
    assert len(node_ids) == 3, f"Shortest path should have 3 nodes, got {len(node_ids)}"
    print(f"  shortestPath node ids: {node_ids}")


# ── Test 2: variable-length match with multiple rel types ────────


def test_variable_length_multi_rel(graph) -> None:
    """Variable-length match using [:R|S*1..5]."""
    res = graph.query(
        "MATCH p=(a:N {id:'A'})-[:R|S*1..5]->(c:N {id:'C'}) "
        "RETURN nodes(p) LIMIT 3"
    )
    assert len(res.result_set) >= 1, "Expected at least one path"

    for row in res.result_set:
        node_ids = [n.properties["id"] for n in row[0]]
        assert node_ids[0] == "A"
        assert node_ids[-1] == "C"
        print(f"  Multi-rel path: {node_ids}")


# ── Test 3: parameterized query ──────────────────────────────────


def test_parameterized_query(graph) -> None:
    """Query with $id parameter."""
    res = graph.query(
        "MATCH (n:N {id: $id}) RETURN n.id",
        params={"id": "A"},
    )
    assert len(res.result_set) == 1
    assert res.result_set[0][0] == "A"
    print(f"  Parameterized result: {res.result_set}")


# ── Test 4: graph copy ──────────────────────────────────────────


def test_graph_copy(db: FalkorDB, graph) -> None:
    """Copy the graph using the client method or raw GRAPH.COPY command."""
    if hasattr(graph, "copy"):
        graph.copy(COPY_NAME)
        method = "graph.copy()"
    else:
        db.connection.execute_command("GRAPH.COPY", GRAPH_NAME, COPY_NAME)
        method = "GRAPH.COPY command"

    print(f"  Copied via: {method}")

    copy_graph = db.select_graph(COPY_NAME)
    try:
        verify = copy_graph.query("MATCH (n:N {id:'A'}) RETURN n.id")
        assert len(verify.result_set) == 1
        assert verify.result_set[0][0] == "A"
        print(f"  Copy verified: {verify.result_set}")
    finally:
        copy_graph.delete()
        print(f"  Copy {COPY_NAME} deleted")


# ── Test 5: list graphs ─────────────────────────────────────────


def test_list_graphs(db: FalkorDB, graph) -> None:
    """db.list_graphs() should include our smoke graph."""
    graphs = db.list_graphs()
    assert GRAPH_NAME in graphs, f"{GRAPH_NAME} not in {graphs}"
    print(f"  Graphs: {graphs}")


# ══════════════════════════════════════════════════════════════════
# Tests 6-9: Algorithm / procedure discovery (rg_smoke_alg)
# ══════════════════════════════════════════════════════════════════


def _try_queries(graph, queries: list[str]) -> tuple[bool, str, str]:
    """
    Try each query in order. Return (success, detail, syntax_or_error).

    Returns on the first query that executes and returns data.
    """
    errors = []
    for query in queries:
        try:
            res = graph.query(query)
            if res.result_set:
                detail = f"  Working query: {query}\n  Rows: {len(res.result_set)}\n"
                for row in res.result_set[:5]:
                    detail += f"    {row}\n"
                return True, detail, query
        except Exception as exc:
            errors.append(f"  {query.split('YIELD')[0].strip()}: {exc}")
    return False, "\n".join(errors), errors[-1] if errors else "No queries tried"


# ── Test 6: PageRank ─────────────────────────────────────────────


def test_pagerank(alg_graph, available_procedures) -> None:
    """PageRank: try algo.pageRank, then discover alternatives."""
    queries = [
        "CALL algo.pageRank('Module') YIELD node, score "
        "RETURN node.id, score ORDER BY score DESC",
    ]

    # Add any discovered procedures matching pagerank/rank
    for proc in available_procedures:
        if "pagerank" in proc.lower() or "rank" in proc.lower():
            queries.append(
                f"CALL {proc}('Module') YIELD node, score "
                f"RETURN node.id, score ORDER BY score DESC LIMIT 5"
            )

    ok, detail, syntax = _try_queries(alg_graph, queries)
    if ok:
        print(f"  PageRank SUPPORTED: {syntax}")
    else:
        procs_with_rank = [p for p in available_procedures
                           if "pagerank" in p.lower() or "rank" in p.lower()]
        print(f"  PageRank UNSUPPORTED. Matching procedures: {procs_with_rank}")
        print(f"  All procedures: {available_procedures}")
        print(f"  Errors:\n{detail}")
        pytest.xfail(f"PageRank not available: {syntax}")


# ── Test 7: Community detection ──────────────────────────────────


def test_community_detection(alg_graph, available_procedures) -> None:
    """Community detection: try louvain, labelPropagation, then discover."""
    queries = [
        "CALL algo.community('Module') YIELD node, community_id "
        "RETURN node.id, community_id",
        "CALL algo.louvain('Module') YIELD node, community "
        "RETURN node.id, community",
        "CALL algo.labelPropagation('Module') YIELD node, community "
        "RETURN node.id, community",
    ]

    keywords = ["community", "louvain", "label"]
    for proc in available_procedures:
        if any(kw in proc.lower() for kw in keywords):
            queries.append(f"CALL {proc}('Module') YIELD node RETURN node LIMIT 5")

    ok, detail, syntax = _try_queries(alg_graph, queries)
    if ok:
        print(f"  Community detection SUPPORTED: {syntax}")
    else:
        matching = [p for p in available_procedures
                    if any(kw in p.lower() for kw in keywords)]
        print(f"  Community detection UNSUPPORTED. Matching procedures: {matching}")
        print(f"  All procedures: {available_procedures}")
        print(f"  Errors:\n{detail}")
        pytest.xfail(f"Community detection not available: {syntax}")


# ── Test 8: Shortest path (procedure) ────────────────────────────


def test_shortest_path_procedure(alg_graph, available_procedures) -> None:
    """Shortest path via procedure or Cypher variable-length fallback."""
    queries = [
        "MATCH (a:Entrypoint {id:'E1'}), (b:Module {id:'M4'}) "
        "CALL algo.shortestPath(a, b) YIELD path, pathWeight "
        "RETURN nodes(path), pathWeight",

        "MATCH (a:Entrypoint {id:'E1'}), (b:Module {id:'M4'}) "
        "CALL algo.shortestPath(a, b) YIELD path "
        "RETURN path",

        "MATCH (a:Entrypoint {id:'E1'}), (b:Module {id:'M4'}) "
        "CALL algo.SPpaths(a, b, 'IMPORTS', {pathCount: 1}) YIELD path "
        "RETURN path",
    ]

    # Add discovered procedures
    sp_keywords = ["shortestpath", "shortest", "sppath", "dijkstra"]
    for proc in available_procedures:
        if any(kw in proc.lower() for kw in sp_keywords):
            queries.append(
                f"MATCH (a:Entrypoint {{id:'E1'}}), (b:Module {{id:'M4'}}) "
                f"CALL {proc}(a, b) YIELD path RETURN path"
            )

    ok, detail, syntax = _try_queries(alg_graph, queries)
    if ok:
        print(f"  Shortest path procedure SUPPORTED: {syntax}")
        return

    # Fallback: variable-length path + ORDER BY length
    try:
        query = (
            "MATCH (a:Entrypoint {id:'E1'}), (b:Module {id:'M4'}), "
            "p=(a)-[:HANDLED_BY|IMPORTS*1..10]->(b) "
            "WITH p ORDER BY length(p) ASC LIMIT 1 "
            "RETURN [n IN nodes(p) | n.id] AS path_ids, length(p) AS hops"
        )
        res = alg_graph.query(query)
        assert res.result_set, "Variable-length fallback returned no rows"
        path_ids = res.result_set[0][0]
        hops = res.result_set[0][1]
        print(f"  No procedure, but variable-length fallback works: {path_ids} ({hops} hops)")
    except Exception as exc:
        matching = [p for p in available_procedures
                    if any(kw in p.lower() for kw in sp_keywords)]
        print(f"  Matching procedures: {matching}")
        print(f"  All procedures: {available_procedures}")
        print(f"  Procedure errors:\n{detail}")
        pytest.xfail(f"No shortest path procedure or fallback: {exc}")


# ── Test 9: Connected components / centrality ────────────────────


def test_components_centrality(alg_graph, available_procedures) -> None:
    """Connected components or betweenness centrality."""
    queries = [
        "CALL algo.connectedComponents('Module') YIELD node, component "
        "RETURN node.id, component",
        "CALL algo.betweenness('Module') YIELD node, score "
        "RETURN node.id, score",
        "CALL algo.BFS(n, 0, 'IMPORTS') YIELD nodes "
        "RETURN size(nodes)",
    ]

    keywords = ["component", "betweenness", "centrality"]
    for proc in available_procedures:
        if any(kw in proc.lower() for kw in keywords):
            queries.extend([
                f"CALL {proc}('Module') YIELD node, score "
                f"RETURN node.id, score LIMIT 5",
                f"CALL {proc}('Module') YIELD node RETURN node LIMIT 5",
            ])

    ok, detail, syntax = _try_queries(alg_graph, queries)
    if ok:
        print(f"  Components/centrality SUPPORTED: {syntax}")
    else:
        matching = [p for p in available_procedures
                    if any(kw in p.lower() for kw in keywords)]
        print(f"  Components/centrality UNSUPPORTED. Matching procedures: {matching}")
        print(f"  All procedures: {available_procedures}")
        print(f"  Errors:\n{detail}")
        pytest.xfail(f"No components/centrality procedure: {syntax}")
