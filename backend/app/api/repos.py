"""
ReachGuard — Repositories API.

Exposes the repos router defined in app.ingest.router.
"""

from app.ingest.router import repos_router

__all__ = ["repos_router"]
