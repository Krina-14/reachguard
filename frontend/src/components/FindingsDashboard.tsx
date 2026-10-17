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
  ChokePoint,
} from "../api/types";

interface FindingsDashboardProps {
  repoId: string;
  lockfileKind?: string;
}

export const FindingsDashboard: React.FC<FindingsDashboardProps> = ({
  repoId,
  lockfileKind,
}) => {
  const navigate = useNavigate();
  const [searchParams, setSearchParams] = useSearchParams();

  // Read filter values directly from URL search params
  const verdictFilter = searchParams.get("verdict") || "all";
  const statusFilter = searchParams.get("status") || "all";
  const searchQuery = searchParams.get("q") || "";
  const sortBy = (searchParams.get("sort") as "score" | "severity") || "score";

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

  // Modal state
  const [isScoreModalOpen, setIsScoreModalOpen] = useState<boolean>(false);

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
    data: findings = [],
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

  // Calculate top strip verdict counters from all rows in the repository
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

  return (
    <div className="space-y-6">
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
              No Path Found in Model
            </span>
            <span className="text-2xl font-bold font-mono text-white">
              {counts.nopath}
            </span>
          </div>
          <p className="text-[11px] text-gray-400 mt-1">
            No execution flow found in model (Not proof of safety)
          </p>
        </div>

      </div>

      {/* ════════════════════════════════════════════════════════════════
          ALWAYS VISIBLE LEGEND & SCORE INFO CARD
          ════════════════════════════════════════════════════════════════ */}
      <div className="bg-bg-surface border border-border rounded-xl p-4 md:p-5 shadow-md">
        <div className="flex flex-col md:flex-row md:items-center justify-between gap-4">
          <div className="space-y-2">
            <div className="flex items-center gap-2">
              <h3 className="text-xs font-bold uppercase tracking-wider text-gray-300">
                Reachability Verdict Legend
              </h3>
              <span className="text-gray-600">|</span>
              <span className="text-xs text-amber-400/90 font-medium">
                "No path found" is not proof of safety.
              </span>
            </div>

            <div className="flex flex-wrap items-center gap-4 text-xs text-gray-400">
              <div className="flex items-center gap-1.5">
                <span className="w-2.5 h-2.5 rounded-full bg-red-500" />
                <span className="text-white font-medium">Reachable</span>: Entrypoint
                leads directly to package AST call.
              </div>
              <div className="flex items-center gap-1.5">
                <span className="w-2.5 h-2.5 rounded-full bg-amber-500" />
                <span className="text-white font-medium">Unknown</span>: Blind spots
                prevent complete static verification.
              </div>
              <div className="flex items-center gap-1.5">
                <span className="w-2.5 h-2.5 rounded-full bg-slate-400" />
                <span className="text-white font-medium">No path found</span>: No
                call chain in static graph.
              </div>
            </div>
          </div>

          <button
            type="button"
            onClick={() => setIsScoreModalOpen(true)}
            className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-bg-card hover:bg-bg-subtle border border-border text-xs text-accent hover:text-white transition-colors flex-shrink-0 cursor-pointer"
          >
            <svg
              className="w-3.5 h-3.5"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth="2"
            >
              <circle cx="12" cy="12" r="10" />
              <line x1="12" y1="16" x2="12" y2="12" />
              <line x1="12" y1="8" x2="12.01" y2="8" />
            </svg>
            <span>How is the score computed?</span>
          </button>
        </div>
      </div>

      {/* ════════════════════════════════════════════════════════════════
          CHOKE-POINTS CARD: UPGRADE RECOMMENDATIONS
          ════════════════════════════════════════════════════════════════ */}
      {chokePoints && chokePoints.length > 0 && (
        <div className="bg-bg-surface border border-accent/30 rounded-xl p-5 shadow-lg relative overflow-hidden">
          <div className="flex items-start gap-3 mb-4">
            <div className="w-8 h-8 rounded-lg bg-accent/15 border border-accent/30 text-accent flex items-center justify-center flex-shrink-0">
              <svg
                className="w-4 h-4"
                viewBox="0 0 24 24"
                fill="none"
                stroke="currentColor"
                strokeWidth="2"
              >
                <polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2" />
              </svg>
            </div>
            <div>
              <h3 className="text-sm font-bold text-white flex items-center gap-2">
                <span>Choke Points</span>
                <span className="text-[10px] uppercase font-mono px-2 py-0.2 rounded bg-accent/20 text-accent">
                  High Impact
                </span>
              </h3>
              <p className="text-xs text-gray-300 mt-0.5">
                Upgrade or remove these packages to clear the most reachable findings
              </p>
            </div>
          </div>

          <div className="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-3 lg:grid-cols-5 gap-3">
            {chokePoints.map((cp) => (
              <div
                key={`${cp.package}@${cp.version}`}
                onClick={() => updateParam("q", cp.package)}
                className="p-3 rounded-lg bg-bg-card hover:bg-bg-subtle border border-border hover:border-accent/40 transition-all cursor-pointer group"
                title={`Click to filter findings for ${cp.package}`}
              >
                <div className="flex items-center justify-between text-xs mb-1">
                  <span className="font-mono font-bold text-white group-hover:text-accent transition-colors truncate">
                    {cp.package}
                  </span>
                  <span className="text-[11px] text-gray-400 font-mono">
                    {cp.version || "*"}
                  </span>
                </div>
                <div className="flex items-center justify-between text-[11px] text-gray-400 mt-2 pt-2 border-t border-border/60">
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
          SEARCH & FILTER TOOLBAR
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

        {/* Filter select inputs */}
        <div className="flex items-center gap-3 w-full md:w-auto flex-wrap">
          {/* Verdict Filter */}
          <div className="flex items-center gap-1.5 text-xs text-gray-400">
            <span>Verdict:</span>
            <select
              value={verdictFilter}
              onChange={(e) => updateParam("verdict", e.target.value)}
              className="bg-bg-card border border-border rounded-lg px-2.5 py-1.5 text-xs text-white focus:outline-none focus:ring-1 focus:ring-accent"
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
              className="bg-bg-card border border-border rounded-lg px-2.5 py-1.5 text-xs text-white focus:outline-none focus:ring-1 focus:ring-accent"
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
              className="bg-bg-card border border-border rounded-lg px-2.5 py-1.5 text-xs text-white focus:outline-none focus:ring-1 focus:ring-accent"
            >
              <option value="score">Score (Default)</option>
              <option value="severity">Severity</option>
            </select>
          </div>
        </div>
      </div>


      {/* ════════════════════════════════════════════════════════════════
          FINDINGS DATA TABLE
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
              className="px-3 py-1.5 bg-bg-card border border-red-500/40 rounded text-white text-xs hover:bg-bg-subtle"
            >
              Retry
            </button>
          </div>
        )}

        {/* Empty State */}
        {!isLoading && !isError && findings.length === 0 && (
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
              No known vulnerabilities found for the pinned dependencies. This is
              data from OSV.dev, not proof of safety.
            </p>
            {(!lockfileKind || lockfileKind === "none") && (
              <p className="text-xs text-amber-400/90 font-mono">
                No dependency file found; add requirements.txt or poetry.lock
              </p>
            )}
          </div>
        )}

        {/* Table Content */}
        {!isLoading && !isError && findings.length > 0 && (
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
                {findings.map((f) => {
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

                      {/* Vulnerability ID (external link to OSV.dev) */}
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
                            {f.owners.map((owner) => (
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

                      {/* Status Chip & Risk Accepted By tag */}
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
