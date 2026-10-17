"""
FalkorDB schema management — index creation for meta and repo graphs.

Index creation is idempotent: "already indexed" errors are silently
ignored while any other error is re-raised.
"""

from __future__ import annotations

import logging

from falkordb import Graph

from app.graph.client import global_graph, meta_graph

logger = logging.getLogger(__name__)

# ── Helpers ─────────────────────────────────────────────────────


def _create_index(graph: Graph, label: str, prop: str) -> None:
    """Create a node property index, ignoring 'already indexed' errors."""
    cypher = f"CREATE INDEX FOR (n:{label}) ON (n.{prop})"
    try:
        graph.query(cypher)
        logger.info("Created index %s(%s)", label, prop)
    except Exception as exc:
        msg = str(exc).lower()
        if "already indexed" in msg or "already exists" in msg:
            logger.debug("Index %s(%s) already exists — skipping", label, prop)
        else:
            raise


# ── Meta graph schema ──────────────────────────────────────────


def ensure_meta_schema() -> None:
    """Create required indexes on the ``rg_meta`` graph.

    Indexes:
    - User(email)
    - User(id)
    - Repo(id)
    """
    g = meta_graph()
    _create_index(g, "User", "email")
    _create_index(g, "User", "id")
    _create_index(g, "Repo", "id")


# ── Global graph schema ────────────────────────────────────────


def ensure_global_schema() -> None:
    """Create required indexes on the ``rg_global`` graph.

    Indexes:
    - Pattern(name)
    """
    g = global_graph()
    _create_index(g, "Pattern", "name")


# ── Repo graph schema ─────────────────────────────────────────


def ensure_repo_schema(graph: Graph) -> None:
    """Create required indexes on a per-repository graph.

    Indexes:
    - Entrypoint(id)
    - Module(id)
    - Package(id)
    - Package(name)
    - Vulnerability(id)
    - Finding(id)
    - Investigation(id)
    - Decision(id)
    """
    for label, prop in [
        ("Entrypoint", "id"),
        ("Module", "id"),
        ("Package", "id"),
        ("Package", "name"),
        ("Vulnerability", "id"),
        ("Finding", "id"),
        ("Investigation", "id"),
        ("Decision", "id"),
    ]:
        _create_index(graph, label, prop)
