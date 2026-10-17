"""
Tests for Cross-Repository Global Memory (rg_global).

Verifies:
1. global_graph() returns graph "rg_global", schema creates index on Pattern(name).
2. UPSERT (:Pattern {name: normalized pattern})-[:LEARNED_FROM]->(:Decision copy) into rg_global
   on admin approval: package name for accept_risk/false_positive, or vuln alias prefix for fixed.
3. global_recall tool and queries.global_recall finds learned patterns from foreign repos.
4. Rule: rg_global is written ONLY on admin-approved decisions. Viewers/analysts never write it.
5. End-to-end test: approve a decision in repo A, global_recall finds it from repo B's context.
   Agent trace_path includes "This pattern was previously <decision type> on <date> by <user>: <reason>".
   Test data cleaned up at end.
"""

from __future__ import annotations

import uuid
from collections.abc import Generator

import pytest
from app.agent.loop import run_agent
from app.agent.tools import ToolContext
from app.agent.tools import global_recall as global_recall_tool
from app.config import settings
from app.graph import queries
from app.graph.client import (
    delete_graph_if_exists,
    global_graph,
    repo_graph,
    repo_graph_name,
    run,
)
from app.graph.schema import ensure_global_schema, ensure_repo_schema


@pytest.fixture
def clean_global_patterns() -> Generator[list[str], None, None]:
    """Track pattern names and decision IDs created during test to clean them up at teardown."""
    tracked_repo_ids: list[str] = []
    yield tracked_repo_ids

    # Teardown
    gg = global_graph()
    try:
        if tracked_repo_ids:
            run(
                gg,
                """
                MATCH (p:Pattern)-[r:LEARNED_FROM]->(d:Decision)
                WHERE d.repo_id IN $rids
                DETACH DELETE p, d
                """,
                {"rids": tracked_repo_ids},
            )
            for rid in tracked_repo_ids:
                delete_graph_if_exists(repo_graph_name(rid))
    except Exception:
        pass


def test_global_graph_and_schema() -> None:
    """Verify global_graph returns <prefix>_global and schema creates Pattern(name) index idempotently."""
    g = global_graph()
    assert g.name == f"{settings.GRAPH_PREFIX}_global"

    # Schema creation must be idempotent
    ensure_global_schema()
    ensure_global_schema()


def test_rule_rg_global_only_written_on_admin_approval(clean_global_patterns: list[str]) -> None:
    """Rule: rg_global is written ONLY on admin-approved decisions. Viewers/analysts never write it."""
    repo_id = str(uuid.uuid4())
    clean_global_patterns.append(repo_id)

    g = repo_graph(repo_id)
    ensure_repo_schema(g)

    # Seed finding in repo
    finding_id = uuid.uuid4().hex[:12]
    seed_cypher = """
    CREATE (p:Package {id: 'requests@2.25.0', name: 'requests', version: '2.25.0', direct: true, ecosystem: 'PyPI'}),
           (v:Vulnerability {id: 'GHSA-requests-01', aliases: ['CVE-2023-1111'], summary: 'Requests test vuln', severity: 'HIGH'}),
           (f:Finding {id: $fid, status: 'open', first_seen: '2026-10-15T00:00:00Z'})
    CREATE (v)-[:AFFECTS]->(p),
           (f)-[:ABOUT]->(v),
           (f)-[:ON_PACKAGE]->(p)
    """
    run(g, seed_cypher, {"fid": finding_id})

    # 1. Analyst creates a pending decision
    dec = queries.create_decision(
        repo_id=repo_id,
        finding_id=finding_id,
        by="analyst@example.com",
        type="accept_risk",
        reason="Assessed by analyst as mitigated by network isolation",
        expires_at=None,
    )
    assert dec["status"] == "pending"

    # Check rg_global: no Pattern should exist yet
    hits_before = queries.global_recall("requests")
    assert not any(h.get("repo_id") == repo_id for h in hits_before)

    # 2. Analyst attempts to approve decision -> should NOT write to rg_global
    queries.set_decision_status(
        repo_id=repo_id,
        decision_id=dec["id"],
        status="approved",
        by="analyst@example.com",
    )
    hits_after_analyst = queries.global_recall("requests")
    assert not any(h.get("repo_id") == repo_id for h in hits_after_analyst)


def test_cross_repo_memory_and_agent_recall(clean_global_patterns: list[str]) -> None:
    """Approve a decision in Repo A, global_recall finds it from Repo B's context.

    Agent trace_path on Repo B includes:
    'This pattern was previously <decision type> on <date> by <user>: <reason>'
    """
    repo_a = str(uuid.uuid4())
    repo_b = str(uuid.uuid4())
    clean_global_patterns.extend([repo_a, repo_b])

    # Clean existing test patterns from previous test runs if any
    gg = global_graph()
    try:
        run(gg, "MATCH (p:Pattern {name: 'urllib3'})-[r:LEARNED_FROM]->(d:Decision) DETACH DELETE p, d")
    except Exception:
        pass

    # 1. Setup Repo A
    ga = repo_graph(repo_a)
    ensure_repo_schema(ga)
    find_a_id = uuid.uuid4().hex[:12]
    seed_a = """
    CREATE (e:Entrypoint {id: 'ep-a', method: 'GET', path: '/api/v1/health', file: 'app/main.py', line: 10, public: true, auth_hint: ''}),
           (m:Module {id: 'app.main', file: 'app/main.py', lines: 40}),
           (p:Package {id: 'urllib3@1.26.0', name: 'urllib3', version: '1.26.0', direct: true, ecosystem: 'PyPI'}),
           (v:Vulnerability {id: 'GHSA-urllib3-001', aliases: ['CVE-2021-9999'], summary: 'Urllib3 vuln', severity: 'HIGH'}),
           (f:Finding {id: $fid, status: 'open', first_seen: '2026-10-15T00:00:00Z'})
    CREATE (e)-[:HANDLED_BY]->(m),
           (m)-[:USES]->(p),
           (v)-[:AFFECTS]->(p),
           (f)-[:ABOUT]->(v),
           (f)-[:ON_PACKAGE]->(p)
    """
    run(ga, seed_a, {"fid": find_a_id})

    # Record decision in Repo A
    dec_a = queries.create_decision(
        repo_id=repo_a,
        finding_id=find_a_id,
        by="analyst1@corp.internal",
        type="accept_risk",
        reason="Mitigated at perimeter gateway timeout configuration",
        expires_at=None,
    )
    assert dec_a["status"] == "pending"

    # Admin approves decision in Repo A
    approved_a = queries.set_decision_status(
        repo_id=repo_a,
        decision_id=dec_a["id"],
        status="approved",
        by="admin1@corp.internal",
    )
    assert approved_a["status"] == "approved"
    assert approved_a["approved_by"] == "admin1@corp.internal"

    # Verify rg_global has pattern for 'urllib3'
    gg = global_graph()
    pattern_rows = run(
        gg,
        """
        MATCH (p:Pattern {name: 'urllib3'})-[:LEARNED_FROM]->(d:Decision {id: $did})
        RETURN p.name as pattern, d.type as type, d.status as status, d.approved_by as approved_by
        """,
        {"did": dec_a["id"]},
    )
    assert len(pattern_rows) == 1
    assert pattern_rows[0]["pattern"] == "urllib3"
    assert pattern_rows[0]["type"] == "accept_risk"
    assert pattern_rows[0]["status"] == "approved"

    # 2. Setup Repo B (completely independent graph)
    gb = repo_graph(repo_b)
    ensure_repo_schema(gb)
    find_b_id = uuid.uuid4().hex[:12]
    seed_b = """
    CREATE (e:Entrypoint {id: 'ep-b', method: 'POST', path: '/checkout', file: 'service/pay.py', line: 15, public: true, auth_hint: ''}),
           (m:Module {id: 'service.pay', file: 'service/pay.py', lines: 60}),
           (p:Package {id: 'urllib3@1.26.4', name: 'urllib3', version: '1.26.4', direct: true, ecosystem: 'PyPI'}),
           (v:Vulnerability {id: 'GHSA-urllib3-001', aliases: ['CVE-2021-9999'], summary: 'Urllib3 vuln', severity: 'HIGH'}),
           (f:Finding {id: $fid, status: 'open', first_seen: '2026-10-16T00:00:00Z'})
    CREATE (e)-[:HANDLED_BY]->(m),
           (m)-[:USES]->(p),
           (v)-[:AFFECTS]->(p),
           (f)-[:ABOUT]->(v),
           (f)-[:ON_PACKAGE]->(p)
    """
    run(gb, seed_b, {"fid": find_b_id})

    # 3. Call global_recall from Repo B's context
    ctx_b = ToolContext(repo_id=repo_b, user_role="viewer")
    tool_res = global_recall_tool(ctx_b, package_name="urllib3")
    assert tool_res["ok"] is True
    assert tool_res["count"] >= 1
    hits = tool_res["hits"]
    hit = next((h for h in hits if h.get("id") == dec_a["id"]), None)
    assert hit is not None
    assert hit["type"] == "accept_risk"
    assert hit["reason"] == "Mitigated at perimeter gateway timeout configuration"
    assert hit["approved_by"] == "admin1@corp.internal"

    # 4. Agent calls global_recall during trace_path on Repo B
    # Message mentions finding find_b_id which will execute trace_path
    agent_res = run_agent(ctx_b, message=f"Trace path and reachability for finding {find_b_id}")

    # Tool calls should include global_recall
    tool_names = [tc.get("name") for tc in agent_res.tool_calls]
    assert "trace_path" in tool_names
    assert "global_recall" in tool_names

    # Answer must include:
    # "This pattern was previously <decision type> on <date> by <user>: <reason>"
    expected_phrase = "This pattern was previously accept_risk"
    assert expected_phrase in agent_res.answer
    assert "by admin1@corp.internal: Mitigated at perimeter gateway timeout configuration" in agent_res.answer


def test_fixed_decision_pattern_upsert(clean_global_patterns: list[str]) -> None:
    """Fixed decision pattern uses vuln alias prefix (e.g. CVE-2021 from CVE-2021-9999)."""
    repo_id = str(uuid.uuid4())
    clean_global_patterns.append(repo_id)

    g = repo_graph(repo_id)
    ensure_repo_schema(g)

    finding_id = uuid.uuid4().hex[:12]
    seed_cypher = """
    CREATE (p:Package {id: 'aiohttp@3.7.0', name: 'aiohttp', version: '3.7.0', direct: true, ecosystem: 'PyPI'}),
           (v:Vulnerability {id: 'GHSA-aiohttp-fixed', aliases: ['CVE-2022-3344'], summary: 'Aiohttp header injection', severity: 'MEDIUM'}),
           (f:Finding {id: $fid, status: 'open', first_seen: '2026-10-15T00:00:00Z'})
    CREATE (v)-[:AFFECTS]->(p),
           (f)-[:ABOUT]->(v),
           (f)-[:ON_PACKAGE]->(p)
    """
    run(g, seed_cypher, {"fid": finding_id})

    # Record fixed decision (starts pending or created)
    # Admin approves
    dec = queries.create_decision(
        repo_id=repo_id,
        finding_id=finding_id,
        by="admin@reachguard.io",
        type="fixed",
        reason="Upgraded in base dockerfile to 3.8.1",
        expires_at=None,
    )
    # If type="fixed", create_decision sets status="approved" by default,
    # but rule 2 requires set_decision_status to UPSERT into rg_global.
    # So if status is pending or we call set_decision_status:
    # Let's set it to pending first to test set_decision_status:
    run(g, "MATCH (d:Decision {id: $id}) SET d.status = 'pending'", {"id": dec["id"]})

    queries.set_decision_status(
        repo_id=repo_id,
        decision_id=dec["id"],
        status="approved",
        by="admin@reachguard.io",
    )

    # Alias is CVE-2022-3344 -> pattern prefix is 'cve-2022'
    hits = queries.global_recall("cve-2022")
    assert any(h.get("id") == dec["id"] for h in hits)
    hit = next(h for h in hits if h.get("id") == dec["id"])
    assert hit["pattern_name"] == "cve-2022"
    assert hit["type"] == "fixed"
    assert hit["reason"] == "Upgraded in base dockerfile to 3.8.1"
