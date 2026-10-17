"""
Tests for graph algorithms in backend/app/graph/queries.py:
- critical_modules (PageRank / reach_centrality)
- choke_points (algo.SPpaths vs counting)
- vulnerability_clusters (entrypoint ancestor clusters)
- trace_paths (trace_ms measurement)

Uses a small throwaway graph:
- 2 entrypoints
- 4 modules
- 2 packages
- 1 finding
"""

from __future__ import annotations

import uuid
from collections.abc import Generator

import pytest
from app.graph.client import delete_graph_if_exists, repo_graph, repo_graph_name, run
from app.graph.queries import (
    choke_points,
    choke_points_algorithm,
    choke_points_counting,
    critical_modules,
    trace_paths,
    vulnerability_clusters,
)
from app.graph.schema import ensure_repo_schema
from falkordb import Graph


@pytest.fixture()
def algo_repo() -> Generator[tuple[str, Graph], None, None]:
    """Create a temporary repo graph seeded with 2 entrypoints, 4 modules, 2 packages, and 1 finding.

    Topology:
    - Entrypoints:
        e1 (public) -> m1
        e2 (public) -> m3
    - Modules:
        m1 (hub): receives imports from m2 and m4; imports m2
        m3: imports m4; m4 imports m1
    - Packages:
        m1 -> p1 (requests)
        m3 -> p2 (urllib3)
    - Finding:
        f1 on p1
    Always cleans up the graph after the test.
    """
    repo_id = str(uuid.uuid4())
    g = repo_graph(repo_id)

    try:
        g.query("MATCH (n) DETACH DELETE n")
    except Exception:  # noqa: BLE001, S110
        pass

    ensure_repo_schema(g)

    setup_cypher = """
    CREATE (e1:Entrypoint {id: 'e1', method: 'GET', path: '/public1', public: true}),
           (e2:Entrypoint {id: 'e2', method: 'POST', path: '/public2', public: true}),
           (m1:Module {id: 'm1', file: 'm1.py'}),
           (m2:Module {id: 'm2', file: 'm2.py'}),
           (m3:Module {id: 'm3', file: 'm3.py'}),
           (m4:Module {id: 'm4', file: 'm4.py'}),
           (p1:Package {id: 'pkg-requests', name: 'requests', version: '2.28.0'}),
           (p2:Package {id: 'pkg-urllib3', name: 'urllib3', version: '1.26.0'}),
           (f1:Finding {id: 'find-01', status: 'open'}),
           (v1:Vulnerability {id: 'GHSA-test-0001', severity: 'HIGH'}),
           (e1)-[:HANDLED_BY]->(m1),
           (e1)-[:HANDLED_BY]->(m2),
           (m2)-[:IMPORTS]->(m1),
           (e2)-[:HANDLED_BY]->(m3),
           (e2)-[:HANDLED_BY]->(m4),
           (m1)-[:USES]->(p1),
           (m3)-[:USES]->(p2),
           (f1)-[:ON_PACKAGE]->(p1),
           (f1)-[:ABOUT]->(v1)
    """
    run(g, setup_cypher)

    yield repo_id, g

    delete_graph_if_exists(repo_graph_name(repo_id))


def test_critical_modules_returns_hub_module_first(algo_repo: tuple[str, Graph]) -> None:
    """critical_modules returns top 10 with the hub module (m1) first and score 0-100."""
    repo_id, _ = algo_repo
    modules = critical_modules(repo_id)

    assert len(modules) >= 1
    assert modules[0]["module"] == "m1", f"Expected hub module 'm1' first, got {modules[0]['module']}"
    assert 0 <= modules[0]["score"] <= 100.0
    assert modules[0]["score"] == 100.0, f"Expected top module score to be 100.0, got {modules[0]['score']}"


def test_choke_points_algorithm_matches_counting(algo_repo: tuple[str, Graph]) -> None:
    """choke_points algorithm result matches the path-counting result."""
    repo_id, _ = algo_repo

    algo_res = choke_points_algorithm(repo_id)
    count_res = choke_points_counting(repo_id)
    main_res = choke_points(repo_id)

    assert len(algo_res) == 1
    assert len(count_res) == 1
    assert algo_res == count_res, f"Algorithm result {algo_res} did not match counting result {count_res}"
    assert main_res == algo_res

    top_pkg = main_res[0]
    assert top_pkg["package"] == "requests"
    assert top_pkg["clears_findings"] == 1
    assert top_pkg["finding_ids"] == ["find-01"]


def test_vulnerability_clusters_groups_modules_under_same_entrypoint(algo_repo: tuple[str, Graph]) -> None:
    """vulnerability_clusters puts modules under the same entrypoint in one cluster."""
    repo_id, _ = algo_repo

    clusters = vulnerability_clusters(repo_id)
    assert len(clusters) == 2, f"Expected 2 clusters, got {len(clusters)}: {clusters}"

    # Cluster 1: m1 and m2 (under e1)
    # Cluster 2: m3 and m4 (under e2)
    modules_sets = [set(c["modules"]) for c in clusters]
    assert {"m1", "m2"} in modules_sets, f"Expected cluster with m1 and m2, got {modules_sets}"
    assert {"m3", "m4"} in modules_sets, f"Expected cluster with m3 and m4, got {modules_sets}"

    # Verify findings are listed inside the reachable cluster
    cluster_e1 = next(c for c in clusters if "m1" in c["modules"])
    assert "find-01" in cluster_e1["findings"]

    cluster_e2 = next(c for c in clusters if "m3" in c["modules"])
    assert "find-01" not in cluster_e2["findings"]


def test_trace_ms_is_present_and_integer_gte_zero(algo_repo: tuple[str, Graph]) -> None:
    """trace_paths returns trace_ms as an integer >= 0."""
    repo_id, _ = algo_repo

    result = trace_paths(repo_id, "find-01")

    assert "trace_ms" in result, "trace_ms not found in TraceResult"
    assert isinstance(result["trace_ms"], int), f"Expected trace_ms to be int, got {type(result['trace_ms'])}"
    assert result["trace_ms"] >= 0, f"Expected trace_ms >= 0, got {result['trace_ms']}"
    assert result["verdict"] == "reachable_in_model"
