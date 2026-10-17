"""
Pytest configuration for ReachGuard backend test suite.

Contract Requirement:
Sets GRAPH_PREFIX to 'rgtest_' + random hex and, at session end,
deletes every graph with that prefix so tests never touch dev graphs.
"""

from __future__ import annotations

import os
import uuid

# Set test environment prefix before importing application settings
_TEST_PREFIX = f"rgtest_{uuid.uuid4().hex[:8]}"
os.environ["GRAPH_PREFIX"] = _TEST_PREFIX

import pytest  # noqa: E402
from app.config import settings  # noqa: E402
from app.graph.client import get_db  # noqa: E402
from app.graph.schema import ensure_global_schema, ensure_meta_schema  # noqa: E402

settings.GRAPH_PREFIX = _TEST_PREFIX


@pytest.fixture(scope="session", autouse=True)
def isolated_test_graphs():
    """Initialize schemas on isolated test graphs, and clean them all up at session end."""
    try:
        ensure_meta_schema()
        ensure_global_schema()
    except Exception:
        pass

    yield

    try:
        db = get_db()
        for name in db.list_graphs():
            if name.startswith(_TEST_PREFIX):
                try:
                    db.select_graph(name).delete()
                except Exception:
                    pass
    except Exception:
        pass
