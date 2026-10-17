"""
ReachGuard — FastAPI application entry point.

Wires together:
- Lifespan: ensure_meta_schema, cleanup_sim_graphs, bootstrap_admin
- CORS from settings
- Global exception handler → {"error": {"code": ..., "message": ...}}
- Routers: /api/health, /api/auth, /api/admin
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, RedirectResponse
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.agent.router import agent_router
from app.api.findings import findings_router
from app.api.memory import decisions_router, memory_router
from app.api.whatif import whatif_router
from app.auth.router import admin_router, auth_router, limiter
from app.auth.service import bootstrap_admin
from app.config import settings
from app.graph.client import cleanup_sim_graphs, get_db
from app.graph.schema import ensure_global_schema, ensure_meta_schema
from app.ingest.router import repos_router

logger = logging.getLogger(__name__)


# ── Lifespan ────────────────────────────────────────────────────


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    """Run startup tasks before yielding, cleanup after."""
    logger.info("Starting ReachGuard v0.1.0 (env=%s)", settings.APP_ENV)

    # 1. Schema indexes
    try:
        ensure_meta_schema()
        ensure_global_schema()
        logger.info("Meta and global schema ensured")
    except Exception:
        logger.exception("Failed to ensure schemas")

    # 2. Clean stale simulation graphs
    try:
        cleanup_sim_graphs()
    except Exception:
        logger.exception("Failed to clean sim graphs")

    # 3. Startup reaper: mark in-progress repos older than 15 minutes as failed
    try:
        from app.ingest.router import reap_stale_repos

        reaped = reap_stale_repos(max_age_minutes=15)
        if reaped > 0:
            logger.info("Startup reaper marked %d stale repos as failed", reaped)
    except Exception:
        logger.exception("Failed to run startup reaper")

    # 4. Bootstrap admin
    try:
        bootstrap_admin()
    except Exception:
        logger.exception("Failed to bootstrap admin")

    yield  # ── app is running ──

    logger.info("Shutting down ReachGuard")


# ── App ─────────────────────────────────────────────────────────

app = FastAPI(
    title="ReachGuard",
    version="0.1.0",
    docs_url="/api/docs",
    openapi_url="/api/openapi.json",
    lifespan=lifespan,
)

# ── CORS ────────────────────────────────────────────────────────

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Rate limiter state ──────────────────────────────────────────

app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)


# ── Global exception handler ───────────────────────────────────


@app.exception_handler(HTTPException)
async def http_exception_handler(_request: Request, exc: HTTPException) -> JSONResponse:
    """Return every HTTP error in the standard envelope."""
    return JSONResponse(
        status_code=exc.status_code,
        content={"error": {"code": exc.status_code, "message": exc.detail}},
    )


# Starlette's built-in 404/405 raises StarletteHTTPException, not FastAPI's subclass
@app.exception_handler(StarletteHTTPException)
async def starlette_exception_handler(_request: Request, exc: StarletteHTTPException) -> JSONResponse:
    """Catch Starlette-level HTTP errors (404, 405, etc.) in the standard envelope."""
    return JSONResponse(
        status_code=exc.status_code,
        content={"error": {"code": exc.status_code, "message": exc.detail}},
    )


@app.exception_handler(Exception)
async def unhandled_exception_handler(_request: Request, exc: Exception) -> JSONResponse:
    """Catch-all for unhandled exceptions."""
    logger.error("Unhandled exception", exc_info=exc)
    return JSONResponse(
        status_code=500,
        content={"error": {"code": 500, "message": "Internal server error"}},
    )


# ── Health endpoint ─────────────────────────────────────────────


def _check_falkordb() -> bool:
    """Return True if FalkorDB is reachable, False otherwise. Never raises."""
    try:
        get_db().connection.ping()
        return True
    except Exception:
        logger.debug("FalkorDB health-check failed", exc_info=True)
        return False


def _check_llm() -> dict:
    """Return LLM health status.

    Tries to import app.agent.llm.health() (will be added by Member-3).
    Falls back to a placeholder reporting unreachable.
    """
    try:
        from app.agent.llm import health as llm_health
        return llm_health()
    except Exception:  # noqa: BLE001
        return {
            "provider": settings.LLM_PROVIDER,
            "model": settings.LLM_MODEL,
            "reachable": False,
            "mode": "deterministic",
        }


@app.get("/api/health")
async def health() -> dict:
    """Public health endpoint per contract Section 7."""
    return {
        "status": "ok",
        "falkordb": _check_falkordb(),
        "llm": _check_llm(),
        "version": "0.1.0",
    }


@app.get("/docs", include_in_schema=False)
async def docs_redirect() -> RedirectResponse:
    """Redirect /docs to /api/docs."""
    return RedirectResponse(url="/api/docs")


# ── Include routers ─────────────────────────────────────────────

app.include_router(auth_router)
app.include_router(admin_router)
app.include_router(repos_router)
app.include_router(findings_router)
app.include_router(whatif_router)
app.include_router(memory_router)
app.include_router(decisions_router)
app.include_router(agent_router)
