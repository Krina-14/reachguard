"""
Tests for backend/app/graph/client.py and schema.py.

Requires a running FalkorDB instance (localhost:6379 by default).
Uses a temporary graph that is cleaned up after each test.
"""

from __future__ import annotations

import uuid

import pytest
from app.graph.client import (
    cleanup_sim_graphs,
    delete_graph_if_exists,
    get_db,
    meta_graph,
    repo_graph,
    repo_graph_name,
    run,
    sim_graph_name,
)
from app.graph.schema import _create_index, ensure_meta_schema, ensure_repo_schema
from falkordb import Graph

# ── Fixtures ────────────────────────────────────────────────────

TEMP_GRAPH = "rg_test_client_" + uuid.uuid4().hex[:8]


@pytest.fixture()
def temp_graph() -> Graph:
    """Provide a fresh temporary graph, deleted after the test."""
    db = get_db()
    g = db.select_graph(TEMP_GRAPH)
    # Ensure it's empty
    try:
        g.query("MATCH (n) DETACH DELETE n")
    except Exception:
        pass
    yield g
    # Cleanup
    try:
        g.delete()
    except Exception:
        pass


# ── repo_graph_name ─────────────────────────────────────────────


class TestRepoGraphName:
    """repo_graph_name must validate UUID4 and reject anything else."""

    def test_accepts_valid_uuid4(self) -> None:
        uid = str(uuid.uuid4())
        name = repo_graph_name(uid)
        assert name.startswith("rg_repo_")
        assert "-" not in name  # dashes replaced with underscores
        assert uid.replace("-", "_") in name

    def test_rejects_path_traversal(self) -> None:
        with pytest.raises(ValueError, match="Invalid UUID4"):
            repo_graph_name("../x")

    def test_rejects_empty_string(self) -> None:
        with pytest.raises(ValueError, match="Invalid UUID4"):
            repo_graph_name("")

    def test_rejects_plain_text(self) -> None:
        with pytest.raises(ValueError, match="Invalid UUID4"):
            repo_graph_name("not-a-uuid-at-all")

    def test_rejects_uuid1(self) -> None:
        uid1 = str(uuid.uuid1())
        with pytest.raises(ValueError):
            repo_graph_name(uid1)

    def test_rejects_sql_injection_attempt(self) -> None:
        with pytest.raises(ValueError, match="Invalid UUID4"):
            repo_graph_name("'; DROP TABLE users; --")

    def test_repo_graph_returns_graph_handle(self) -> None:
        uid = str(uuid.uuid4())
        g = repo_graph(uid)
        assert isinstance(g, Graph)


# ── sim_graph_name ──────────────────────────────────────────────


class TestSimGraphName:
    def test_prefix(self) -> None:
        name = sim_graph_name()
        assert name.startswith("rg_sim_")

    def test_uniqueness(self) -> None:
        names = {sim_graph_name() for _ in range(20)}
        assert len(names) == 20


# ── meta_graph ──────────────────────────────────────────────────


class TestMetaGraph:
    def test_returns_graph_named_rg_meta(self) -> None:
        g = meta_graph()
        assert isinstance(g, Graph)


# ── run() round-trip ────────────────────────────────────────────


class TestRun:
    """run() should return a list of dicts keyed by column header names."""

    def test_round_trip(self, temp_graph: Graph) -> None:
        temp_graph.query(
            "CREATE (a:T {id: 'x', val: 42}), (b:T {id: 'y', val: 99})"
        )
        rows = run(temp_graph, "MATCH (n:T) RETURN n.id AS id, n.val AS val ORDER BY n.id")
        assert len(rows) == 2
        assert rows[0] == {"id": "x", "val": 42}
        assert rows[1] == {"id": "y", "val": 99}

    def test_parameterized_query(self, temp_graph: Graph) -> None:
        temp_graph.query("CREATE (:T {id: 'p1'}), (:T {id: 'p2'})")
        rows = run(
            temp_graph,
            "MATCH (n:T {id: $target}) RETURN n.id AS id",
            params={"target": "p1"},
        )
        assert len(rows) == 1
        assert rows[0]["id"] == "p1"

    def test_empty_result(self, temp_graph: Graph) -> None:
        rows = run(temp_graph, "MATCH (n:DoesNotExist) RETURN n.id AS id")
        assert rows == []


# ── delete_graph_if_exists ──────────────────────────────────────


class TestDeleteGraphIfExists:
    def test_deletes_existing_graph(self) -> None:
        name = "rg_test_delete_" + uuid.uuid4().hex[:8]
        db = get_db()
        g = db.select_graph(name)
        g.query("CREATE (:Tmp {x: 1})")
        assert name in db.list_graphs()

        delete_graph_if_exists(name)
        assert name not in db.list_graphs()

    def test_ignores_nonexistent_graph(self) -> None:
        # Should not raise
        delete_graph_if_exists("rg_definitely_does_not_exist_" + uuid.uuid4().hex)


# ── cleanup_sim_graphs ─────────────────────────────────────────


class TestCleanupSimGraphs:
    def test_removes_sim_graphs(self) -> None:
        db = get_db()
        # Create two sim graphs
        names = [sim_graph_name(), sim_graph_name()]
        for n in names:
            g = db.select_graph(n)
            g.query("CREATE (:Tmp {x: 1})")

        for n in names:
            assert n in db.list_graphs()

        cleanup_sim_graphs()

        current = db.list_graphs()
        for n in names:
            assert n not in current


# ── schema ──────────────────────────────────────────────────────


class TestSchema:
    def test_create_index_idempotent(self, temp_graph: Graph) -> None:
        """Creating the same index twice should not raise."""
        temp_graph.query("CREATE (:Probe {name: 'test'})")
        _create_index(temp_graph, "Probe", "name")
        # Second call should be silently ignored
        _create_index(temp_graph, "Probe", "name")

    def test_ensure_meta_schema(self) -> None:
        """ensure_meta_schema should complete without error (idempotent)."""
        ensure_meta_schema()
        ensure_meta_schema()  # second call should also be fine

    def test_ensure_repo_schema(self, temp_graph: Graph) -> None:
        """ensure_repo_schema should create indexes without error."""
        # Seed some data so the labels exist
        temp_graph.query(
            "CREATE (:Entrypoint {id:'e1'}), (:Module {id:'m1'}), "
            "(:Package {id:'p1', name:'pkg'}), (:Vulnerability {id:'v1'}), "
            "(:Finding {id:'f1'}), (:Investigation {id:'i1'}), (:Decision {id:'d1'})"
        )
        ensure_repo_schema(temp_graph)
        # Idempotent
        ensure_repo_schema(temp_graph)
