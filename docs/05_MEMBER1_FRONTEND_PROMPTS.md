# Member-1: Frontend (React + TypeScript + Tailwind + Cytoscape.js)

You own everything in `frontend/`. The UI talks **only** to the real backend through `/api/...` as defined in the contract. There is **no demo data anywhere**: every list starts empty, shows an empty state, and fills only from API calls.

**What you can do before the backend exists:** scaffold, routing, layout, components, forms, empty states, loading and error states. You can read the live API reference at `http://localhost:8000/docs` once Member-2 publishes G1.
**Wait for:** G0 to start (so the repo exists). G1 before wiring login. G2 before the findings screens show data. G3 before wiring chat.

Every prompt starts with: `First read docs/01_SHARED_CONTRACT.md. Follow it exactly. No mock, dummy, fake or demo data in frontend/src. Show empty states instead.`

**Setup after G0:** `git pull`, `git checkout -b m1-frontend`.

---

## F1. Scaffold (45 min, no dependencies)

```
Create the frontend in frontend/ with Vite, React 18, TypeScript (strict), Tailwind CSS, react-router-dom, @tanstack/react-query, cytoscape and its types, and clsx. Use npm.
- Vite dev server on port 5173 with a proxy: /api -> http://localhost:8000 (so no CORS in dev).
- Folder layout: src/api (client + types), src/auth (context, guards), src/components, src/pages, src/lib, src/styles.
- Tailwind configured with a restrained design system: a dark neutral background, one accent color, verdict colors that are distinct AND have different icons/labels (not color alone): Reachable in model = red with a "path" icon, Unknown = amber with a "?" icon, No path found in model = slate with a "dash" icon. Document colors in tailwind.config.
- src/api/types.ts: TypeScript types for every response shape in contract Sections 7 and 8 (User, Repo, RepoStats, FindingRow, FindingDetail, TraceResult, ScoreBreakdown, GraphResponse, Decision, Investigation, ChatResponse, WhatIfResponse).
- src/api/client.ts: a fetch wrapper that adds the Bearer token from memory state (NOT localStorage if avoidable; if you persist, use sessionStorage), parses the standard error shape {"error":{code,message}} into a typed ApiError, on 401 clears the session and redirects to /login, and never logs tokens.
- Routes (placeholders for now): /login, /, /repos/:repoId, /repos/:repoId/findings/:findingId, /admin/users, *.
- Add npm scripts: dev, build, lint (eslint), typecheck (tsc --noEmit).
Do not add any content data. Keep placeholder pages to a title only.
```

**Manual steps:** `cd frontend && npm install && npm run dev`, open `http://localhost:5173`.
**Verify F1:** the app loads at each route without console errors; `npm run typecheck` and `npm run build` pass.

## F2. Auth screens and role guards (after G1)

```
Implement login and role handling.
- src/auth/AuthContext.tsx: holds user {id,email,role} and token; login(email,password) calls POST /api/auth/login; logout; on page refresh restore from sessionStorage and call GET /api/auth/me to validate (clear if 401).
- src/auth/guards.tsx: <RequireAuth> redirects to /login; <RequireRole roles={[...]}> shows a friendly 403 page. A hook useCan() returns booleans: canAddRepo, canSave, canApprove, canManageUsers computed ONLY from role per the contract Section 3 table.
- /login page: email + password form, loading state, shows the API's error message (generic "Invalid email or password"), 429 shows "Too many attempts, wait a minute". Accessible labels, Enter submits, focus on the first field.
- Header: product name, repo switcher placeholder, user email + role badge, logout, backend health badge that polls GET /api/health every 30 seconds showing three states: Graph DB up/down and AI mode ("LLM: <model>" or "Deterministic mode").
Hide buttons the role cannot use (do not just disable); the backend still enforces permissions.
```

**Verify F2:** log in as the admin created by Member-2 (ask for the credentials in the private chat, never in git). Check: wrong password shows the error; refresh keeps you logged in; logout clears; opening `/admin/users` as a viewer shows the 403 page. The header badge shows "Graph DB up" with Docker running and "down" when you stop the falkordb container.

## F3. Repos page (after G1; data after G2)

```
Implement the home page "/" (repo list) and add-repo flow.
- List repos from GET /api/repos with status chips (queued, cloning, parsing, scanning, ready, failed). Poll every 3 seconds while any repo is not ready or failed (React Query refetchInterval). Show the stage name, created time, and key stats once ready (modules, entrypoints, packages, findings).
- Empty state when there are no repos: explanation of what ReachGuard does and a prominent "Analyze a repository" call to action (only for roles that can add repos; viewers see "Ask an analyst to add a repository").
- Add-repo dialog for analysts/admins: tab 1 "GitHub URL" (validate client side with https://github.com/owner/repo, show the rule), tab 2 "Upload zip" (max 50 MB message, drag and drop). Show server validation errors inline. After submit, go to the repo page.
- Failed repos show the error message from the API and a "Delete" (admin only) button with a confirm dialog.
- Repo page /repos/:repoId: while status is not ready, a progress view with the stages as a stepper. When ready, a summary strip of stats including the honest scope line: "Python only. Analysis scope: <files_parsed> files parsed, <files_failed> failed. Dependencies from <lockfile_kind>. Transitive dependencies: <available | not available (no lockfile)>."
```

**Verify F3:** add `https://github.com/fportantier/vulpy`. Watch the stepper move. The stats appear. Add `http://example.com/x`: the form rejects it. Log in as a viewer: no add button.

## F4. Findings dashboard (after G2)

```
On the repo page add the findings dashboard from GET /api/repos/{id}/findings.
- Table columns: Score (with a small bar), Verdict badge (icon + label), Severity, Package@version, Vulnerability id (link to https://osv.dev/vulnerability/<id>), Owner(s), Status chip. Row click opens the finding detail page.
- Filters: verdict (3 values + all), status, text search q. Sort by score (default), severity. Server side filters via query params.
- Top strip: three counters (Reachable, Unknown, No path found) computed from the returned rows.
- Legend card, always visible: explains the three labels, and states "No path found is not proof of safety." Link "How is the score computed?" opens a modal with the formula and weights from the finding's score_breakdown.
- Risk-accepted rows appear at the bottom with a "Risk accepted by <name>" tag (information from the finding row/detail).
- Empty state: "No known vulnerabilities found for the pinned dependencies. This is data from OSV.dev, not proof of safety." plus if lockfile_kind is none: "No dependency file found; add requirements.txt or poetry.lock".
- Choke-points card from GET /api/repos/{id}/choke-points: "Upgrade or remove these packages to clear the most reachable findings" with counts and links to the findings.
```

**Verify F4:** counters equal the number of rows with that verdict. Filtering changes the URL query and the table. Compare the first three rows with `curl .../findings` output.

## F5. Finding detail with the proof path graph (the standout screen)

```
Implement /repos/:repoId/findings/:findingId using GET /findings/{fid} and GET /graph?finding_id=.
- Left column: finding summary (vulnerability id + summary, severity, package, version, fixed versions as chips), the verdict badge, score with the breakdown shown as a small table (reach, severity, exposure, weights, final score) and the formula text from the API.
- Main panel: Cytoscape.js graph. Node shapes/colors by label (Entrypoint, Module, Package, Vulnerability). Path nodes and edges from highlight.* are bold with the accent color and animated (a subtle pulsing or flowing dash along edges); other nodes are dimmed. Layout: dagre-like left-to-right using Cytoscape's built-in "breadthfirst" with directed true and roots = entrypoints; fit to view. Pan, zoom, a "Reset view" button. Click a node shows a side card with its props (file, line, version).
- Proof path text panel above the graph: the first path rendered as a breadcrumb "POST /login -> app.views -> flask-wtf@... -> pkg@version" taken from trace.paths[0], with each hop labeled by its edge type in plain language (handled by, imports, uses, depends on). If several paths, a selector for path 1..3 which re-highlights.
- If verdict is no_path_found: show a "Search scope" card with trace.searched_scope (modules searched, files parsed/failed, lockfile kind, transitive available) and the text "This is not proof of safety. It only means no path was found in the analyzed graph." If reason is declared_not_imported say "This package is in the dependency file but no import of it was found."
- If verdict is unknown: list blind spots (kind, file, line, reason) in a table.
- Owners and "Suggested next step" card from the API fields (fixed versions); never claim a fix is applied.
- Memory section: list of past investigations and decisions for this finding from the finding detail (who, when, verdict at that time, reason).
- Decision panel (analyst/admin): form to create a decision (type select, reason textarea min 10 chars, optional expiry date). accept_risk shows "Pending admin approval" after creation. Admins see Approve/Reject buttons on pending decisions.
Wire nothing to localStorage. All state comes from the API.
```

**Verify F5:** open a reachable finding; the highlighted path matches the breadcrumb and the FalkorDB Browser query result. Open a no-path finding: scope card and the no-proof sentence show. Create a decision as an analyst: "pending". As admin: approve, and the finding row shows risk-accepted back on the dashboard.

## F6. What-if panel (after Member-2's B9)

```
On the finding detail page add a "What if..." panel for analyst/admin.
- Lists the public entrypoints on the current proof path with a button "Simulate: add authentication to <METHOD path>", and the module->package USES edges on the path with "Simulate: remove import of <package> from <module>".
- Calls POST /api/repos/{id}/whatif with the change. Show a side by side before/after: verdict badges, path counts, and the after-graph highlight (render the after TraceResult paths in a second small Cytoscape instance). A banner states "Simulation on a temporary copy. Nothing was changed."
- Handle errors (422 invalid change, 501 or 500 if copy unsupported) with a clear message.
```

**Verify F6:** simulate on a reachable finding; the verdict flips or the path count changes consistently with the graph; after the call, reload the finding: unchanged.

## F7. Chat panel (after G3)

```
Add a collapsible chat panel (right side, available on repo and finding pages) using POST /api/repos/{id}/agent/chat.
- Message list, input (Enter sends, Shift+Enter newline), session_id kept in component state and sent with each message; a "New session" button clears it.
- "Save investigation" toggle, visible and enabled only for analyst/admin, sends save=true.
- While waiting show a typing indicator; LLM calls can take 30+ seconds with local models so show elapsed seconds, and allow cancel (AbortController).
- Under each answer: a mode chip ("LLM + tools", "LLM explanation", "Deterministic"), a "grounded" check mark (green if grounded true, amber with the warnings list otherwise), and an expandable "Evidence" section: the tool_calls list (name, args, summary) and for each evidence.traces item a "Show path" button that highlights that finding's path on the main graph or opens the finding page.
- Finding ids in the answer text become links to the finding page ONLY if the id exists in evidence.findings.
- Suggested starter questions as buttons, built from the real finding list (e.g. "Why is <top package> ranked first?"). If there are no findings, no suggestions.
- Show API errors (403 for viewers using save, 429 rate limit) as friendly messages.
```

**Verify F7:** ask "Which finding should I fix first and why?". The answer appears with tool calls under Evidence. Stop Ollama: the next answer shows the "Deterministic" chip. As viewer the Save toggle is hidden.

## F8. Memory view and admin users

```
1. Memory page /repos/:repoId/memory: timeline from GET /api/repos/{id}/memory (investigations and decisions, newest first): who, when, finding link, verdict, summary or decision type and status. Empty state: "Nothing saved yet. Investigations appear here when an analyst chats with saving enabled or records a decision."
2. Admin users page /admin/users (admin only): table from GET /api/admin/users, create user dialog (email, password min 10 chars, role select), change role, deactivate/reactivate, reset password. Show the 409 error text when trying to remove the last admin. No user data is hardcoded.
3. Change-password dialog in the header menu calling /api/auth/change-password.
```

**Verify F8:** after F5 and F7 actions the timeline shows the entries. Create a viewer, log in as them in a private window, check they cannot reach `/admin/users`.

## F9. Polish and quality bar (before G4)

```
Quality pass over the whole frontend:
- Every data screen has loading skeletons, empty states, and error states with a Retry button.
- Responsive down to 1024px wide (demo laptops) and usable at tablet width. Keyboard navigation works; focus rings visible; all buttons and inputs have labels; color is never the only carrier of meaning.
- A global error boundary; no unhandled promise rejections; no console errors or warnings in a full click-through.
- Run: npm run lint, npm run typecheck, npm run build with zero errors.
- Run the guard: bash scripts/no_demo_data.sh (from repo root) must pass.
- Page titles per route; favicon; app name ReachGuard.
- A footer with the honest limits line: "Python only. Module-level analysis. Heuristic auth detection. Results show reachability in the analyzed model, not proof of exploitability."
```

## F10. Docker (hand over to Member-4)

```
Create frontend/Dockerfile (multi-stage: node:20-alpine build -> nginx:alpine) and frontend/nginx.conf exactly as described in docs/02_MEMBER4_PROMPTS.md section D2 (SPA fallback with try_files, /api proxy to http://backend:8000/api/, gzip, security headers, client_max_body_size 55m). The build must use relative /api URLs so no host is baked into the bundle.
```

**Verify F10:** `docker build -t reachguard-web ./frontend` succeeds.

## F11. GATE G4

Full click-through on a real analyzed repo (checklist):
- [ ] Login as admin, analyst, viewer: menus differ correctly.
- [ ] Add a real repo, watch statuses, see findings.
- [ ] Open reachable, no-path and (if present) unknown findings: each renders correct sections.
- [ ] Path highlight matches the proof text.
- [ ] What-if works and leaves the real graph unchanged.
- [ ] Chat answers with evidence; deterministic mode works with Ollama stopped.
- [ ] Decision pending, admin approves, finding shows risk accepted.
- [ ] Backend restart, new session: memory is still shown.
- [ ] `npm run build`, lint, typecheck pass; `no_demo_data.sh` passes.

**DONE message:** `GATE G4 DONE | M1 | commit <sha> | checklist: <n>/9 ticked | screenshots: <folder> | known issues: <...>`
**Waiting teammate:** Member-4 runs `scripts/e2e.py` and a manual pass in the browser.

**Safe work while waiting for gates:** build components against TypeScript types only; keep a `docs/UI_NOTES.md`; capture clean screenshots for the deck once G3 is done.
