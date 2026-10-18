import React, { useState, useMemo } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { apiFetch } from "../api/client";
import { VerdictBadge } from "./VerdictBadge";
import { ScoreComputationModal } from "./ScoreComputationModal";
import type {
  FindingRow,
  FindingStatus,
  Severity,
  Verdict,
  ChokePoint,
} from "../api/types";

interface FindingsDashboardProps {
  repoId: string;
  lockfileKind?: string;
  publicEntrypoints?: number;
  noEntrypoints?: boolean;
}

interface PackageFindingGroup {
  packageKey: string;
  packageName: string;
  packageVersion: string;
  findings: FindingRow[];
  count: number;
  worstSeverity: Severity;
  bestVerdict: Verdict;
  highestScore: number;
}

const SEVERITY_RANK: Record<Severity, number> = {
  CRITICAL: 4,
  HIGH: 3,
  MODERATE: 2,
  LOW: 1,
  UNKNOWN: 0,
};

const VERDICT_RANK: Record<Verdict, number> = {
  reachable_in_model: 3,
  unknown: 2,
  no_path_found: 1,
};

export const FindingsDashboard: React.FC<FindingsDashboardProps> = ({
  repoId,
  lockfileKind,
  publicEntrypoints,
  noEntrypoints,
}) => {
  const navigate = useNavigate();
  const [searchParams, setSearchParams] = useSearchParams();

  // Read filter values directly from URL search params
  const verdictFilter = searchParams.get("verdict") || "all";
  const statusFilter = searchParams.get("status") || "all";
  const searchQuery = searchParams.get("q") || "";
  const sortBy = (searchParams.get("sort") as "score" | "severity") || "score";

  // View Mode: grouped by package@version (default) or flat list
  const [viewMode, setViewMode] = useState<"grouped" | "flat">("grouped");

  // Show no-path findings chip state (default: hidden, only Reachable and Unknown)
  const [showNoPath, setShowNoPath] = useState<boolean>(false);

  // Expanded package group keys
  const [expandedKeys, setExpandedKeys] = useState<Set<string>>(new Set());

  // Modal state
  const [isScoreModalOpen, setIsScoreModalOpen] = useState<boolean>(false);

  // Helper to update a URL search param
  const updateParam = (key: string, value: string) => {
    setSearchParams((prev) => {
      const next = new URLSearchParams(prev);
      if (!value || value === "all" || (key === "sort" && value === "score")) {
        next.delete(key);
      } else {
        next.set(key, value);
      }
      return next;
    });
  };

  const toggleExpand = (packageKey: string) => {
    setExpandedKeys((prev) => {
      const next = new Set(prev);
      if (next.has(packageKey)) {
        next.delete(packageKey);
      } else {
        next.add(packageKey);
      }
      return next;
    });
  };

  // Build query params for GET /api/repos/{id}/findings
  const queryParams = useMemo(() => {
    const params: Record<string, string> = {};
    if (verdictFilter !== "all") {
      params.verdict = verdictFilter;
    }
    if (statusFilter !== "all") {
      params.status = statusFilter;
    }
    if (searchQuery.trim()) {
      params.q = searchQuery.trim();
    }
    if (sortBy) {
      params.sort = sortBy;
    }
    return params;
  }, [verdictFilter, statusFilter, searchQuery, sortBy]);

  // Query filtered findings for the table
  const {
    data: rawFindings = [],
    isLoading,
    isError,
    error,
    refetch,
  } = useQuery<FindingRow[]>({
    queryKey: ["findings", repoId, queryParams],
    queryFn: () =>
      apiFetch<FindingRow[]>(`/api/repos/${repoId}/findings`, {
        params: queryParams,
      }),
  });

  // Query all findings to accurately calculate total verdict counters
  const { data: allFindings = [] } = useQuery<FindingRow[]>({
    queryKey: ["findings-all", repoId],
    queryFn: () => apiFetch<FindingRow[]>(`/api/repos/${repoId}/findings`),
  });

  // Query choke points from GET /api/repos/{id}/choke-points
  const { data: chokePoints = [] } = useQuery<ChokePoint[]>({
    queryKey: ["choke-points", repoId],
    queryFn: () => apiFetch<ChokePoint[]>(`/api/repos/${repoId}/choke-points`),
  });

  // Top strip counters
  const counts = useMemo(() => {
    let reachable = 0;
    let unknown = 0;
    let nopath = 0;

    for (const f of allFindings) {
      if (f.verdict === "reachable_in_model") reachable++;
      else if (f.verdict === "unknown") unknown++;
      else if (f.verdict === "no_path_found") nopath++;
    }

    return { reachable, unknown, nopath, total: allFindings.length };
  }, [allFindings]);

  // Apply default filter: Reachable and Unknown only, unless showNoPath is active or user chose no_path_found
  const displayedFindings = useMemo(() => {
    if (verdictFilter === "no_path_found") {
      return rawFindings.filter((f) => f.verdict === "no_path_found");
    }
    if (verdictFilter !== "all") {
      return rawFindings;
    }
    // Default filter: only reachable and unknown, unless showNoPath is toggled
    if (!showNoPath) {
      return rawFindings.filter(
        (f) => f.verdict === "reachable_in_model" || f.verdict === "unknown"
      );
    }
    return rawFindings;
  }, [rawFindings, verdictFilter, showNoPath]);

  // Group displayed findings by package@version
  const groupedFindings: PackageFindingGroup[] = useMemo(() => {
    const map = new Map<string, FindingRow[]>();

    for (const f of displayedFindings) {
      const key = `${f.package}@${f.version || "*"}`;
      if (!map.has(key)) {
        map.set(key, []);
      }
      map.get(key)!.push(f);
    }

    const groups: PackageFindingGroup[] = [];

    for (const [key, items] of map.entries()) {
      let worstSev: Severity = "UNKNOWN";
      let maxSevRank = -1;
      let bestVer: Verdict = "no_path_found";
      let maxVerRank = -1;
      let highestScore = 0;

      for (const item of items) {
        const sRank = SEVERITY_RANK[item.severity] ?? 0;
        if (sRank > maxSevRank) {
          maxSevRank = sRank;
          worstSev = item.severity;
        }

        const vRank = VERDICT_RANK[item.verdict] ?? 0;
        if (vRank > maxVerRank) {
          maxVerRank = vRank;
          bestVer = item.verdict;
        }

        if ((item.score ?? 0) > highestScore) {
          highestScore = item.score ?? 0;
        }
      }

      const [pkg, ver] = key.split("@");

      groups.push({
        packageKey: key,
        packageName: pkg,
        packageVersion: ver,
        findings: items,
        count: items.length,
        worstSeverity: worstSev,
        bestVerdict: bestVer,
        highestScore,
      });
    }

    // Sort groups by highestScore descending
    groups.sort((a, b) => b.highestScore - a.highestScore);
    return groups;
  }, [displayedFindings]);

  const getSeverityBadge = (severity: Severity) => {
    switch (severity) {
      case "CRITICAL":
        return (
          <span className="px-2 py-0.5 rounded text-[10px] font-bold bg-red-500/20 text-red-400 border border-red-500/35 uppercase">
            Critical
          </span>
        );
      case "HIGH":
        return (
          <span className="px-2 py-0.5 rounded text-[10px] font-bold bg-orange-500/20 text-orange-400 border border-orange-500/35 uppercase">
            High
          </span>
        );
      case "MODERATE":
        return (
          <span className="px-2 py-0.5 rounded text-[10px] font-bold bg-amber-500/20 text-amber-400 border border-amber-500/35 uppercase">
            Moderate
          </span>
        );
      case "LOW":
        return (
          <span className="px-2 py-0.5 rounded text-[10px] font-bold bg-blue-500/20 text-blue-400 border border-blue-500/35 uppercase">
            Low
          </span>
        );
      case "UNKNOWN":
      default:
        return (
          <span className="px-2 py-0.5 rounded text-[10px] font-medium bg-slate-500/20 text-slate-400 border border-slate-500/35 uppercase">
            Unknown
          </span>
        );
    }
  };

  // Severity badge for group row: Unrated when UNKNOWN
  const getGroupWorstSeverityBadge = (severity: Severity) => {
    if (severity === "UNKNOWN") {
      return (
        <span className="px-2 py-0.5 rounded text-[10px] font-medium bg-slate-500/20 text-slate-400 border border-slate-500/35 uppercase">
          Unrated
        </span>
      );
    }
    return getSeverityBadge(severity);
  };

  const getStatusBadge = (status: FindingStatus) => {
    switch (status) {
      case "risk_accepted":
        return (
          <span className="px-2 py-0.5 rounded-full text-[11px] font-medium bg-purple-500/15 text-purple-300 border border-purple-500/30">
            Risk Accepted
          </span>
        );
      case "fixed":
        return (
          <span className="px-2 py-0.5 rounded-full text-[11px] font-medium bg-emerald-500/15 text-emerald-400 border border-emerald-500/30">
            Fixed
          </span>
        );
      case "fix_planned":
        return (
          <span className="px-2 py-0.5 rounded-full text-[11px] font-medium bg-sky-500/15 text-sky-400 border border-sky-500/30">
            Fix Planned
          </span>
        );
      case "false_positive":
        return (
          <span className="px-2 py-0.5 rounded-full text-[11px] font-medium bg-slate-500/15 text-slate-400 border border-slate-500/30">
            False Positive
          </span>
        );
      case "open":
      default:
        return (
          <span className="px-2 py-0.5 rounded-full text-[11px] font-medium bg-amber-500/15 text-amber-400 border border-amber-500/30">
            Open
          </span>
        );
    }
  };

  const getScoreColor = (score: number) => {
    if (score >= 75) return "bg-red-500 text-red-400";
    if (score >= 45) return "bg-amber-500 text-amber-400";
    return "bg-slate-400 text-slate-400";
  };

  const hasNoPublicEntrypoints = publicEntrypoints === 0 || Boolean(noEntrypoints);

  return (
    <div className="space-y-6">
      {/* ════════════════════════════════════════════════════════════════
          NO WEB ROUTES BANNER (WHEN STATS SHOW 0 PUBLIC ENTRYPOINTS)
          ════════════════════════════════════════════════════════════════ */}
      {hasNoPublicEntrypoints && (
        <div className="p-4 rounded-xl bg-amber-500/10 border border-amber-500/30 text-amber-200 text-xs flex items-start gap-3 shadow-sm">
          <svg
            className="w-5 h-5 text-amber-400 shrink-0 mt-0.5"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            strokeWidth="2"
          >
            <path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z" />
            <line x1="12" y1="9" x2="12" y2="13" />
            <line x1="12" y1="17" x2="12.01" y2="17" />
          </svg>
          <div className="space-y-1">
            <span className="font-bold text-amber-300 block">
              Analysis Notice:
            </span>
            <p className="leading-relaxed">
              No web routes were detected in this repository (Python Flask and FastAPI only). Verdicts can&apos;t be judged.
            </p>
          </div>
        </div>
      )}

      {/* ════════════════════════════════════════════════════════════════
          TOP STRIP: THREE VERDICT COUNTERS
          ════════════════════════════════════════════════════════════════ */}
      <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
        {/* Reachable Counter */}
        <div
          onClick={() =>
            updateParam(
              "verdict",
              verdictFilter === "reachable_in_model" ? "all" : "reachable_in_model"
            )
          }
          className={`p-4 rounded-xl border transition-all cursor-pointer ${
            verdictFilter === "reachable_in_model"
              ? "bg-red-500/15 border-red-500/60 ring-1 ring-red-500/30"
              : "bg-bg-surface hover:bg-bg-card border-border"
          }`}
        >
          <div className="flex items-center justify-between">
            <span className="text-xs font-semibold uppercase tracking-wider text-red-400 flex items-center gap-1.5">
              <span className="w-2 h-2 rounded-full bg-red-500" />
              Reachable in Model
            </span>
            <span className="text-2xl font-bold font-mono text-white">
              {counts.reachable}
            </span>
          </div>
          <p className="text-[11px] text-gray-400 mt-1">
            Confirmed call paths from public/authenticated entrypoints
          </p>
        </div>

        {/* Unknown Counter */}
        <div
          onClick={() =>
            updateParam("verdict", verdictFilter === "unknown" ? "all" : "unknown")
          }
          className={`p-4 rounded-xl border transition-all cursor-pointer ${
            verdictFilter === "unknown"
              ? "bg-amber-500/15 border-amber-500/60 ring-1 ring-amber-500/30"
              : "bg-bg-surface hover:bg-bg-card border-border"
          }`}
        >
          <div className="flex items-center justify-between">
            <span className="text-xs font-semibold uppercase tracking-wider text-amber-400 flex items-center gap-1.5">
              <span className="w-2 h-2 rounded-full bg-amber-500" />
              Unknown
            </span>
            <span className="text-2xl font-bold font-mono text-white">
              {counts.unknown}
            </span>
          </div>
          <p className="text-[11px] text-gray-400 mt-1">
            Static analysis obstructed by dynamic imports or unparsed modules
          </p>
        </div>

        {/* No Path Found Counter */}
        <div
          onClick={() =>
            updateParam(
              "verdict",
              verdictFilter === "no_path_found" ? "all" : "no_path_found"
            )
          }
          className={`p-4 rounded-xl border transition-all cursor-pointer ${
            verdictFilter === "no_path_found"
              ? "bg-slate-500/20 border-slate-400/60 ring-1 ring-slate-400/30"
              : "bg-bg-surface hover:bg-bg-card border-border"
          }`}
        >
          <div className="flex items-center justify-between">
            <span className="text-xs font-semibold uppercase tracking-wider text-slate-300 flex items-center gap-1.5">
              <span className="w-2 h-2 rounded-full bg-slate-400" />
              No Path Found
            </span>
            <span className="text-2xl font-bold font-mono text-white">
              {counts.nopath}
            </span>
          </div>
          <p className="text-[11px] text-gray-400 mt-1">
            No active route found connecting public entrypoints to package
          </p>
        </div>
      </div>

      {/* ════════════════════════════════════════════════════════════════
          TOP CHOKE POINTS SUMMARY
          ════════════════════════════════════════════════════════════════ */}
      {chokePoints && chokePoints.length > 0 && (
        <div className="bg-bg-surface border border-accent/30 rounded-xl p-4 shadow-sm space-y-3">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2">
              <div className="w-7 h-7 rounded-lg bg-accent/15 border border-accent/30 flex items-center justify-center text-accent">
                <svg className="w-4 h-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                  <path d="M12 2v20M17 5H9.5a3.5 3.5 0 0 0 0 7h5a3.5 3.5 0 0 1 0 7H6" />
                </svg>
              </div>
              <h3 className="text-sm font-semibold text-white">
                Top Remediation Choke Points
              </h3>
            </div>
            <span className="text-xs text-gray-400">
              Fixing these libraries yields maximum vulnerability reduction
            </span>
          </div>

          <div className="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-3 gap-3">
            {chokePoints.slice(0, 3).map((cp) => (
              <div
                key={`${cp.package}@${cp.version}`}
                onClick={() => updateParam("q", cp.package)}
                className="bg-bg-card border border-border hover:border-accent/40 rounded-lg p-3 transition-colors cursor-pointer group"
              >
                <div className="font-mono text-xs font-semibold text-white group-hover:text-accent transition-colors truncate">
                  {cp.package}
                  <span className="text-gray-400 font-normal">@{cp.version}</span>
                </div>
                <div className="flex items-center justify-between mt-1 text-xs text-gray-400">
                  <span>Clears findings:</span>
                  <span className="font-bold text-red-400 font-mono">
                    {cp.clears_findings}
                  </span>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* ════════════════════════════════════════════════════════════════
          SEARCH & FILTER TOOLBAR + VIEW MODE TOGGLE + NO-PATH CHIP
          ════════════════════════════════════════════════════════════════ */}
      <div className="bg-bg-surface border border-border rounded-xl p-4 flex flex-col md:flex-row items-center justify-between gap-4">
        {/* Search input */}
        <div className="w-full md:w-80 relative">
          <svg
            className="w-4 h-4 text-gray-400 absolute left-3 top-3"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            strokeWidth="2"
          >
            <circle cx="11" cy="11" r="8" />
            <line x1="21" y1="21" x2="16.65" y2="16.65" />
          </svg>
          <input
            type="text"
            value={searchQuery}
            onChange={(e) => updateParam("q", e.target.value)}
            placeholder="Search CVE, package, or summary..."
            className="w-full pl-9 pr-3.5 py-2 bg-bg-card border border-border rounded-lg text-xs text-white placeholder-gray-500 focus:outline-none focus:ring-1 focus:ring-accent"
          />
          {searchQuery && (
            <button
              onClick={() => updateParam("q", "")}
              className="absolute right-2.5 top-2.5 text-gray-500 hover:text-white"
            >
              ×
            </button>
          )}
        </div>

        {/* Filter select inputs and View Mode Toggle */}
        <div className="flex items-center gap-3 w-full md:w-auto flex-wrap">
          {/* Show no-path findings chip */}
          {verdictFilter === "all" && counts.nopath > 0 && (
            <button
              type="button"
              onClick={() => setShowNoPath(!showNoPath)}
              className={`px-3 py-1.5 rounded-lg border text-xs font-semibold transition-all cursor-pointer flex items-center gap-1.5 ${
                showNoPath
                  ? "bg-slate-500/25 text-slate-200 border-slate-400/50 shadow-sm"
                  : "bg-bg-card hover:bg-bg-subtle text-gray-400 border-border"
              }`}
            >
              <span>{showNoPath ? "Hide no-path findings" : "Show no-path findings"}</span>
              <span className="px-1.5 py-0.2 rounded-full text-[10px] bg-black/30 font-mono">
                {counts.nopath}
              </span>
            </button>
          )}

          {/* View Mode Toggle (Grouped vs Flat) */}
          <div className="flex items-center bg-bg-card p-1 rounded-lg border border-border text-xs">
            <button
              type="button"
              onClick={() => setViewMode("grouped")}
              className={`px-3 py-1 rounded font-medium transition-colors cursor-pointer ${
                viewMode === "grouped"
                  ? "bg-accent text-white shadow-sm font-semibold"
                  : "text-gray-400 hover:text-gray-200"
              }`}
            >
              Grouped by Package
            </button>
            <button
              type="button"
              onClick={() => setViewMode("flat")}
              className={`px-3 py-1 rounded font-medium transition-colors cursor-pointer ${
                viewMode === "flat"
                  ? "bg-accent text-white shadow-sm font-semibold"
                  : "text-gray-400 hover:text-gray-200"
              }`}
            >
              Flat List
            </button>
          </div>

          {/* Verdict Filter Dropdown */}
          <div className="flex items-center gap-1.5 text-xs text-gray-400">
            <span>Verdict:</span>
            <select
              value={verdictFilter}
              onChange={(e) => updateParam("verdict", e.target.value)}
              className="bg-bg-card border border-border rounded-lg px-2.5 py-1.5 text-xs text-white focus:outline-none focus:ring-1 focus:ring-accent cursor-pointer"
            >
              <option value="all">All Verdicts</option>
              <option value="reachable_in_model">Reachable in Model</option>
              <option value="unknown">Unknown</option>
              <option value="no_path_found">No Path Found</option>
            </select>
          </div>

          {/* Status Filter */}
          <div className="flex items-center gap-1.5 text-xs text-gray-400">
            <span>Status:</span>
            <select
              value={statusFilter}
              onChange={(e) => updateParam("status", e.target.value)}
              className="bg-bg-card border border-border rounded-lg px-2.5 py-1.5 text-xs text-white focus:outline-none focus:ring-1 focus:ring-accent cursor-pointer"
            >
              <option value="all">All Statuses</option>
              <option value="open">Open</option>
              <option value="risk_accepted">Risk Accepted</option>
              <option value="fixed">Fixed</option>
              <option value="fix_planned">Fix Planned</option>
              <option value="false_positive">False Positive</option>
            </select>
          </div>

          {/* Sort By */}
          <div className="flex items-center gap-1.5 text-xs text-gray-400">
            <span>Sort:</span>
            <select
              value={sortBy}
              onChange={(e) => updateParam("sort", e.target.value)}
              className="bg-bg-card border border-border rounded-lg px-2.5 py-1.5 text-xs text-white focus:outline-none focus:ring-1 focus:ring-accent cursor-pointer"
            >
              <option value="score">Score (Default)</option>
              <option value="severity">Severity</option>
            </select>
          </div>
        </div>
      </div>

      {/* ════════════════════════════════════════════════════════════════
          FINDINGS DATA TABLE (GROUPED OR FLAT)
          ════════════════════════════════════════════════════════════════ */}
      <div className="bg-bg-surface border border-border rounded-xl shadow-lg overflow-hidden">
        {isLoading && (
          <div className="p-12 text-center text-gray-400 font-mono text-sm flex items-center justify-center gap-3">
            <svg
              className="animate-spin h-5 w-5 text-accent"
              viewBox="0 0 24 24"
              fill="none"
            >
              <circle
                className="opacity-25"
                cx="12"
                cy="12"
                r="10"
                stroke="currentColor"
                strokeWidth="4"
              />
              <path
                className="opacity-75"
                fill="currentColor"
                d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"
              />
            </svg>
            <span>Loading findings from FalkorDB...</span>
          </div>
        )}

        {isError && (
          <div className="p-6 text-center text-red-400 text-xs">
            <p className="font-bold mb-1">Failed to load findings</p>
            <p className="text-gray-400 mb-3">
              {error instanceof Error ? error.message : "Error"}
            </p>
            <button
              onClick={() => refetch()}
              className="px-3 py-1.5 bg-bg-card border border-red-500/40 rounded text-white text-xs hover:bg-bg-subtle cursor-pointer"
            >
              Retry
            </button>
          </div>
        )}

        {/* Empty State */}
        {!isLoading && !isError && displayedFindings.length === 0 && (
          <div className="p-12 text-center max-w-xl mx-auto space-y-3">
            <div className="w-12 h-12 rounded-full bg-emerald-500/10 border border-emerald-500/20 text-emerald-400 mx-auto flex items-center justify-center">
              <svg
                className="w-6 h-6"
                viewBox="0 0 24 24"
                fill="none"
                stroke="currentColor"
                strokeWidth="2"
              >
                <path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z" />
                <path d="m9 12 2 2 4-4" />
              </svg>
            </div>
            <h3 className="text-base font-bold text-white">
              No Findings Matching Filter
            </h3>
            <p className="text-xs text-gray-400 leading-relaxed">
              No vulnerabilities matching your active filters were found in this repository.
              {!showNoPath && counts.nopath > 0 && (
                <span className="block mt-1 text-gray-300">
                  {counts.nopath} no-path findings are hidden by default. Click &quot;Show no-path findings&quot; to inspect them.
                </span>
              )}
            </p>
            {(!lockfileKind || lockfileKind === "none") && (
              <p className="text-xs text-amber-400/90 font-mono">
                No dependency file found; add requirements.txt or poetry.lock
              </p>
            )}
          </div>
        )}

        {/* ── 1. GROUPED VIEW (DEFAULT) ────────────────────────────────── */}
        {!isLoading && !isError && displayedFindings.length > 0 && viewMode === "grouped" && (
          <div className="overflow-x-auto">
            <table className="w-full text-left text-xs border-collapse">
              <thead>
                <tr className="border-b border-border bg-bg-card/70 text-gray-400 font-semibold uppercase tracking-wider text-[11px]">
                  <th className="py-3 px-4 w-10"></th>
                  <th className="py-3 px-4">Package</th>
                  <th className="py-3 px-4 w-32">Findings</th>
                  <th className="py-3 px-4 w-32">Worst Severity</th>
                  <th className="py-3 px-4 w-44">Best Verdict</th>
                  <th className="py-3 px-4 w-32 text-right">Highest Score</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-border/60">
                {groupedFindings.map((group) => {
                  const isExpanded = expandedKeys.has(group.packageKey);
                  const scoreColors = getScoreColor(group.highestScore);

                  return (
                    <React.Fragment key={group.packageKey}>
                      {/* Parent Group Row */}
                      <tr
                        onClick={() => toggleExpand(group.packageKey)}
                        className={`hover:bg-bg-card/60 transition-colors cursor-pointer select-none ${
                          isExpanded ? "bg-bg-card/40" : ""
                        }`}
                      >
                        {/* Expand/Collapse Chevron */}
                        <td className="py-3 px-4 text-gray-400">
                          <svg
                            className={`w-4 h-4 transition-transform ${isExpanded ? "rotate-90 text-accent" : ""}`}
                            viewBox="0 0 24 24"
                            fill="none"
                            stroke="currentColor"
                            strokeWidth="2"
                          >
                            <polyline points="9 18 15 12 9 6" />
                          </svg>
                        </td>

                        {/* Package @ Version */}
                        <td className="py-3 px-4 font-mono font-semibold text-white">
                          <span>{group.packageName}</span>
                          <span className="text-accent ml-1 font-normal text-[11px]">
                            @{group.packageVersion}
                          </span>
                        </td>

                        {/* Count of findings */}
                        <td className="py-3 px-4">
                          <span className="px-2.5 py-0.5 rounded-full text-xs font-mono font-semibold bg-bg-card border border-border text-gray-200">
                            {group.count} {group.count === 1 ? "finding" : "findings"}
                          </span>
                        </td>

                        {/* Worst Severity (Unrated when UNKNOWN) */}
                        <td className="py-3 px-4">
                          {getGroupWorstSeverityBadge(group.worstSeverity)}
                        </td>

                        {/* Best Verdict */}
                        <td className="py-3 px-4">
                          <VerdictBadge verdict={group.bestVerdict} />
                        </td>

                        {/* Highest Score */}
                        <td className="py-3 px-4 text-right">
                          <div className="flex items-center justify-end gap-2">
                            <span className="font-mono font-bold text-sm text-white w-7">
                              {group.highestScore}
                            </span>
                            <div className="w-12 h-1.5 bg-bg-card rounded-full overflow-hidden border border-border/80">
                              <div
                                className={`h-full rounded-full ${scoreColors.split(" ")[0]}`}
                                style={{ width: `${Math.min(100, group.highestScore)}%` }}
                              />
                            </div>
                          </div>
                        </td>
                      </tr>

                      {/* Nested Individual Findings Rows when Expanded */}
                      {isExpanded && (
                        <tr>
                          <td colSpan={6} className="bg-bg-card/25 p-0">
                            <div className="p-3 sm:p-4 space-y-2 border-y border-border/70">
                              <div className="text-[11px] font-semibold uppercase tracking-wider text-gray-400 font-mono px-1">
                                Individual Findings for {group.packageKey} ({group.findings.length})
                              </div>
                              <div className="space-y-2">
                                {group.findings.map((f) => {
                                  const isRiskAccepted = f.status === "risk_accepted";
                                  const fScoreColors = getScoreColor(f.score);

                                  return (
                                    <div
                                      key={f.id}
                                      onClick={() =>
                                        navigate(`/repos/${repoId}/findings/${f.id}`)
                                      }
                                      className={`p-3 rounded-lg border transition-colors flex flex-col sm:flex-row sm:items-center justify-between gap-3 cursor-pointer ${
                                        isRiskAccepted
                                          ? "bg-purple-950/15 border-purple-500/30"
                                          : "bg-bg-surface border-border hover:border-gray-500"
                                      }`}
                                    >
                                      <div className="space-y-1 min-w-0 flex-1">
                                        <div className="flex items-center gap-2 flex-wrap">
                                          <a
                                            href={`https://osv.dev/vulnerability/${f.vuln_id}`}
                                            target="_blank"
                                            rel="noreferrer"
                                            onClick={(e) => e.stopPropagation()}
                                            className="font-mono font-bold text-xs text-accent hover:underline inline-flex items-center gap-1"
                                          >
                                            <span>{f.vuln_id}</span>
                                            <svg
                                              className="w-3 h-3 opacity-60"
                                              viewBox="0 0 24 24"
                                              fill="none"
                                              stroke="currentColor"
                                              strokeWidth="2"
                                            >
                                              <path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6" />
                                              <polyline points="15 3 21 3 21 9" />
                                              <line x1="10" y1="14" x2="21" y2="3" />
                                            </svg>
                                          </a>
                                          {getSeverityBadge(f.severity)}
                                          <VerdictBadge verdict={f.verdict} />
                                          {getStatusBadge(f.status)}
                                        </div>
                                        {f.summary && (
                                          <p className="text-xs text-gray-300 line-clamp-1">
                                            {f.summary}
                                          </p>
                                        )}
                                      </div>

                                      <div className="flex items-center gap-3 shrink-0 self-end sm:self-center">
                                        <div className="flex items-center gap-2">
                                          <span className="font-mono font-bold text-xs text-white">
                                            Score: {f.score}
                                          </span>
                                          <div className="w-10 h-1.5 bg-bg-card rounded-full overflow-hidden border border-border/80">
                                            <div
                                              className={`h-full rounded-full ${fScoreColors.split(" ")[0]}`}
                                              style={{ width: `${Math.min(100, f.score)}%` }}
                                            />
                                          </div>
                                        </div>

                                        <span className="text-xs text-accent hover:underline font-medium">
                                          View details →
                                        </span>
                                      </div>
                                    </div>
                                  );
                                })}
                              </div>
                            </div>
                          </td>
                        </tr>
                      )}
                    </React.Fragment>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}

        {/* ── 2. FLAT LIST VIEW ────────────────────────────────────────── */}
        {!isLoading && !isError && displayedFindings.length > 0 && viewMode === "flat" && (
          <div className="overflow-x-auto">
            <table className="w-full text-left text-xs border-collapse">
              <thead>
                <tr className="border-b border-border bg-bg-card/70 text-gray-400 font-semibold uppercase tracking-wider text-[11px]">
                  <th className="py-3 px-4 w-28">Score</th>
                  <th className="py-3 px-4 w-44">Verdict</th>
                  <th className="py-3 px-4 w-24">Severity</th>
                  <th className="py-3 px-4 w-40">Package</th>
                  <th className="py-3 px-4 w-44">Vulnerability ID</th>
                  <th className="py-3 px-4">Owner(s)</th>
                  <th className="py-3 px-4 w-32 text-right">Status</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-border/60">
                {displayedFindings.map((f) => {
                  const isRiskAccepted = f.status === "risk_accepted";
                  const scoreColors = getScoreColor(f.score);

                  return (
                    <tr
                      key={f.id}
                      onClick={() =>
                        navigate(`/repos/${repoId}/findings/${f.id}`)
                      }
                      className={`hover:bg-bg-card/60 transition-colors cursor-pointer group ${
                        isRiskAccepted ? "bg-purple-950/10 opacity-85" : ""
                      }`}
                    >
                      {/* Score with visual progress bar */}
                      <td className="py-3 px-4">
                        <div className="flex items-center gap-2">
                          <span className="font-mono font-bold text-sm text-white w-7">
                            {f.score}
                          </span>
                          <div className="w-12 h-1.5 bg-bg-card rounded-full overflow-hidden border border-border/80">
                            <div
                              className={`h-full rounded-full ${scoreColors.split(" ")[0]}`}
                              style={{ width: `${Math.min(100, f.score)}%` }}
                            />
                          </div>
                        </div>
                      </td>

                      {/* Verdict Badge */}
                      <td className="py-3 px-4">
                        <VerdictBadge verdict={f.verdict} />
                      </td>

                      {/* Severity */}
                      <td className="py-3 px-4">
                        {getSeverityBadge(f.severity)}
                      </td>

                      {/* Package @ Version */}
                      <td className="py-3 px-4 font-mono">
                        <span className="text-white font-semibold">
                          {f.package}
                        </span>
                        <span className="text-gray-400 text-[11px]">
                          @{f.version || "*"}
                        </span>
                      </td>

                      {/* Vulnerability ID */}
                      <td className="py-3 px-4">
                        <a
                          href={`https://osv.dev/vulnerability/${f.vuln_id}`}
                          target="_blank"
                          rel="noreferrer"
                          onClick={(e) => e.stopPropagation()}
                          className="font-mono text-accent hover:underline inline-flex items-center gap-1 group/link"
                          title="Open advisory on OSV.dev"
                        >
                          <span>{f.vuln_id}</span>
                          <svg
                            className="w-3 h-3 opacity-60 group-hover/link:opacity-100"
                            viewBox="0 0 24 24"
                            fill="none"
                            stroke="currentColor"
                            strokeWidth="2"
                          >
                            <path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6" />
                            <polyline points="15 3 21 3 21 9" />
                            <line x1="10" y1="14" x2="21" y2="3" />
                          </svg>
                        </a>
                      </td>

                      {/* Owner(s) */}
                      <td className="py-3 px-4">
                        {f.owners && f.owners.length > 0 ? (
                          <div className="flex flex-wrap gap-1">
                            {Array.from(new Set(f.owners)).map((owner) => (
                              <span
                                key={owner}
                                className="px-1.5 py-0.5 rounded bg-bg-card border border-border text-[10px] text-gray-300 font-mono"
                              >
                                {owner}
                              </span>
                            ))}
                          </div>
                        ) : (
                          <span className="text-gray-500 text-[11px] italic">
                            Unassigned
                          </span>
                        )}
                      </td>

                      {/* Status Chip */}
                      <td className="py-3 px-4 text-right">
                        <div className="flex flex-col items-end gap-1">
                          {getStatusBadge(f.status)}
                          {isRiskAccepted && (
                            <span
                              className="text-[10px] text-purple-300 font-mono truncate max-w-[140px]"
                              title={`Risk accepted by ${f.risk_accepted_by || "analyst"}`}
                            >
                              Risk accepted by {f.risk_accepted_by || "analyst"}
                            </span>
                          )}
                        </div>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* Score computation explanation modal */}
      <ScoreComputationModal
        isOpen={isScoreModalOpen}
        onClose={() => setIsScoreModalOpen(false)}
      />
    </div>
  );
};

export default FindingsDashboard;
