"""
Tests for backend/app/graph/queries.py.

Builds a tiny throwaway graph in tests with explicit Cypher:
- 2 entrypoints
- 3 modules
- 3 packages
- 1 vulnerability
- 1 blind spot

Asserts:
- reachable path nodes in order
- no_path_found (declared_not_imported)
- unknown via dynamic_import
- simulate flips reachable to no_path_found after add_auth and the sim graph no longer exists afterwards
- choke point count
- decision pending until approved
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Generator

import pytest
from app.graph.client import delete_graph_if_exists, get_db, repo_graph, repo_graph_name
from app.graph.queries import (
    choke_points,
    create_decision,
    entrypoint_stats,
    get_finding,
    list_findings,
    recall,
    save_investigation,
    set_decision_status,
    simulate,
    subgraph,
    trace_paths,
)
from app.graph.schema import ensure_repo_schema
from falkordb import Graph

logger = logging.getLogger(__name__)


@pytest.fixture()
def tiny_repo() -> Generator[tuple[str, Graph], None, None]:
    """Create a temporary repo graph seeded with 2 entrypoints, 3 modules, 3 packages,

    1 vulnerability, and 1 blind spot.
    Always cleans up the graph after the test.
    """
    repo_id = str(uuid.uuid4())
    g = repo_graph(repo_id)

    # Clean slate
    try:
        g.query("MATCH (n) DETACH DELETE n")
    except Exception as exc:  # noqa: BLE001
        logger.debug("Clean slate error: %s", exc)

    ensure_repo_schema(g)

    # Seed the tiny graph:
    # Entrypoints:
    #   - ep-login: public: true
    #   - ep-admin: public: false
    # Modules:
    #   - app.auth (handled by ep-login)
    #   - app.utils (imported by app.auth)
    #   - app.internal (handled by ep-admin)
    # Packages:
    #   - requests@2.25.0 (used by app.utils)
    #   - urllib3@1.26.0 (depended on by requests)
    #   - unused-lib@1.0.0 (in lockfile, never imported)
    # Vulnerability:
    #   - GHSA-test-urllib3 affects urllib3@1.26.0
    # BlindSpot:
    #   - dynamic_import in app.utils
    # Findings:
    #   - find-urllib3 on urllib3@1.26.0
    #   - find-unused on unused-lib@1.0.0
    seed_cypher = """
    CREATE (e1:Entrypoint {id: 'ep-login', method: 'POST', path: '/login', file: 'app/auth.py', line: 10, public: true, auth_hint: ''}),
           (e2:Entrypoint {id: 'ep-admin', method: 'GET', path: '/admin', file: 'app/admin.py', line: 20, public: false, auth_hint: 'admin'}),
           (m1:Module {id: 'app.auth', file: 'app/auth.py', lines: 50}),
           (m2:Module {id: 'app.utils', file: 'app/utils.py', lines: 30}),
           (m3:Module {id: 'app.internal', file: 'app/internal.py', lines: 40}),
           (p1:Package {id: 'requests@2.25.0', name: 'requests', version: '2.25.0', direct: true, ecosystem: 'PyPI'}),
           (p2:Package {id: 'urllib3@1.26.0', name: 'urllib3', version: '1.26.0', direct: false, ecosystem: 'PyPI'}),
           (p3:Package {id: 'unused-lib@1.0.0', name: 'unused-lib', version: '1.0.0', direct: true, ecosystem: 'PyPI'}),
           (v1:Vulnerability {id: 'GHSA-test-urllib3', aliases: ['CVE-2021-9999'], summary: 'Test vuln in urllib3', severity: 'HIGH', fixed_versions: ['1.26.5'], published: '2021-01-01'}),
           (v2:Vulnerability {id: 'GHSA-test-unused', aliases: [], summary: 'Unused vuln', severity: 'LOW', fixed_versions: ['1.0.1'], published: '2021-01-01'}),
           (b1:BlindSpot {id: 'bs-dyn-1', kind: 'dynamic_import', reason: 'Dynamic plugin load', file: 'app/utils.py', line: 15, name: 'plugins'}),
           (f1:Finding {id: 'find-urllib3', status: 'open', first_seen: '2026-10-15T00:00:00Z'}),
           (f2:Finding {id: 'find-unused', status: 'open', first_seen: '2026-10-15T00:00:00Z'})

    CREATE (e1)-[:HANDLED_BY]->(m1),
           (e2)-[:HANDLED_BY]->(m3),
           (m1)-[:IMPORTS]->(m2),
           (m2)-[:USES]->(p1),
           (p1)-[:DEPENDS_ON]->(p2),
           (v1)-[:AFFECTS]->(p2),
           (v2)-[:AFFECTS]->(p3),
           (f1)-[:ABOUT]->(v1),
           (f1)-[:ON_PACKAGE]->(p2),
           (f2)-[:ABOUT]->(v2),
           (f2)-[:ON_PACKAGE]->(p3),
           (m2)-[:HAS_BLINDSPOT]->(b1)
    """
    g.query(seed_cypher)

    yield repo_id, g

    # Teardown
    delete_graph_if_exists(repo_graph_name(repo_id))


# ── Tests ───────────────────────────────────────────────────────


def test_entrypoint_stats(tiny_repo: tuple[str, Graph]) -> None:
    repo_id, _ = tiny_repo
    stats = entrypoint_stats(repo_id)
    assert stats["total"] == 2
    assert stats["total_public"] == 1


def test_trace_paths_reachable_in_order(tiny_repo: tuple[str, Graph]) -> None:
    repo_id, _ = tiny_repo
    res = trace_paths(repo_id, "find-urllib3")

    assert res["finding_id"] == "find-urllib3"
    assert res["verdict"] == "reachable_in_model"
    assert res["reaching_entrypoints"] == 1
    assert res["total_public_entrypoints"] == 1
    assert len(res["paths"]) >= 1

    path0 = res["paths"][0]
    assert path0["entrypoint_id"] == "ep-login"
    assert path0["entrypoint"] == "POST /login"

    # Assert nodes in exact traversal order: Entrypoint -> Module -> Module -> Package -> Package
    node_labels = [n["label"] for n in path0["nodes"]]
    node_ids = [n["id"] for n in path0["nodes"]]

    assert node_labels == ["Entrypoint", "Module", "Module", "Package", "Package"]
    assert node_ids == [
        "ep-login",
        "app.auth",
        "app.utils",
        "requests@2.25.0",
        "urllib3@1.26.0",
    ]

    # Assert edge types in order
    edge_types = [e["type"] for e in path0["edges"]]
    assert edge_types == ["HANDLED_BY", "IMPORTS", "USES", "DEPENDS_ON"]


def test_trace_paths_no_path_found_declared_not_imported(
    tiny_repo: tuple[str, Graph],
) -> None:
    repo_id, _ = tiny_repo
    res = trace_paths(repo_id, "find-unused")

    assert res["verdict"] == "no_path_found"
    assert res["reason"] == "declared_not_imported"
    assert res["paths"] == []
    assert res["reaching_entrypoints"] == 0


def test_trace_paths_unknown_via_dynamic_import(tiny_repo: tuple[str, Graph]) -> None:
    repo_id, g = tiny_repo

    # Add a package and finding that is imported only by an isolated module (no public path),
    # but the reachable module m2 has blind spot dynamic_import.
    g.query("""
    CREATE (m_iso:Module {id: 'app.iso', file: 'app/iso.py', lines: 10}),
           (p_iso:Package {id: 'isolated@1.0', name: 'isolated', version: '1.0', direct: true, ecosystem: 'PyPI'}),
           (v_iso:Vulnerability {id: 'GHSA-iso', severity: 'MODERATE'}),
           (f_iso:Finding {id: 'find-iso', status: 'open'})
    CREATE (m_iso)-[:USES]->(p_iso),
           (v_iso)-[:AFFECTS]->(p_iso),
           (f_iso)-[:ABOUT]->(v_iso),
           (f_iso)-[:ON_PACKAGE]->(p_iso)
    """)

    res = trace_paths(repo_id, "find-iso")
    assert res["verdict"] == "unknown"
    assert "dynamic_import" in res["reason"]
    assert len(res["blind_spots"]) >= 1


def test_simulate_flips_reachable_to_no_path_found(tiny_repo: tuple[str, Graph]) -> None:
    repo_id, _ = tiny_repo
    db = get_db()

    # Before simulate: finding is reachable
    before = trace_paths(repo_id, "find-urllib3")
    assert before["verdict"] == "reachable_in_model"

    # Run simulate: add_auth to ep-login making it non-public
    sim_res = simulate(
        repo_id,
        "find-urllib3",
        [{"type": "add_auth", "entrypoint_id": "ep-login"}],
    )

    assert sim_res["before"]["verdict"] == "reachable_in_model"
    assert sim_res["after"]["verdict"] in ("no_path_found", "unknown")
    assert len(sim_res["changed"]) == 1
    assert sim_res["changed"][0]["finding_id"] == "find-urllib3"
    assert sim_res["changed"][0]["from"] == "reachable_in_model"

    # Assert the real graph was NOT modified
    after_real = trace_paths(repo_id, "find-urllib3")
    assert after_real["verdict"] == "reachable_in_model"

    # Assert no leftover simulation graphs exist
    leftovers = [name for name in db.list_graphs() if name.startswith("rg_sim_")]
    assert leftovers == []


def test_choke_points(tiny_repo: tuple[str, Graph]) -> None:
    repo_id, _ = tiny_repo
    cps = choke_points(repo_id)

    assert len(cps) >= 1
    pkg_names = [c["package"] for c in cps]
    # Both requests and urllib3 are on the path to the reachable finding
    assert "requests" in pkg_names or "urllib3" in pkg_names
    for c in cps:
        assert c["clears_findings"] >= 1
        assert "find-urllib3" in c["finding_ids"]


def test_decision_lifecycle_pending_until_approved(tiny_repo: tuple[str, Graph]) -> None:
    repo_id, _ = tiny_repo

    # accept_risk starts as pending
    dec = create_decision(
        repo_id=repo_id,
        finding_id="find-urllib3",
        by="analyst1",
        type="accept_risk",
        reason="Testing risk acceptance workflow",
        expires_at=None,
    )

    assert dec["status"] == "pending"
    assert dec["approved_by"] is None
    assert dec["type"] == "accept_risk"

    # Finding status is not yet risk_accepted while pending
    finding_pending = get_finding(repo_id, "find-urllib3")
    assert finding_pending is not None
    assert finding_pending["status"] == "open"

    # Approve decision
    approved = set_decision_status(
        repo_id=repo_id,
        decision_id=dec["id"],
        status="approved",
        by="admin1",
    )
    assert approved["status"] == "approved"
    assert approved["approved_by"] == "admin1"

    # Now finding status reflects risk_accepted
    finding_approved = get_finding(repo_id, "find-urllib3")
    assert finding_approved is not None
    assert finding_approved["status"] == "risk_accepted"

    # Attempting to re-update an already approved decision raises ValueError
    with pytest.raises(ValueError, match="is not pending"):
        set_decision_status(
            repo_id=repo_id,
            decision_id=dec["id"],
            status="rejected",
            by="admin2",
        )


def test_investigation_and_recall(tiny_repo: tuple[str, Graph]) -> None:
    repo_id, _ = tiny_repo

    inv_id = save_investigation(
        repo_id=repo_id,
        finding_id="find-urllib3",
        by="analyst1",
        verdict="reachable_in_model",
        score=75,
        path_json='{"paths": []}',
        summary="Verified reachable through POST /login",
        session_id="session-123",
    )
    assert len(inv_id) == 12

    mem = recall(repo_id, "find-urllib3")
    assert len(mem["investigations"]) >= 1
    assert mem["investigations"][0]["id"] == inv_id
    assert mem["investigations"][0]["summary"] == "Verified reachable through POST /login"

    all_mem = recall(repo_id, None)
    assert len(all_mem["investigations"]) >= 1


def test_list_and_get_findings(tiny_repo: tuple[str, Graph]) -> None:
    repo_id, _ = tiny_repo

    findings = list_findings(repo_id)
    assert len(findings) == 2
    f_ids = [f["id"] for f in findings]
    assert "find-urllib3" in f_ids
    assert "find-unused" in f_ids

    # find-urllib3 is reachable and high severity, so should have higher score than unused
    assert findings[0]["id"] == "find-urllib3"
    assert findings[0]["score"] > findings[1]["score"]

    # get_finding
    detail = get_finding(repo_id, "find-urllib3")
    assert detail is not None
    assert detail["verdict"] == "reachable_in_model"
    assert "score_breakdown" in detail
    assert "trace" in detail


def test_subgraph_queries(tiny_repo: tuple[str, Graph]) -> None:
    repo_id, _ = tiny_repo

    # Subgraph with finding_id
    sub_f = subgraph(repo_id, "find-urllib3")
    assert "nodes" in sub_f
    assert "edges" in sub_f
    assert "highlight" in sub_f
    assert len(sub_f["highlight"]["nodes"]) >= 1

    # Subgraph without finding_id (summary graph)
    sub_summary = subgraph(repo_id, None)
    assert "nodes" in sub_summary
    assert "edges" in sub_summary
    assert sub_summary["highlight"]["nodes"] == []
