"""
FalkorDB graph client — single source of truth for connections and graph names.

Every graph interaction in the codebase goes through this module.
Graph names are built ONLY by the helpers here; no other module should
concatenate graph name strings.
"""

from __future__ import annotations

import logging
import re
import uuid
from functools import lru_cache
from typing import Any

from falkordb import FalkorDB, Graph

from app.config import settings

logger = logging.getLogger(__name__)

# ── Connection ──────────────────────────────────────────────────

_UUID4_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$",
    re.IGNORECASE,
)


@lru_cache(maxsize=1)
def get_db() -> FalkorDB:
    """Return a lazily-created, cached FalkorDB connection."""
    password = settings.FALKORDB_PASSWORD or None
    logger.info(
        "Connecting to FalkorDB at %s:%s", settings.FALKORDB_HOST, settings.FALKORDB_PORT
    )
    return FalkorDB(
        host=settings.FALKORDB_HOST,
        port=settings.FALKORDB_PORT,
        password=password,
    )


# ── Graph name builders ────────────────────────────────────────


def _validate_uuid4(value: str) -> str:
    """Validate that *value* is a canonical UUID4 string. Returns the value.

    Raises ``ValueError`` for anything else (path traversal, random strings, …).
    """
    if not _UUID4_RE.match(value):
        raise ValueError(f"Invalid UUID4: {value!r}")
    # Extra sanity: round-trip through stdlib to reject crafted strings
    parsed = uuid.UUID(value, version=4)
    if str(parsed) != value.lower():
        raise ValueError(f"UUID4 round-trip failed for {value!r}")
    return value


def _prefix() -> str:
    p = settings.GRAPH_PREFIX.strip() if settings.GRAPH_PREFIX else "rg"
    return p


def meta_graph_name() -> str:
    """Return the meta-graph name."""
    return f"{_prefix()}_meta"


def meta_graph() -> Graph:
    """Return the singleton meta-graph ``<prefix>_meta``."""
    return get_db().select_graph(meta_graph_name())


def global_graph_name() -> str:
    """Return the cross-repo knowledge graph name."""
    return f"{_prefix()}_global"


def global_graph() -> Graph:
    """Return the singleton cross-repo knowledge graph ``<prefix>_global``."""
    return get_db().select_graph(global_graph_name())


def repo_graph_name(repo_id: str) -> str:
    """Build a graph name for a repository.

    ``repo_id`` must be a valid UUID4 string.  The returned name is
    ``f"{prefix}_repo_"`` followed by the UUID with dashes replaced by underscores.

    This is the **ONLY** place repository graph names are constructed.
    """
    _validate_uuid4(repo_id)
    return f"{_prefix()}_repo_" + repo_id.replace("-", "_")


def repo_graph(repo_id: str) -> Graph:
    """Return a Graph handle for the given repo UUID."""
    return get_db().select_graph(repo_graph_name(repo_id))


def sim_graph_name() -> str:
    """Generate a unique simulation graph name (``<prefix>_sim_<hex>``)."""
    return f"{_prefix()}_sim_" + uuid.uuid4().hex


# ── Query runner ────────────────────────────────────────────────


def run(graph: Graph, cypher: str, params: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    """Execute *cypher* on *graph* and return rows as a list of dicts.

    Column names come from the result header.  Parameters must be passed
    via ``params`` — **never** format user input into the Cypher string.
    """
    result = graph.query(cypher, params=params)
    # result.header is a list of [column_type, column_name] pairs
    headers = [h[1] for h in result.header]
    return [
        {h: row[i] for i, h in enumerate(headers)}
        for row in result.result_set
    ]


# ── Lifecycle helpers ───────────────────────────────────────────


def delete_graph_if_exists(name: str) -> None:
    """Delete a graph by name, ignoring "unknown graph" errors."""
    try:
        get_db().select_graph(name).delete()
        logger.info("Deleted graph %s", name)
    except Exception as exc:
        # FalkorDB raises a ResponseError when the graph doesn't exist.
        # The message varies by version; catch the known patterns.
        msg = str(exc).lower()
        if "unknown graph" in msg or "empty key" in msg:
            logger.debug("Graph %s did not exist — nothing to delete", name)
        else:
            raise


def cleanup_sim_graphs() -> None:
    """Delete every graph whose name starts with ``<prefix>_sim_`` or ``rg_sim_``.

    Called at application startup to remove stale simulation graphs.
    """
    db = get_db()
    prefix = _prefix()
    sim_prefixes = (f"{prefix}_sim_", "rg_sim_")
    for name in db.list_graphs():
        if any(name.startswith(p) for p in sim_prefixes):
            try:
                db.select_graph(name).delete()
                logger.info("Cleaned up simulation graph %s", name)
            except Exception:
                logger.warning("Failed to clean up %s", name, exc_info=True)
