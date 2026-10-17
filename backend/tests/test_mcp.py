"""
Integration tests for ReachGuard FastMCP Server.

Tests:
1. Starts the FastMCP server in a background thread.
2. Connects over the HTTP streamable transport using fastmcp.Client.
3. Asserts all 9 tools are exposed.
4. Calls a tool (critical_modules, list_findings) over HTTP against the real repository graph in FalkorDB.
5. Verifies read-only enforcement on save_investigation.
6. Verifies production MCP_API_KEY authentication enforcement.
"""

from __future__ import annotations

import asyncio
import json
import os
import socket
import threading
import time
from typing import Any

import pytest
import uvicorn
from fastmcp import Client

from app.graph.client import meta_graph, run
from app.mcp_server import create_app


def _find_free_port() -> int:
    """Find a random available port on localhost."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture(scope="module")
def ready_repo_id() -> str:
    """Find or provide an active ready repo_id from FalkorDB."""
    try:
        g = meta_graph()
        rows = run(g, "MATCH (r:Repo) WHERE r.status = 'ready' RETURN r.id as id LIMIT 1")
        if rows:
            return rows[0]["id"]
    except Exception:
        pass
    return "7e443543-ba34-4e04-abf9-10f8daf929d1"


@pytest.fixture(scope="module")
def mcp_server_url() -> str:
    """Launch the ReachGuard FastMCP server in a daemon thread on a free port."""
    port = _find_free_port()
    app = create_app()
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="error"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()

    # Wait for server to accept connections
    for _ in range(50):
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.1):
                break
        except OSError:
            time.sleep(0.05)

    return f"http://127.0.0.1:{port}/mcp"


@pytest.mark.asyncio
async def test_mcp_server_tools_list_and_real_repo_call(mcp_server_url: str, ready_repo_id: str) -> None:
    """Connect over HTTP, list 9 tools, and execute critical_modules on the real repo graph."""
    async with Client(mcp_server_url) as client:
        tools = await client.list_tools()
        tool_names = {t.name for t in tools}

        expected_tools = {
            "list_findings",
            "trace_path",
            "score_finding",
            "choke_points",
            "simulate",
            "recall",
            "save_investigation",
            "critical_modules",
            "vulnerability_clusters",
        }
        assert expected_tools.issubset(tool_names)
        assert len(tools) == 9

        # Call critical_modules on real repository graph
        res = await client.call_tool("critical_modules", {"repo_id": ready_repo_id})
        assert not res.is_error
        assert len(res.content) > 0

        parsed = json.loads(res.content[0].text)
        assert parsed.get("ok") is True
        assert "modules" in parsed
        assert isinstance(parsed["modules"], list)

        # Call list_findings on real repository graph
        f_res = await client.call_tool("list_findings", {"repo_id": ready_repo_id})
        assert not f_res.is_error
        f_parsed = json.loads(f_res.content[0].text)
        assert f_parsed.get("ok") is True
        assert "findings" in f_parsed

        # Call save_investigation to verify read-only contract
        save_res = await client.call_tool(
            "save_investigation",
            {"repo_id": ready_repo_id, "finding_id": "a1b2c3d4e5f6", "summary": "test note"},
        )
        save_parsed = json.loads(save_res.content[0].text)
        assert save_parsed.get("ok") is False
        assert "disabled on MCP" in save_parsed.get("error", "")


@pytest.mark.asyncio
async def test_mcp_auth_in_production(ready_repo_id: str, monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify that in production mode, requests without valid MCP_API_KEY are rejected with 401."""
    import httpx

    test_key = "test-prod-key-998877"
    monkeypatch.setenv("APP_ENV", "prod")
    monkeypatch.setenv("MCP_API_KEY", test_key)

    port = _find_free_port()
    app = create_app()
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="error"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()

    time.sleep(0.5)
    endpoint = f"http://127.0.0.1:{port}/mcp"

    async with httpx.AsyncClient() as http_client:
        # 1. Request without key -> 401 Unauthorized
        resp_unauth = await http_client.post(
            endpoint,
            headers={"Content-Type": "application/json"},
            json={"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
        )
        assert resp_unauth.status_code == 401
        assert "Unauthorized" in resp_unauth.text

        # 2. Request with invalid key -> 401 Unauthorized
        resp_bad = await http_client.post(
            endpoint,
            headers={"Content-Type": "application/json", "mcp-api-key": "wrong-key"},
            json={"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
        )
        assert resp_bad.status_code == 401

        # 3. Request with valid key -> Accepted
        resp_ok = await http_client.post(
            endpoint,
            headers={"Content-Type": "application/json", "mcp-api-key": test_key},
            json={"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
        )
        assert resp_ok.status_code in (200, 202)
