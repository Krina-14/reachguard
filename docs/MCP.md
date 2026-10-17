# ReachGuard — Model Context Protocol (MCP) Server

ReachGuard exposes its full reachability graph analysis, deterministic risk scoring, and graph algorithms to external AI assistants (such as Claude Desktop, Cursor, or custom MCP clients) via the **Model Context Protocol (MCP)**.

This enables foreign agents to directly query ReachGuard's live FalkorDB knowledge graph and answer reachability questions without re-parsing source code or re-evaluating dependency graphs.

---

## 1. Exposed MCP Tools

All MCP tools are **read-only** and delegate directly to ReachGuard's central tool registry (`app.agent.tools.REGISTRY`):

| Tool Name | Parameters | Description |
|---|---|---|
| `list_findings` | `repo_id: str` | List the top 25 vulnerability findings in the repository with scores, verdicts, and packages. |
| `trace_path` | `repo_id: str, finding_id: str` | Trace reachable execution paths from public entrypoints to the vulnerable package for a finding. |
| `score_finding` | `repo_id: str, finding_id: str` | Compute and return deterministic 0–100 risk score breakdown (reach, severity, exposure factor). |
| `choke_points` | `repo_id: str` | Identify bottleneck packages whose upgrade/removal clears the most reachable findings. |
| `simulate` | `repo_id: str, changes: list, finding_id: str?` | Simulate architectural changes on a temporary in-memory graph copy. |
| `recall` | `repo_id: str, finding_id: str?` | Recall past triage investigations, analyst notes, and human risk decisions from memory. |
| `save_investigation` | `repo_id: str, finding_id: str, summary: str` | Preserved for schema completeness; disabled over read-only MCP (stays REST-only). |
| `critical_modules` | `repo_id: str` | Identify top 10 central modules in the codebase, scores (0–100), algorithm notes, and owners. |
| `vulnerability_clusters` | `repo_id: str` | Group findings into clusters sharing entrypoint ancestors to plan unified remediation batches. |

---

## 2. Quick Start: Running the MCP Server

### Streamable HTTP (Port 8765 — Development Default)
Run the server over streamable HTTP:
```bash
cd backend
PYTHONPATH=. ./.venv/bin/python -m app.mcp_server --transport streamable-http --port 8765
```
The server will listen at `http://localhost:8765/mcp`.

### Stdio Mode (Command-Line Pipe)
Run the server directly via standard input/output for local desktop clients:
```bash
cd backend
PYTHONPATH=. ./.venv/bin/python -m app.mcp_server --transport stdio
```

---

## 3. Client Configuration

### Claude Desktop Configuration (`claude_desktop_config.json`)

To connect Claude Desktop to ReachGuard via the streamable HTTP endpoint:

**macOS**: `~/Library/Application Support/Claude/claude_desktop_config.json`  
**Windows**: `%APPDATA%\Claude\claude_desktop_config.json`

```json
{
  "mcpServers": {
    "reachguard": {
      "url": "http://localhost:8765/mcp"
    }
  }
}
```

*Alternatively, to connect Claude Desktop via stdio:*
```json
{
  "mcpServers": {
    "reachguard": {
      "command": "/Users/patelkrina/Desktop/my-app/reachguard/backend/.venv/bin/python",
      "args": ["-m", "app.mcp_server", "--transport", "stdio"],
      "env": {
        "PYTHONPATH": "/Users/patelkrina/Desktop/my-app/reachguard/backend",
        "APP_ENV": "dev"
      }
    }
  }
}
```

---

### Cursor Configuration (`.cursor/mcp.json` or Settings > MCP)

Add ReachGuard under your Cursor workspace MCP settings:

```json
{
  "mcpServers": {
    "reachguard": {
      "url": "http://localhost:8765/mcp"
    }
  }
}
```

---

## 4. Authentication

- **Development (`APP_ENV=dev`)**: No authentication header is required.
- **Production (`APP_ENV=prod`)**: Provide the static API key via the `mcp-api-key` header (configured via the `MCP_API_KEY` environment variable):

```json
{
  "mcpServers": {
    "reachguard": {
      "url": "https://reachguard.internal:8765/mcp",
      "headers": {
        "mcp-api-key": "your-static-production-mcp-key"
      }
    }
  }
}
```

---

## 5. Live Demonstration: Cross-Agent Graph Querying

Ask the external AI assistant (Claude Desktop or Cursor):
> *"Is finding `8bc5f7a0c3f7` in repository `7e443543-ba34-4e04-abf9-10f8daf929d1` reachable?"*

Watch the foreign agent query ReachGuard's live FalkorDB graph through `trace_path`, citing the exact public entrypoints, reaching call chain, and deterministic score breakdown matching ReachGuard's native UI!
