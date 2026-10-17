"""
ReachGuard — Model Context Protocol (MCP) Server.

Exposes ReachGuard reachability analysis, graph queries, risk scoring,
and algorithmic tools via the Model Context Protocol (MCP) over both
stdio and streamable HTTP (port 8765 in development).

Exposes exactly 9 agent tools:
1. list_findings(repo_id)
2. trace_path(repo_id, finding_id)
3. score_finding(repo_id, finding_id)
4. choke_points(repo_id)
5. simulate(repo_id, changes, finding_id)
6. recall(repo_id, finding_id)
7. save_investigation(repo_id, finding_id, summary) — read-only over MCP (REST-only)
8. critical_modules(repo_id)
9. vulnerability_clusters(repo_id)

All tools delegate directly to app.agent.tools.REGISTRY with ToolContext.
One source of truth, no duplicated logic.

Auth:
- In production (APP_ENV != 'dev' or MCP_API_KEY set): checks 'mcp-api-key' or Bearer header against MCP_API_KEY.
- In dev: no authentication required.
"""

from __future__ import annotations

import logging
import os
from typing import Any

from fastmcp import FastMCP
from starlette.middleware import Middleware
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from app.agent.tools import REGISTRY, ToolContext

logger = logging.getLogger(__name__)

# Initialize FastMCP Server
mcp = FastMCP("ReachGuard MCP Server")


# ── Tool Definitions (Delegating to REGISTRY) ───────────────────


@mcp.tool()
def list_findings(repo_id: str) -> dict[str, Any]:
    """List the top 25 vulnerability findings in the repository with scores, verdicts, and packages.

    Args:
        repo_id: Repository UUID identifier.
    """
    ctx = ToolContext(repo_id=repo_id, user_role="viewer")
    return REGISTRY["list_findings"](ctx)


@mcp.tool()
def trace_path(repo_id: str, finding_id: str) -> dict[str, Any]:
    """Trace reachable execution paths from public entrypoints to the vulnerable package for a specific finding.

    Args:
        repo_id: Repository UUID identifier.
        finding_id: 12-character hex finding identifier.
    """
    ctx = ToolContext(repo_id=repo_id, user_role="viewer")
    return REGISTRY["trace_path"](ctx, finding_id=finding_id)


@mcp.tool()
def score_finding(repo_id: str, finding_id: str) -> dict[str, Any]:
    """Compute and return deterministic 0-100 risk score breakdown for a specific finding.

    Args:
        repo_id: Repository UUID identifier.
        finding_id: 12-character hex finding identifier.
    """
    ctx = ToolContext(repo_id=repo_id, user_role="viewer")
    return REGISTRY["score_finding"](ctx, finding_id=finding_id)


@mcp.tool()
def choke_points(repo_id: str) -> dict[str, Any]:
    """Identify bottleneck packages whose upgrade or removal clears the most reachable findings.

    Args:
        repo_id: Repository UUID identifier.
    """
    ctx = ToolContext(repo_id=repo_id, user_role="viewer")
    return REGISTRY["choke_points"](ctx)


@mcp.tool()
def simulate(
    repo_id: str,
    changes: list[dict[str, Any]],
    finding_id: str | None = None,
) -> dict[str, Any]:
    """Simulate architectural changes (add_auth, remove_import) on a temporary in-memory graph copy.

    Never modifies the persistent repository database.

    Args:
        repo_id: Repository UUID identifier.
        changes: List of change dictionaries to simulate.
        finding_id: Optional 12-character hex finding identifier to evaluate.
    """
    ctx = ToolContext(repo_id=repo_id, user_role="analyst")
    return REGISTRY["simulate"](ctx, changes=changes, finding_id=finding_id)


@mcp.tool()
def recall(repo_id: str, finding_id: str | None = None) -> dict[str, Any]:
    """Recall past investigations, analyst notes, and human risk decisions from repository memory.

    Args:
        repo_id: Repository UUID identifier.
        finding_id: Optional 12-character hex finding identifier.
    """
    ctx = ToolContext(repo_id=repo_id, user_role="viewer")
    return REGISTRY["recall"](ctx, finding_id=finding_id)


@mcp.tool()
def save_investigation(
    repo_id: str,
    finding_id: str = "",
    summary: str = "",
) -> dict[str, Any]:
    """Save an investigation note into repository memory.

    Disabled on read-only MCP transport; save_investigation stays REST-only in ReachGuard.

    Args:
        repo_id: Repository UUID identifier.
        finding_id: 12-character hex finding identifier.
        summary: Summary note for the investigation.
    """
    return {
        "ok": False,
        "error": "save_investigation is disabled on MCP (read-only transport; save_investigation stays REST-only).",
    }


@mcp.tool()
def critical_modules(repo_id: str) -> dict[str, Any]:
    """Identify the top 10 central or critical modules in the codebase, scores (0-100), algorithm notes, and owners.

    Args:
        repo_id: Repository UUID identifier.
    """
    ctx = ToolContext(repo_id=repo_id, user_role="viewer")
    return REGISTRY["critical_modules"](ctx)


@mcp.tool()
def vulnerability_clusters(repo_id: str) -> dict[str, Any]:
    """Group findings into clusters based on shared module entrypoints and code paths to plan remediation batches.

    Args:
        repo_id: Repository UUID identifier.
    """
    ctx = ToolContext(repo_id=repo_id, user_role="viewer")
    return REGISTRY["vulnerability_clusters"](ctx)


# ── Authentication Middleware ───────────────────────────────────


class MCPAuthMiddleware(BaseHTTPMiddleware):
    """Authenticate incoming HTTP requests with MCP_API_KEY when running in production."""

    async def dispatch(self, request: Request, call_next: Any) -> Response:
        app_env = os.getenv("APP_ENV", "dev").lower()
        api_key = os.getenv("MCP_API_KEY")

        # In dev mode without explicit API key configured: allow all
        if app_env == "dev" and not api_key:
            return await call_next(request)

        # In production (or if MCP_API_KEY is configured): validate key
        if api_key:
            provided_key = (
                request.headers.get("mcp-api-key")
                or request.headers.get("x-api-key")
            )
            auth_header = request.headers.get("authorization", "")
            if not provided_key and auth_header.lower().startswith("bearer "):
                provided_key = auth_header[7:].strip()

            if not provided_key or provided_key != api_key:
                return Response(
                    content='{"jsonrpc":"2.0","error":{"code":-32001,"message":"Unauthorized: Invalid or missing MCP_API_KEY"}}\n',
                    status_code=401,
                    media_type="application/json",
                )

        return await call_next(request)


# ── Application Factory & CLI Runner ────────────────────────────


def create_app() -> Any:
    """Create ASGI application for streamable HTTP transport with authentication middleware."""
    return mcp.http_app(middleware=[Middleware(MCPAuthMiddleware)], transport="streamable-http")


def run_stdio() -> None:
    """Run FastMCP server over standard input/output."""
    mcp.run(transport="stdio")


def run_http(host: str = "0.0.0.0", port: int = 8765) -> None:
    """Run FastMCP server over streamable HTTP on specified host and port."""
    import uvicorn

    app = create_app()
    uvicorn.run(app, host=host, port=port)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="ReachGuard MCP Server")
    parser.add_argument(
        "--transport",
        default="streamable-http",
        choices=["stdio", "streamable-http", "http", "sse"],
        help="Transport protocol (default: streamable-http)",
    )
    parser.add_argument(
        "--host",
        default="0.0.0.0",
        help="HTTP host (default: 0.0.0.0)",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=8765,
        help="HTTP port (default: 8765)",
    )
    args = parser.parse_args()

    if args.transport == "stdio":
        run_stdio()
    else:
        run_http(host=args.host, port=args.port)
