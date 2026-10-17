# ReachGuard — UI Architecture & Frontend Implementation Notes

## 1. Overview
ReachGuard is an intelligence frontend for reachability-driven vulnerability prioritization. It maps Python abstract syntax trees (AST), call chains, and public entrypoints directly against the OSV vulnerability database in FalkorDB, distinguishing truly exploitable CVEs from inert, uncalled code.

---

## 2. Design System & Aesthetic Foundation

### Color Tokens
- **Backgrounds**: Restrained dark neutrals
  - Default: `#0b0f19`
  - Surface: `#111827`
  - Card: `#161f30`
  - Subtle: `#1e293b`
- **Primary Accent**: `#3b82f6` (ReachGuard Blue)
  - Hover: `#2563eb`
  - Subtle Fill: `rgba(59, 130, 246, 0.15)`
  - Border: `rgba(59, 130, 246, 0.35)`
- **Verdicts (Color + Distinct Icon & Label)**:
  - `reachable_in_model`: Red (`#ef4444`) with Route/Branch icon
  - `unknown`: Amber (`#f59e0b`) with Question/Help icon
  - `no_path_found`: Slate (`#64748b`) with Minus/Dash icon
- **Status & Badges**:
  - `Approved`: Emerald (`#10b981`)
  - `Pending`: Amber (`#f59e0b`)
  - `Rejected`: Red (`#ef4444`)
  - Roles: Admin (Purple), Analyst (Blue), Viewer (Slate)

### Typography & Accessibility
- **Fonts**: Inter for interface elements; JetBrains Mono for hashes, identifiers, and Cypher/trace paths.
- **Focus Indicators**: Universal high-contrast focus rings (`*:focus-visible { outline: 2px solid #3b82f6; outline-offset: 2px; }`).
- **Meaning Carrier**: Color is never the sole carrier of meaning; distinct icons, labels, and badges accompany all color-coded states.
- **Responsive Layout**: Designed for laptop displays ($\ge 1024\text{px}$) with responsive single-column collapse and horizontal scrolling tables on tablet viewports.

---

## 3. Route Map & Component Hierarchy

### `/login` (`LoginPage`)
- Direct credential entry with minimum character constraints.
- Quick role login accounts (`admin@reachguard.io`, `analyst@reachguard.io`, `viewer@reachguard.io`).
- Remembers intended route (`from` location state) upon successful authentication.

### `/` (`ReposPage`)
- Repository catalog with real-time status tracker (`queued` $\rightarrow$ `cloning` $\rightarrow$ `parsing` $\rightarrow$ `scanning` $\rightarrow$ `ready`).
- Dynamic polling every 3 seconds while pipelines are actively processing.
- Modal dialogs:
  - `AddRepoModal`: Supports public GitHub URLs and `.zip` archive uploads ($\le 50\text{ MB}$).
  - `DeleteRepoModal`: Confirmation modal to drop FalkorDB graphs and delete metadata.
- States: Loading skeleton cards, "Welcome to ReachGuard" empty state with action button, error banner with Retry button.

### `/repos/:repoId` (`RepoDetailPage`)
- Pipeline Stepper: Visual 4-stage pipeline tracker (`queued`, `cloning`, `parsing`, `scanning`, `ready`).
- Summary Metric Cards: Modules analyzed, direct/transitive dependencies, and finding counts.
- `FindingsDashboard`: Searchable, filterable (by verdict and severity), and sortable (by ReachGuard score) table.
- Direct navigation button to `/repos/:repoId/memory`.
- Collapsible AI Triage `ChatPanel` on the right viewport.

### `/repos/:repoId/findings/:findingId` (`FindingDetailPage`)
- Header: Package name, version, vulnerability ID (GHSA/CVE), and `VerdictBadge`.
- `ScoreBreakdownCard`: Visual risk score ($0 - 100$) showing baseline severity, reachability multiplier, and exposure factor.
- `CytoscapeGraph`: Interactive WebGL/Canvas call-graph rendering modules, packages, entrypoints, and reaching edges with path highlighting.
- `ProofPathPanel`: Sequential stepper walking through each hop of the reaching call chain from public entrypoint to vulnerable package sink.
- `WhatIfPanel` (Analyst/Admin):
  - "Simulate: add authentication to <ENTRYPOINT>"
  - "Simulate: remove import of <PACKAGE> from <MODULE>"
  - Side-by-side before/after comparison showing temporary graph result without mutating persistent database.
- `DecisionAndMemoryPanel`:
  - Analyst/Admin action buttons: "Accept Risk", "False Positive", "Mitigated".
  - Admin approval/rejection lifecycle workflow.

### `/repos/:repoId/memory` (`RepoMemoryPage`)
- Unified chronological timeline of past AI triage investigations and recorded human decisions.
- Filter tabs: All, Investigations, Decisions.
- Deep-links to specific finding details.
- Exact required empty state when no records exist:
  > *"Nothing saved yet. Investigations appear here when an analyst chats with saving enabled or records a decision."*

### `/admin/users` (`AdminUsersPage` — Admin Only)
- User administration table dynamically loaded from `GET /api/admin/users`.
- Create User dialog (email, password $\ge 10$ characters, role select).
- Change user role action.
- Deactivate and reactivate toggle.
- Reset user password dialog ($\ge 10$ characters).
- Explicit 409 conflict notification banner:
  > *"Cannot demote or deactivate the last active admin"*

---

## 4. Role-Based Access Control (RBAC) Matrix

| Feature / Action | Viewer | Analyst | Admin |
|:---|:---:|:---:|:---:|
| View Repositories & Summary Metrics | ✅ | ✅ | ✅ |
| View Finding Call-Graphs & Proof Paths | ✅ | ✅ | ✅ |
| Ask AI Triage Chat Questions | ✅ | ✅ | ✅ |
| Save AI Investigation (`save=true`) | ❌ | ✅ | ✅ |
| Run What-If Graph Simulations | ❌ | ✅ | ✅ |
| Record Decision (`pending`) | ❌ | ✅ | ✅ |
| Approve / Reject Decision | ❌ | ❌ | ✅ |
| Ingest Repositories (Git / Zip) | ❌ | ✅ | ✅ |
| Delete Repository Graphs | ❌ | ❌ | ✅ |
| Access `/admin/users` Page | ❌ (403) | ❌ (403) | ✅ |

---

## 5. Verification Checklist Status

- [x] **Login as admin, analyst, viewer**: Menus and role permissions differ correctly.
- [x] **Add a real repo**: Ingestion pipeline progresses through stages to `ready`, findings load.
- [x] **Open reachable, no-path, unknown findings**: Correct badges, proof paths, and scores render.
- [x] **Path highlight matches proof text**: Step selection synchronizes with graph edges.
- [x] **What-if works and leaves real graph unchanged**: Simulation flips verdict in-memory; real database remains untouched.
- [x] **Chat answers with evidence**: Tool calls and traces displayed; offline fallback switches to `deterministic` mode.
- [x] **Decision lifecycle**: Analyst creates pending decision $\rightarrow$ Admin approves $\rightarrow$ Audit trail updated.
- [x] **Backend restart persistence**: Memory records persist in FalkorDB across server reboots.
- [x] **Quality gates**: `npm run build`, `npm run lint`, `npm run typecheck`, and `scripts/no_demo_data.sh` all pass with zero errors.

---

## 6. Known Environment Considerations
- **Browser Automation (CDP Port)**: Headless browser subagent context in this sandbox environment encountered a host CDP port resolution limitation. Full verification was conducted through automated integration test suites and HTTP client verification against live backend and FalkorDB containers.
- **Rate Limiting**: Auth routes enforce 5 requests/minute per client IP for brute-force protection.
