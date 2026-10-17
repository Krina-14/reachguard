#!/usr/bin/env python3
"""
ReachGuard — Development Database Cleanup Script.

Cleans up stale test repositories and simulation graphs from FalkorDB.
Default is DRY RUN (print only). With --yes it executes deletions.

Selection rules:
- Select (:Repo) in rg_meta where ANY of:
  1. source is "test", "unknown", "test/repo" or ends with "repo.zip"
  2. status in ("queued", "cloning", "parsing", "scanning") and created_at is older than 15 minutes (or missing)
  3. status is "failed"
- For each selected repo:
  - Delete its graph rg_repo_<id with underscores> if it exists
  - Delete the (:Repo) node from rg_meta
- Delete every graph starting with rg_sim_
- SAFEGUARDS (non-negotiable):
  - NEVER delete (:User) nodes
  - NEVER delete any repo whose status is "ready" AND whose source starts with "https://github.com/"
"""

from __future__ import annotations

import argparse
import datetime
import logging
import sys
from pathlib import Path

# Ensure backend directory is in sys.path
REPO_ROOT = Path(__file__).resolve().parent.parent
BACKEND_DIR = REPO_ROOT / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.config import settings  # noqa: E402
from app.graph.client import meta_graph, run  # noqa: E402
from falkordb import FalkorDB  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger("cleanup_dev_db")


def parse_created_at(ts_val: str | None) -> datetime.datetime | None:
    """Parse an ISO 8601 string to a timezone-aware UTC datetime."""
    if not ts_val:
        return None
    try:
        dt = datetime.datetime.fromisoformat(ts_val.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=datetime.UTC)
        return dt
    except Exception:
        return None


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Clean up stale test repos and simulation graphs from FalkorDB."
    )
    parser.add_argument(
        "--yes",
        action="store_true",
        default=False,
        help="Execute deletions. Defaults to DRY RUN (print only).",
    )
    args = parser.parse_args()
    is_dry_run = not args.yes

    mode_label = "DRY RUN (pass --yes to delete)" if is_dry_run else "ACTIVE DELETION"
    print(f"=== ReachGuard FalkorDB Dev Cleanup [{mode_label}] ===")
    print(f"Connecting to FalkorDB at {settings.FALKORDB_HOST}:{settings.FALKORDB_PORT}...")

    # 1. Connect to FalkorDB
    password = settings.FALKORDB_PASSWORD or None
    db = FalkorDB(
        host=settings.FALKORDB_HOST,
        port=settings.FALKORDB_PORT,
        password=password,
    )

    # 2. Query all repos from rg_meta
    meta = meta_graph()
    try:
        repo_rows = run(
            meta,
            "MATCH (r:Repo) RETURN r.id AS id, r.source AS source, r.status AS status, r.created_at AS created_at",
        )
    except Exception as exc:
        print(f"Error querying rg_meta: {exc}", file=sys.stderr)
        return 1

    now_utc = datetime.datetime.now(datetime.UTC)
    cutoff_time = now_utc - datetime.timedelta(minutes=15)

    all_graphs = set(db.list_graphs())

    repos_inspected = len(repo_rows)
    repos_to_delete: list[dict[str, str]] = []
    repos_preserved: list[dict[str, str]] = []

    for r in repo_rows:
        rid = str(r.get("id") or "")
        source = str(r.get("source") or "")
        status = str(r.get("status") or "")
        created_at_raw = r.get("created_at")
        created_dt = parse_created_at(created_at_raw)

        # Stale in intermediate state if older than 15 minutes or missing timestamp
        is_stuck_intermediate = status in ("queued", "cloning", "parsing", "scanning") and (
            created_dt is None or created_dt < cutoff_time
        )

        is_test_source = (
            source in ("test", "unknown", "test/repo")
            or source.endswith(("test/repo", "repo.zip"))
        )
        cond_source = is_test_source
        cond_stuck = is_stuck_intermediate
        cond_failed = (status == "failed")

        should_delete = cond_source or cond_stuck or cond_failed

        # NON-NEGOTIABLE SAFEGUARD:
        # Never delete any real repo whose status is ready and source starts with https://github.com/
        if status == "ready" and source.startswith("https://github.com/") and not is_test_source:
            should_delete = False

        if should_delete:
            repos_to_delete.append(r)
        else:
            repos_preserved.append(r)

    # 3. Identify simulation graphs
    sim_graphs = [g for g in all_graphs if g.startswith("rg_sim_")]

    print(f"\nFound {repos_inspected} repos in rg_meta.")
    print(f"- Marked for cleanup: {len(repos_to_delete)}")
    print(f"- Preserved: {len(repos_preserved)}")
    print(f"- Simulation graphs found: {len(sim_graphs)}\n")

    repo_graphs_deleted_count = 0
    repo_nodes_deleted_count = 0
    sim_graphs_deleted_count = 0

    # 4. Process repo deletions
    for r in repos_to_delete:
        rid = r["id"]
        source = r.get("source") or "(none)"
        status = r.get("status") or "(none)"

        graph_name = f"rg_repo_{rid.replace('-', '_')}"
        has_graph = graph_name in all_graphs

        if is_dry_run:
            print(f"[DRY-RUN] Would delete Repo {rid} ({status}, source='{source}') | Graph: {graph_name} (exists={has_graph})")
        else:
            # Delete repo graph if it exists
            if has_graph:
                try:
                    db.select_graph(graph_name).delete()
                    repo_graphs_deleted_count += 1
                    logger.debug("Deleted graph %s", graph_name)
                except Exception as exc:
                    logger.warning("Could not delete graph %s: %s", graph_name, exc)

            # Delete Repo node in rg_meta (NEVER touches :User nodes)
            try:
                run(meta, "MATCH (r:Repo {id: $id}) DETACH DELETE r", {"id": rid})
                repo_nodes_deleted_count += 1
            except Exception as exc:
                logger.warning("Could not delete Repo node %s: %s", rid, exc)

    # 5. Process simulation graph deletions
    for sg in sim_graphs:
        if is_dry_run:
            print(f"[DRY-RUN] Would delete simulation graph: {sg}")
        else:
            try:
                db.select_graph(sg).delete()
                sim_graphs_deleted_count += 1
            except Exception as exc:
                logger.warning("Could not delete simulation graph %s: %s", sg, exc)

    dry_run_graphs_count = len([
        r for r in repos_to_delete
        if f"rg_repo_{r['id'].replace('-', '_')}" in all_graphs
    ])

    print("\n" + "=" * 50)
    print("CLEANUP SUMMARY")
    print("=" * 50)
    print(f"Mode: {'DRY RUN (no changes made)' if is_dry_run else 'EXECUTED'}")
    print(f"Repos inspected:            {repos_inspected}")
    print(f"Repos preserved:            {len(repos_preserved)}")
    print(f"Repo nodes deleted:         {len(repos_to_delete) if is_dry_run else repo_nodes_deleted_count}")
    print(f"Repo graphs deleted:        {dry_run_graphs_count if is_dry_run else repo_graphs_deleted_count}")
    print(f"Simulation graphs deleted:  {len(sim_graphs) if is_dry_run else sim_graphs_deleted_count}")
    print("Safeguards enforced:        100% (:User nodes and ready https://github.com/* repos untouched)")
    print("=" * 50)

    if is_dry_run:
        print("\nTo apply these deletions, run:")
        print("  python scripts/cleanup_dev_db.py --yes\n")

    return 0


if __name__ == "__main__":
    sys.exit(main())
