/**
 * ReachGuard TypeScript Types.
 * Single source of truth adhering strictly to Contract Sections 7 & 8.
 */

// ── Auth & Users ───────────────────────────────────────────────────

export type UserRole = "viewer" | "analyst" | "admin";

export interface User {
  id: string;
  email: string;
  role: UserRole;
  active?: boolean;
  created_at?: string;
}

export interface LoginRequest {
  email: string;
  password: string;
}

export interface LoginResponse {
  access_token: string;
  token_type: "bearer";
  user: User;
}

export interface ChangePasswordRequest {
  current_password?: string;
  old_password?: string;
  new_password: string;
}

export interface CreateUserRequest {
  email: string;
  password: string;
  role: UserRole;
}

export interface PatchUserRequest {
  role?: UserRole;
  active?: boolean;
  password?: string;
}

export interface HealthResponse {
  status: string;
  falkordb: boolean;
  llm: {
    provider: string;
    model: string;
    reachable: boolean;
    mode: "llm" | "deterministic";
  };
  version: string;
}

// ── Standard API Error Envelope ────────────────────────────────────

export interface ApiErrorShape {
  error: {
    code: string | number;
    message: string;
  };
}

export class ApiError extends Error {
  code: string | number;
  statusCode: number;

  constructor(message: string, code: string | number, statusCode: number) {
    super(message);
    this.name = "ApiError";
    this.code = code;
    this.statusCode = statusCode;
  }
}

// ── Repositories ───────────────────────────────────────────────────

export type RepoStatus =
  | "queued"
  | "cloning"
  | "parsing"
  | "scanning"
  | "ready"
  | "failed";

export interface RepoStats {
  files_parsed: number;
  files_failed: number;
  modules: number;
  entrypoints: number;
  public_entrypoints: number;
  packages: number;
  direct_packages: number;
  findings: number;
  blind_spots: number;
  lockfile_kind: string;
  transitive_available: boolean;
  no_entrypoints?: boolean;
}

export interface Repo {
  id: string;
  source: string;
  source_type?: "git" | "zip";
  status: RepoStatus;
  stage_detail?: string | null;
  error?: string | null;
  created_at: string;
  created_by?: string;
  stats?: RepoStats;
}

// ── Findings & Verdicts ────────────────────────────────────────────

export type Verdict = "reachable_in_model" | "unknown" | "no_path_found";

export type FindingStatus =
  | "open"
  | "risk_accepted"
  | "fixed"
  | "false_positive"
  | "fix_planned";

export type Severity =
  | "CRITICAL"
  | "HIGH"
  | "MODERATE"
  | "LOW"
  | "UNKNOWN";

export interface FindingRow {
  id: string;
  vuln_id: string;
  aliases: string[];
  summary: string;
  severity: Severity;
  package: string;
  version: string;
  fixed_versions: string[];
  verdict: Verdict;
  score: number;
  status: FindingStatus;
  owners: string[];
  risk_accepted_by?: string | null;
}


export interface ScoreWeights {
  reach: number;
  severity: number;
  exposure: number;
}

export interface ScoreBreakdown {
  reach: number;
  severity: number;
  exposure: number;
  weights: ScoreWeights;
  score: number;
  formula?: string;
}

// ── Traces & Call Paths (Contract Section 8) ───────────────────────

export interface TraceGraphNode {
  id: string;
  label: "Entrypoint" | "Module" | "Package" | string;
  name: string;
}

export interface TraceGraphEdge {
  id: string;
  type: "HANDLED_BY" | "IMPORTS" | "USES" | "DEPENDS_ON" | string;
}

export interface TracePath {
  entrypoint_id: string;
  entrypoint: string;
  nodes: TraceGraphNode[];
  edges: TraceGraphEdge[];
}

export interface BlindSpot {
  kind: "dynamic_import" | "unresolved_import" | "unparsed_file";
  file: string;
  line: number;
  reason: string;
  name?: string;
}

export interface SearchedScope {
  modules: number;
  files_parsed: number;
  files_failed: number;
  max_depth: number;
  lockfile_kind: string;
  transitive_available: boolean;
}

export interface TraceResult {
  finding_id: string;
  verdict: Verdict;
  reason?: string;
  paths: TracePath[];
  reaching_entrypoints: number;
  total_public_entrypoints: number;
  blind_spots: BlindSpot[];
  searched_scope: SearchedScope;
}

// ── Decisions & Memory ─────────────────────────────────────────────

export type DecisionType =
  | "accept_risk"
  | "fix_planned"
  | "false_positive"
  | "fixed";

export type DecisionStatus = "pending" | "approved" | "rejected";

export interface Decision {
  id: string;
  type: DecisionType;
  reason: string;
  by: string;
  status: DecisionStatus;
  approved_by?: string | null;
  created_at: string;
  expires_at?: string | null;
  finding_id?: string;
}

export interface Investigation {
  id: string;
  created_at: string;
  by: string;
  verdict: string;
  score: number;
  path_json: string;
  summary: string;
  session_id: string;
  finding_id?: string;
}

export interface FindingDetail extends FindingRow {
  trace: TraceResult;
  score_breakdown: ScoreBreakdown;
  investigations: Investigation[];
  decisions: Decision[];
}

export interface MemoryResponse {
  investigations: Investigation[];
  decisions: Decision[];
}

// ── Graph Views ────────────────────────────────────────────────────

export interface GraphNode {
  id: string;
  label: string;
  name: string;
  props?: Record<string, unknown>;
}

export interface GraphEdge {
  id: string;
  source: string;
  target: string;
  type: string;
}

export interface GraphResponse {
  nodes: GraphNode[];
  edges: GraphEdge[];
  highlight?: {
    nodes: string[];
    edges: string[];
  };
  truncated?: boolean;
}

// ── Choke Points & What-If ─────────────────────────────────────────

export interface ChokePoint {
  package: string;
  version: string;
  clears_findings: number;
  finding_ids: string[];
}

export type WhatIfChange =
  | { type: "add_auth"; entrypoint_id: string }
  | { type: "remove_import"; module_id: string; package_id: string };

export interface WhatIfRequest {
  finding_id?: string;
  changes: WhatIfChange[];
}

export interface WhatIfChangedVerdict {
  finding_id: string;
  from: string;
  to: string;
}

export interface WhatIfResponse {
  before: TraceResult | Record<string, string>;
  after: TraceResult | Record<string, string>;
  changed: WhatIfChangedVerdict[];
}

// ── Agent & Chat ───────────────────────────────────────────────────

export type AgentMode = "llm_tools" | "llm_explain" | "deterministic";

export interface ToolCallRecord {
  name: string;
  args: Record<string, unknown>;
  ok: boolean;
  summary: string;
}

export interface AgentEvidence {
  findings?: FindingRow[];
  traces?: TraceResult[];
  memory?: Array<{
    investigations?: Investigation[];
    decisions?: Decision[];
  }>;
}

export interface ChatRequest {
  message: string;
  session_id?: string;
  save?: boolean;
}

export interface ChatResponse {
  session_id: string;
  answer: string;
  mode: AgentMode;
  tool_calls: ToolCallRecord[];
  evidence: AgentEvidence;
  grounded: boolean;
  warnings: string[];
}
