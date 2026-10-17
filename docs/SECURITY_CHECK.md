# ReachGuard Security Verification & Production-Readiness (D4 Checklist)

Evidence and verification details for ReachGuard's production security controls per the D4 non-negotiable checklist.

---

## 1. Rate Limiting (SlowAPI)
- **Login Rate Limit**: `5/minute` per IP on `/api/auth/login`.
- **Chat Agent Rate Limit**: `20/minute` per IP on `/api/repos/{repo_id}/agent/chat`.
- **Implementation**: [backend/app/auth/router.py](file:///Users/patelkrina/Desktop/my-app/reachguard/backend/app/auth/router.py) and [backend/app/agent/router.py](file:///Users/patelkrina/Desktop/my-app/reachguard/backend/app/agent/router.py).
- **Verified**: Returns standard error envelope with `429 Too Many Requests` when limits are exceeded.

## 2. Authentication & Per-Request User Load
- **Bcrypt Password Hashing**: Passwords hashed with salt factor 12 using `bcrypt`. Plaintext passwords never stored.
- **JWT with Active Verification**: HS256 tokens signed with `JWT_SECRET`.
- **Per-Request Fresh Load**: [backend/app/deps.py](file:///Users/patelkrina/Desktop/my-app/reachguard/backend/app/deps.py) loads the live user node from `rg_meta` on every authenticated request:
  ```python
  MATCH (u:User {id: $uid}) RETURN u
  ```
  If an admin deactivates or changes the user's role, the next request is immediately blocked (returns 401).

## 3. Strict Parameterized Cypher Queries (Zero Injection)
- **Parameterized Queries**: 100% of Cypher queries in [backend/app/graph/queries.py](file:///Users/patelkrina/Desktop/my-app/reachguard/backend/app/graph/queries.py) use FalkorDB `$params` mapping for user-supplied data (package names, finding IDs, usernames, timestamps).
- **No Cypher Interpolation**: String formatting is prohibited for query clauses; graph names and procedure identifiers are whitelist-validated using regex `^[a-zA-Z0-9_-]+$`.

## 4. Git Clone URL Validation
- **Protocol Restriction**: Only `https://` URLs allowed. `ssh://`, `git://`, `file://`, and local relative paths are strictly rejected.
- **SSRF Mitigation**: Hostnames resolving to private RFC 1918 ranges (`10.0.0.0/8`, `172.16.0.0/12`, `192.168.0.0/16`), loopback (`127.0.0.0/8`), or AWS metadata IP (`169.254.169.254`) are blocked before cloning.
- **Implementation**: [backend/app/ingest/fetch.py](file:///Users/patelkrina/Desktop/my-app/reachguard/backend/app/ingest/fetch.py) `validate_clone_url()`.

## 5. Zip-Slip & Archive Bomb Protection
- **Zip-Slip Path Traversal Protection**: Archive members validated with `(dest / member).resolve().relative_to(dest)`. Any archive entry attempting directory traversal (`../`) raises `ZipValidationError`.
- **Uncompressed Size Quota**: Streamed byte counting enforces `MAX_ZIP_MB` (default 50 MB) and `MAX_REPO_MB` (default 100 MB). Over-quota extractions abort immediately.
- **Max File Limit**: Maximum 5,000 `.py` files per repo prevents disk exhaustion bombs.

## 6. Static Analysis Isolation (No Code Execution)
- **Zero Execution of Analyzed Code**: ReachGuard parses Python source code using standard library `ast.parse()`.
- Modules, classes, functions, and import statements are extracted purely from the Abstract Syntax Tree.
- Analyzed code is **never imported, executed, eval'd, or compiled**.

## 7. FalkorDB Network & Password Isolation
- **Multi-Graph Isolation**: Every repository receives an isolated graph namespace: `rg_repo_<uuid>`.
- Cross-tenant or cross-repo data leaks are architecturally impossible at the graph engine level.
- **Production Mode**: FalkorDB runs with mandatory password auth (`FALKORDB_PASSWORD`), bound to internal Docker bridge network without exposing port 6379 to the host.

## 8. Reverse Proxy HTTPS (Caddy) & SPA Fallback
- **Caddy / Nginx Reverse Proxy**: Automatic TLS certificate termination, gzip compression, security headers (`X-Frame-Options: DENY`, `X-Content-Type-Options: nosniff`, `Content-Security-Policy`).
- SPA routing fallback handled via `try_files $uri $uri/ /index.html`.

## 9. Secret Management
- `.env` is ignored in `.gitignore` and never committed to source control.
- An annotated `.env.example` is provided with secure defaults.
- Enforced in CI via `bash scripts/no_demo_data.sh`.
