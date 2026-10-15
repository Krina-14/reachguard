# ReachGuard: Shared Contract (single source of truth)

All four members code against this file. Copy it to `docs/01_SHARED_CONTRACT.md` in the repo at G0.

## 1. Repo layout and ownership

```
reachguard/
  docs/                       (M4)  these playbook files
  docker-compose.yml          (M4)
  .env.example                (M4)
  scripts/                    (M4)  e2e.py, no_demo_data.sh
  .github/workflows/ci.yml    (M4)
  backend/
    Dockerfile                (M4)
    requirements.txt          (M4 creates, everyone appends via PR)
    app/
      main.py, config.py, deps.py            (M2)
      auth/                                  (M2)  security.py, service.py, router.py
      graph/                                 (M2)  client.py, schema.py, queries.py
      ingest/                                (M2)  fetch.py, parse_python.py, lockfiles.py,
                                                   importmap.py, osv.py, owners.py, builder.py, router.py
      api/                                   (M2)  repos.py, findings.py, memory.py, whatif.py, admin.py
      scoring.py                             (M3)
      agent/                                 (M3)  llm.py, tools.py, loop.py, planner.py,
                                                   guardrails.py, fallback.py, router.py
    tests/                                   (each owner adds tests for their own files)
  frontend/                                  (M1)  everything
    Dockerfile + nginx.conf                  (M1 writes, M4 reviews)
```

## 2. Environment variables (`.env.example`; real `.env` never committed)

| Var | Meaning | Default / example |
|---|---|---|
| `APP_ENV` | `dev` or `prod` | `dev` |
| `FALKORDB_HOST` / `FALKORDB_PORT` | graph DB | `localhost` / `6379` |
| `FALKORDB_PASSWORD` | graph DB password (required in prod) | empty in dev |
| `JWT_SECRET` | random 64+ chars (required in prod, app refuses to start with a default in prod) | none |
| `JWT_EXPIRE_MINUTES` | token life | `60` |
| `ADMIN_EMAIL` / `ADMIN_PASSWORD` | creates first admin **only if no users exist** | none |
| `CORS_ORIGINS` | comma list | `http://localhost:5173` |
| `WORK_DIR` | temp folder for clones | `/tmp/reachguard` |
| `MAX_REPO_MB` / `MAX_ZIP_MB` / `MAX_PY_FILES` | ingestion limits | `100` / `50` / `5000` |
| `OSV_BASE_URL` | vulnerability DB | `https://api.osv.dev` |
| `OSV_CACHE_DIR` | cache of **real** OSV responses | `/data/osv_cache` |
| `LLM_PROVIDER` | `ollama`, `openai_compat`, `none` | `ollama` |
| `LLM_BASE_URL` | OpenAI-compatible base URL | `http://localhost:11434/v1` |
| `LLM_MODEL` | model name | `qwen2.5:7b-instruct` (use `qwen2.5:3b-instruct` on low RAM) |
| `LLM_API_KEY` | only for hosted free tiers | empty |
| `LLM_TIMEOUT_S` | request timeout | `60` |

## 3. Roles and permissions

| Action | viewer | analyst | admin |
|---|---|---|---|
| Login, `me`, health | yes | yes | yes |
| List/read repos, findings, graph, memory | yes | yes | yes |
| Chat with the agent (answers shown, **nothing saved**) | yes | yes | yes |
| Chat with saving (`save=true` creates an Investigation) | no | yes | yes |
| Add repo (URL or zip), what-if, create decision | no | yes | yes |
| Approve/reject a decision, delete repo, manage users | no | no | yes |

Decision rule: a decision of type `accept_risk` is created as `pending` and only counts after an **admin approves** it. Other types (`fix_planned`, `false_positive`, `fixed`) are `approved` immediately. This is the "human approval" the brief asks for.

## 4. Graph model (FalkorDB, Cypher)

Graphs (one FalkorDB instance, many graphs):

- **`rg_meta`**: users, repo registry, audit events.
  - `(:User {id, email, password_hash, role, active, created_at})`
  - `(:Repo {id, source, source_type:'git'|'zip', status, stage_detail, error, created_at, created_by, stats_json})`
  - `(:AuditEvent {id, at, actor, action, target})`
- **`rg_repo_<repo_id>`**: one graph per analyzed repository (isolated tenants, which showcases FalkorDB multigraph).
- **`rg_sim_<uuid>`**: temporary copies for what-if. Always deleted in a `finally`; leftovers deleted at startup.

Repo graph nodes and edges:

```
(:Entrypoint {id, method, path, file, line, framework, public:bool, auth_hint:str})
(:Module     {id /*dotted name*/, file, lines})
(:Package    {id /*name@version*/, name, version, direct:bool, ecosystem:'PyPI'})
(:Vulnerability {id /*OSV id*/, aliases:[str], summary, severity /*CRITICAL|HIGH|MODERATE|LOW|UNKNOWN*/,
                 fixed_versions:[str], published})
(:BlindSpot  {id, kind /*dynamic_import|unresolved_import|unparsed_file*/, reason, file, line, name})
(:Owner      {id, name, kind /*codeowners|author*/})
(:Finding    {id, status /*open|risk_accepted|fixed|false_positive|fix_planned*/, first_seen})
(:Investigation {id, created_at, by, verdict, score, path_json, summary, session_id})
(:Decision   {id, type, reason, by, status /*pending|approved|rejected*/, approved_by, created_at, expires_at})

(Entrypoint)-[:HANDLED_BY]->(Module)
(Module)-[:IMPORTS]->(Module)
(Module)-[:USES]->(Package)                  // module imports a third-party package
(Package)-[:DEPENDS_ON]->(Package)           // from the lockfile
(Vulnerability)-[:AFFECTS]->(Package)
(Finding)-[:ABOUT]->(Vulnerability)
(Finding)-[:ON_PACKAGE]->(Package)
(Module)-[:HAS_BLINDSPOT]->(BlindSpot)
(Module)-[:OWNED_BY]->(Owner)
(Finding)-[:HAD_INVESTIGATION]->(Investigation)
(Finding)-[:HAS_DECISION]->(Decision)
```

Reachability traversal always uses: `[:HANDLED_BY|IMPORTS|USES|DEPENDS_ON*1..20]` from `Entrypoint {public:true}` to the finding's `Package`.
Finding id = `sha1(vuln_id + "|" + package_id)[:12]`. Entrypoint id = `sha1(method|path|file)[:12]`.

## 5. Verdicts (never say "safe")

| Verdict string (API) | UI label | Rule |
|---|---|---|
| `reachable_in_model` | Reachable in model | at least one path from a **public** entrypoint to the package |
| `unknown` | Unknown | no path, but a `dynamic_import` or `unparsed_file` blind spot exists in a module reachable from a public entrypoint, or an `unresolved_import` there whose normalized name matches the package name |
| `no_path_found` | No path found in model | none of the above. UI must show the search scope and the sentence "This is not proof of safety." |

If a package is only in the lockfile and never imported, verdict is `no_path_found` with reason `declared_not_imported`.

## 6. Score (deterministic, M3 owns `scoring.py`)

```
reach     = 1.0 (reachable_in_model) | 0.5 (unknown) | 0.15 (no_path_found)
severity  = 1.0 CRITICAL | 0.75 HIGH | 0.5 MODERATE | 0.25 LOW | 0.4 UNKNOWN
exposure  = reaching_public_entrypoints / total_public_entrypoints   (0 if no public entrypoints)
score     = round(100 * (0.5*reach + 0.3*severity + 0.2*exposure))
status modifier: risk_accepted (approved, not expired) -> shown with score unchanged but sorted to the bottom and labeled
```
The API returns the breakdown `{reach, severity, exposure, weights, score}`. The UI shows the formula.

## 7. API (all under `/api`, JSON, `Authorization: Bearer <jwt>` unless public)

Errors always: `{"error": {"code": "string", "message": "string"}}` with proper HTTP status (400, 401, 403, 404, 409, 422, 429, 500).

### Public
- `GET /api/health` -> `{status:"ok", falkordb:true|false, llm:{provider, model, reachable:true|false, mode:"llm"|"deterministic"}, version}`
- `POST /api/auth/login` `{email, password}` -> `{access_token, token_type:"bearer", user:{id,email,role}}` (rate limited: 5/min per IP)

### Auth
- `GET /api/auth/me` -> `{id,email,role}`
- `POST /api/auth/change-password` `{old_password,new_password}` (min 10 chars)

### Admin (admin only)
- `GET /api/admin/users`, `POST /api/admin/users` `{email,password,role}`, `PATCH /api/admin/users/{id}` `{role?,active?,password?}`
- Cannot demote or deactivate the last active admin (409).

### Repos
- `POST /api/repos` `{git_url}` (analyst+) -> `202 {repo_id, status:"queued"}`. Only `https://github.com/<owner>/<repo>` (optionally `.git`) is accepted in MVP.
- `POST /api/repos/upload` multipart `file=<zip>` (analyst+) -> `202 {repo_id,status}`
- `GET /api/repos` -> `[{id, source, status, created_at, stats}]`
- `GET /api/repos/{id}` -> `{id, source, status, stage_detail, error, created_at, stats:{files_parsed, files_failed, modules, entrypoints, public_entrypoints, packages, direct_packages, findings, blind_spots, lockfile_kind, transitive_available}}`
  - `status`: `queued|cloning|parsing|scanning|ready|failed`
- `DELETE /api/repos/{id}` (admin) -> 204 (drops its graph)

### Findings and graph
- `GET /api/repos/{id}/findings?verdict=&status=&q=` -> `[{id, vuln_id, aliases, summary, severity, package, version, fixed_versions, verdict, score, status, owners:[str]}]` sorted by score desc, risk-accepted last
- `GET /api/repos/{id}/findings/{fid}` -> finding row plus `{trace, score_breakdown, investigations:[...], decisions:[...]}`
  - `trace` = TraceResult (Section 8)
- `GET /api/repos/{id}/graph?finding_id=` -> `{nodes:[{id,label,name,props}], edges:[{id,source,target,type}], highlight:{nodes:[id], edges:[id]}}`. Without `finding_id`: summary graph (public entrypoints, their modules, packages, capped at 300 nodes with `truncated:true`).
- `GET /api/repos/{id}/choke-points` -> `[{package, version, clears_findings:int, finding_ids:[...]}]` (packages whose upgrade or removal clears the most **reachable** findings)

### What-if (analyst+; runs on a temporary graph copy, never changes real data)
- `POST /api/repos/{id}/whatif` `{finding_id?, changes:[{type:"add_auth", entrypoint_id} | {type:"remove_import", module_id, package_id}]}` -> `{before, after, changed:[{finding_id, from, to}]}` where before/after are TraceResult (if `finding_id` given) or per-finding verdict maps.

### Decisions and memory
- `POST /api/repos/{id}/findings/{fid}/decisions` `{type:"accept_risk"|"fix_planned"|"false_positive"|"fixed", reason (min 10 chars), expires_at?}` (analyst+)
- `POST /api/repos/{id}/decisions/{did}/approve` / `.../reject` (admin)
- `GET /api/repos/{id}/memory?finding_id=` -> `{investigations:[...], decisions:[...]}` (without finding_id: latest 50)

### Agent
- `POST /api/repos/{id}/agent/chat` `{session_id?, message, save?:false}` ->
  `{session_id, answer, mode:"llm_tools"|"llm_explain"|"deterministic", tool_calls:[{name,args,ok,summary}], evidence:{findings:[row], traces:[TraceResult], memory:[...]}, grounded:true|false, warnings:[str]}`
  - `evidence` is what the UI uses to draw paths. The UI never parses the answer text for paths.

## 8. TraceResult (returned by `queries.trace_paths`, used by everyone)

```json
{
  "finding_id": "a1b2c3d4e5f6",
  "verdict": "reachable_in_model | unknown | no_path_found",
  "reason": "string, e.g. 'declared_not_imported' or 'dynamic_import in app.plugins'",
  "paths": [
    {"entrypoint_id": "...", "entrypoint": "POST /login",
     "nodes": [{"id":"...","label":"Entrypoint|Module|Package","name":"..."}],
     "edges": [{"id":"...","type":"HANDLED_BY|IMPORTS|USES|DEPENDS_ON"}]}
  ],
  "reaching_entrypoints": 2,
  "total_public_entrypoints": 7,
  "blind_spots": [{"kind":"dynamic_import","file":"app/plugins.py","line":12,"reason":"..."}],
  "searched_scope": {"modules": 41, "files_parsed": 40, "files_failed": 1, "max_depth": 20,
                     "lockfile_kind": "requirements.txt|poetry.lock|none", "transitive_available": false}
}
```

## 9. `app.graph.queries` function signatures (M2 implements, M3 and API call)

```python
def list_findings(repo_id: str) -> list[dict]
def get_finding(repo_id: str, finding_id: str) -> dict | None
def trace_paths(repo_id: str, finding_id: str, max_paths: int = 3, graph_name: str | None = None) -> dict  # TraceResult
def entrypoint_stats(repo_id: str, graph_name: str | None = None) -> dict   # {total_public, ...}
def choke_points(repo_id: str) -> list[dict]
def subgraph(repo_id: str, finding_id: str | None) -> dict
def simulate(repo_id: str, finding_id: str | None, changes: list[dict]) -> dict
def recall(repo_id: str, finding_id: str | None) -> dict   # {investigations, decisions}
def save_investigation(repo_id: str, finding_id: str, by: str, verdict: str, score: int, path_json: str, summary: str, session_id: str) -> str
def create_decision(repo_id: str, finding_id: str, by: str, type: str, reason: str, expires_at: str | None) -> dict
def set_decision_status(repo_id: str, decision_id: str, status: str, by: str) -> dict
```
Rules: every query is **parameterized** (`graph.query(cypher, params)`); never build Cypher with f-strings from user input. Graph names are built only from validated UUIDs.

## 10. Agent tools (M3, JSON schema names must match)

`list_findings()`, `trace_path(finding_id)`, `score_finding(finding_id)`, `choke_points()`, `simulate(finding_id, changes)`, `recall(finding_id)`, `save_investigation(finding_id, summary)`.
The LLM can never write to the graph except through `save_investigation`, and only if the request has `save=true` and the user is analyst+.

## 11. Definition of done for "real data"

- A fresh database has: 1 admin user, 0 repos, 0 findings.
- Every number on screen comes from an API call. Empty lists render an empty state with a call to action.
- `grep -rniE "mock|dummy|lorem|fake|demo_data|sample_data|hardcoded" backend/app frontend/src` returns nothing (CI enforces).
- The OSV cache stores real OSV responses only. It is a cache, not seed data.

## 12. Scope tiers

| Tier | Items |
|---|---|
| **Must** | login + roles, add real repo, parse, graph in FalkorDB, OSV findings, verdicts with proof path, score, graph view, agent chat with evidence, investigation memory + decisions, deterministic fallback |
| **Should** | what-if (graph copy), choke points, owners (CODEOWNERS / git authors), admin users page, approval flow |
| **Optional** | zip upload, MCP server exposing the tools, cross-repo memory |
| **Avoid** | other languages, function-level analysis, auto-applied fixes, SSO, billing |
