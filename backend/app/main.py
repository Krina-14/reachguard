"""
ReachGuard — FastAPI application entry point.

Provides:
- GET /api/health  (public, no auth)
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, FastAPI

from app.config import settings

logger = logging.getLogger(__name__)

app = FastAPI(
    title="ReachGuard",
    version="0.1.0",
    docs_url="/api/docs",
    openapi_url="/api/openapi.json",
)

api_router = APIRouter(prefix="/api")


# ── Health endpoint ──────────────────────────────────────────────


def _check_falkordb() -> bool:
    """Return True if FalkorDB is reachable, False otherwise. Never raises."""
    try:
        from falkordb import FalkorDB

        db = FalkorDB(
            host=settings.FALKORDB_HOST,
            port=settings.FALKORDB_PORT,
            password=settings.FALKORDB_PASSWORD or None,
        )
        db.connection.ping()
        return True
    except Exception:
        logger.debug("FalkorDB health-check failed", exc_info=True)
        return False


@api_router.get("/health")
async def health() -> dict:
    """Public health endpoint per contract Section 7."""
    falkordb_ok = _check_falkordb()

    return {
        "status": "ok",
        "falkordb": falkordb_ok,
        "llm": {
            "provider": "none",
            "model": "",
            "reachable": False,
            "mode": "deterministic",
        },
        "version": "0.1.0",
    }


app.include_router(api_router)
