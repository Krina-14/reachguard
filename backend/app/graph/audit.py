"""
ReachGuard — Audit logging helper.

Creates (:AuditEvent {id, at, actor, action, target}) nodes in rg_meta.
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime

from app.graph.client import meta_graph, run

logger = logging.getLogger(__name__)


def write_audit_event(actor: str, action: str, target: str = "") -> None:
    """Create an (:AuditEvent) node in the meta graph.

    Satisfies Contract Section 4: {id, at, actor, action, target}.
    """
    g = meta_graph()
    aid = uuid.uuid4().hex
    now = datetime.now(UTC).isoformat()
    cypher = """
    CREATE (:AuditEvent {
        id: $id,
        at: $at,
        actor: $actor,
        action: $action,
        target: $target,
        event: $action,
        actor_email: $actor,
        detail: $target,
        ts: $at
    })
    """
    try:
        run(
            g,
            cypher,
            params={
                "id": aid,
                "at": now,
                "actor": actor,
                "action": action,
                "target": target,
            },
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("Failed to write audit event '%s': %s", action, exc)
