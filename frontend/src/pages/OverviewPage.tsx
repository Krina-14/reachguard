import React from "react";
import { Link } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { apiFetch } from "../api/client";
import type {
  FindingDetail,
  FindingRow,
  MemoryResponse,
  Repo,
  Severity,
} from "../api/types";
import { useDocumentTitle } from "../lib/useDocumentTitle";

function formatRepoName(source?: string | null): string {
  if (!source) return "Untitled Repository";
  try {
    if (source.startsWith("http://") || source.startsWith("https://")) {
      const url = new URL(source);
      const parts = url.pathname.replace(/^\/|\/$/g, "").split("/");
      if (parts.length >= 2) {
        return `${parts[parts.length - 2]}/${parts[parts.length - 1]}`;
      }
      return url.pathname.replace(/^\//, "");
    }
  } catch {
    // Return raw source if URL parsing fails
  }
  return source;
}

function formatDate(dateStr?: string | null): string {
  if (!dateStr) return "Recently";
  try {
    const d = new Date(dateStr);
    if (isNaN(d.getTime())) return "Recently";
    return new Intl.DateTimeFormat("en-US", {
      month: "short",
      day: "numeric",
      year: "numeric",
      hour: "2-digit",
      minute: "2-digit",
    }).format(d);
  } catch {
    return "Recently";
  }
}

/** Severity badge helper, mapping UNKNOWN to 'Unrated' per prompt requirements */
const SeverityBadge: React.FC<{ severity: Severity }> = ({ severity }) => {
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
        <span className="px-2 py-0.5 rounded text-[10px] font-medium bg-slate-500/20 text-slate-300 border border-slate-500/35 uppercase">
          Unrated
        </span>
      );
  }
};

/** Individual reachable finding item fetching trace details */
const ReachableFindingItem: React.FC<{
  repoId: string;
  finding: FindingRow;
}> = ({ repoId, finding }) => {
  const { data: detail, isLoading } = useQuery<FindingDetail>({
    queryKey: ["finding-detail-overview", repoId, finding.id],
    queryFn: () =>
      apiFetch<FindingDetail>(`/api/repos/${repoId}/findings/${finding.id}`),
    staleTime: 30000,
  });

  const steps =
    detail?.trace?.paths?.[0]?.edges?.length ||
    (detail?.trace?.paths?.[0]?.nodes?.length
      ? Math.max(1, detail.trace.paths[0].nodes.length - 1)
      : null);

  const plainSentence = isLoading
    ? "Analyzing reachability path..."
    : steps
    ? `A public route can reach this library through ${steps} ${
        steps === 1 ? "step" : "steps"
      }`
    : "A public route can reach this library in the model";

  const ownersText =
    finding.owners && finding.owners.length > 0
      ? finding.owners.join(", ")
      : "No owner assigned";

  return (
    <div className="p-4 rounded-lg bg-bg-card/70 border border-border/80 flex flex-col md:flex-row md:items-center justify-between gap-4">
      <div className="space-y-1.5 min-w-0">
        <div className="flex flex-wrap items-center gap-2.5">
          <span className="font-mono font-semibold text-white text-sm">
            {finding.package}@{finding.version}
          </span>
          <SeverityBadge severity={finding.severity} />
          <span className="text-xs text-gray-400 font-mono">
            {finding.vuln_id}
          </span>
        </div>

        <p className="text-xs text-gray-300 font-medium">
          {plainSentence}
        </p>

        <div className="flex items-center gap-2 text-[11px] text-gray-400">
          <span className="text-gray-500">Owners:</span>
          <span className="text-gray-300 truncate">{ownersText}</span>
        </div>
      </div>

      <div className="flex items-center self-start md:self-center flex-shrink-0">
        <Link
          to={`/repos/${repoId}/findings/${finding.id}`}
          className="text-xs font-semibold text-accent hover:text-accent-hover transition-colors inline-flex items-center gap-1 px-3 py-1.5 rounded-lg bg-accent/10 border border-accent/25 hover:border-accent/40"
        >
          <span>View proof path</span>
          <span aria-hidden="true">→</span>
        </Link>
      </div>
    </div>
  );
};

/** Ready repository overview card */
const ReadyRepoCard: React.FC<{ repo: Repo }> = ({ repo }) => {
  const repoName = formatRepoName(repo.source);
  const hasZeroPublicEntrypoints =
    (repo.stats?.public_entrypoints ?? 0) === 0 ||
    Boolean(repo.stats?.no_entrypoints);

  // Fetch findings (up to 500)
  const { data: findings = [], isLoading: isFindingsLoading } = useQuery<
    FindingRow[]
  >({
    queryKey: ["repo-findings-overview", repo.id],
    queryFn: () =>
      apiFetch<FindingRow[]>(`/api/repos/${repo.id}/findings?limit=500`),
    staleTime: 30000,
  });

  // Fetch memory
  const { data: memoryData, isLoading: isMemoryLoading } =
    useQuery<MemoryResponse>({
      queryKey: ["repo-memory-overview", repo.id],
      queryFn: () =>
        apiFetch<MemoryResponse>(`/api/repos/${repo.id}/memory`),
      staleTime: 30000,
    });

  // Big counters computed from rows
  const reachableCount = findings.filter(
    (f) => f.verdict === "reachable_in_model"
  ).length;
  const unknownCount = findings.filter((f) => f.verdict === "unknown").length;
  const noPathCount = findings.filter(
    (f) => f.verdict === "no_path_found"
  ).length;

  // Top 3 findings by score where verdict is reachable_in_model
  const topReachableFindings = findings
    .filter((f) => f.verdict === "reachable_in_model")
    .sort((a, b) => b.score - a.score)
    .slice(0, 3);

  // Decisions list capped at max 10 rows
  const decisions = (memoryData?.decisions || []).slice(0, 10);

  return (
    <div className="bg-bg-surface border border-border rounded-xl p-6 shadow-xl space-y-6">
      {/* Header: Repo Name and Deep Link */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 pb-4 border-b border-border/80">
        <div>
          <div className="flex items-center gap-3">
            <h2 className="text-xl font-bold text-white tracking-tight">
              {repoName}
            </h2>
            <span className="px-2 py-0.5 rounded-full text-[10px] font-semibold bg-emerald-500/15 text-emerald-400 border border-emerald-500/30">
              Ready
            </span>
          </div>
          <p className="text-xs text-gray-400 mt-1 font-mono truncate">
            {repo.source}
          </p>
        </div>

        <Link
          to={`/repos/${repo.id}`}
          className="text-xs text-gray-400 hover:text-white transition-colors inline-flex items-center gap-1 self-start sm:self-center"
        >
          <span>View repository</span>
          <span aria-hidden="true">→</span>
        </Link>
      </div>

      {/* Notice when zero public entrypoints detected */}
      {hasZeroPublicEntrypoints && (
        <div
          role="note"
          className="p-3.5 rounded-lg bg-amber-500/10 border border-amber-500/30 text-amber-300 text-xs flex items-center gap-2.5"
        >
          <svg
            className="w-4 h-4 flex-shrink-0"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            strokeWidth="2"
            strokeLinecap="round"
            strokeLinejoin="round"
          >
            <circle cx="12" cy="12" r="10" />
            <line x1="12" y1="8" x2="12" y2="12" />
            <line x1="12" y1="16" x2="12.01" y2="16" />
          </svg>
          <span className="leading-relaxed">
            No web routes were detected, so reachability can't be judged for this
            repository.
          </span>
        </div>
      )}

      {/* Three Big Counters */}
      <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
        {/* Reachable in model */}
        <div className="bg-red-500/10 border border-red-500/25 rounded-xl p-4 flex items-center justify-between">
          <div>
            <span className="text-xs font-semibold text-red-300 uppercase tracking-wider block">
              Reachable in model
            </span>
            <span className="text-3xl font-extrabold font-mono text-red-400 mt-1 block">
              {isFindingsLoading ? "..." : reachableCount}
            </span>
          </div>
          <div className="w-10 h-10 rounded-lg bg-red-500/15 border border-red-500/30 text-red-400 flex items-center justify-center flex-shrink-0">
            <svg
              className="w-5 h-5"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth="2"
              strokeLinecap="round"
              strokeLinejoin="round"
            >
              <line x1="6" y1="3" x2="6" y2="15" />
              <circle cx="18" cy="6" r="3" />
              <circle cx="6" cy="18" r="3" />
              <path d="M18 9a9 9 0 0 1-9 9" />
            </svg>
          </div>
        </div>

        {/* Unknown */}
        <div className="bg-amber-500/10 border border-amber-500/25 rounded-xl p-4 flex items-center justify-between">
          <div>
            <span className="text-xs font-semibold text-amber-300 uppercase tracking-wider block">
              Unknown
            </span>
            <span className="text-3xl font-extrabold font-mono text-amber-400 mt-1 block">
              {isFindingsLoading ? "..." : unknownCount}
            </span>
          </div>
          <div className="w-10 h-10 rounded-lg bg-amber-500/15 border border-amber-500/30 text-amber-400 flex items-center justify-center flex-shrink-0">
            <svg
              className="w-5 h-5"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth="2"
              strokeLinecap="round"
              strokeLinejoin="round"
            >
              <circle cx="12" cy="12" r="10" />
              <path d="M9.09 9a3 3 0 0 1 5.83 1c0 2-3 3-3 3" />
              <line x1="12" y1="17" x2="12.01" y2="17" />
            </svg>
          </div>
        </div>

        {/* No path found */}
        <div className="bg-slate-500/10 border border-slate-500/25 rounded-xl p-4 flex items-center justify-between">
          <div>
            <span className="text-xs font-semibold text-slate-300 uppercase tracking-wider block">
              No path found
            </span>
            <span className="text-3xl font-extrabold font-mono text-slate-300 mt-1 block">
              {isFindingsLoading ? "..." : noPathCount}
            </span>
          </div>
          <div className="w-10 h-10 rounded-lg bg-slate-500/15 border border-slate-500/30 text-slate-400 flex items-center justify-center flex-shrink-0">
            <svg
              className="w-5 h-5"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth="2"
              strokeLinecap="round"
              strokeLinejoin="round"
            >
              <circle cx="12" cy="12" r="10" />
              <line x1="8" y1="12" x2="16" y2="12" />
            </svg>
          </div>
        </div>
      </div>

      {/* Top 3 Reachable Findings */}
      <div className="space-y-3 pt-2">
        <div className="flex items-center justify-between">
          <h3 className="text-sm font-semibold text-white uppercase tracking-wider">
            Top Reachable Findings (by Score)
          </h3>
          <span className="text-xs text-gray-500">
            {topReachableFindings.length} of {reachableCount} reachable
          </span>
        </div>

        {isFindingsLoading ? (
          <div className="space-y-2">
            {[1, 2].map((i) => (
              <div
                key={i}
                className="h-16 bg-bg-card/40 rounded-lg animate-pulse border border-border/50"
              />
            ))}
          </div>
        ) : topReachableFindings.length === 0 ? (
          <div className="p-4 rounded-lg bg-bg-card/40 border border-border/60 text-center text-xs text-gray-400">
            No reachable findings detected in this repository.
          </div>
        ) : (
          <div className="space-y-2.5">
            {topReachableFindings.map((finding) => (
              <ReachableFindingItem
                key={finding.id}
                repoId={repo.id}
                finding={finding}
              />
            ))}
          </div>
        )}
      </div>

      {/* Decisions Recorded List from Memory */}
      <div className="space-y-3 pt-4 border-t border-border/70">
        <div className="flex items-center justify-between">
          <h3 className="text-sm font-semibold text-white uppercase tracking-wider">
            Decisions recorded
          </h3>
          <span className="text-xs text-gray-500">
            {decisions.length} recorded
          </span>
        </div>

        {isMemoryLoading ? (
          <div className="h-12 bg-bg-card/40 rounded-lg animate-pulse border border-border/50" />
        ) : decisions.length === 0 ? (
          <div className="p-4 rounded-lg bg-bg-card/40 border border-border/60 text-center text-xs text-gray-400">
            No decisions recorded for this repository.
          </div>
        ) : (
          <div className="space-y-2">
            {decisions.map((dec) => {
              const isApprovedAcceptRisk =
                dec.type === "accept_risk" && dec.status === "approved";

              return (
                <div
                  key={dec.id}
                  className={`p-3.5 rounded-lg border text-xs space-y-1.5 ${
                    isApprovedAcceptRisk
                      ? "bg-emerald-500/5 border-emerald-500/30"
                      : "bg-bg-card/50 border-border/70"
                  }`}
                >
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <div className="flex items-center gap-2">
                      <span
                        className={`text-[10px] font-bold uppercase tracking-wider px-2 py-0.5 rounded-full ${
                          dec.status === "approved"
                            ? "bg-emerald-500/15 text-emerald-400 border border-emerald-500/30"
                            : dec.status === "pending"
                            ? "bg-amber-500/15 text-amber-400 border border-amber-500/30"
                            : "bg-red-500/15 text-red-400 border border-red-500/30"
                        }`}
                      >
                        {dec.type === "accept_risk"
                          ? "Risk Accepted"
                          : dec.type.replace(/_/g, " ")}
                      </span>

                      {dec.status === "approved" && (
                        <span className="text-[10px] text-emerald-400 font-medium">
                          (Approved)
                        </span>
                      )}
                    </div>

                    <span className="text-[11px] text-gray-500 font-mono">
                      {formatDate(dec.created_at)}
                    </span>
                  </div>

                  <div className="text-gray-300 leading-relaxed">
                    <span className="text-gray-400 font-medium">
                      {isApprovedAcceptRisk ? "Approved for:" : "Reason:"}{" "}
                    </span>
                    <span>"{dec.reason}"</span>
                  </div>

                  <div className="flex flex-wrap items-center gap-4 text-[11px] text-gray-400 pt-0.5">
                    <div>
                      <span className="text-gray-500">Recorded by: </span>
                      <span className="text-gray-300 font-mono">{dec.by}</span>
                    </div>

                    {dec.approved_by && (
                      <div>
                        <span className="text-gray-500">Approved by: </span>
                        <span className="text-emerald-300 font-mono">
                          {dec.approved_by}
                        </span>
                      </div>
                    )}

                    {dec.finding_id && (
                      <Link
                        to={`/repos/${repo.id}/findings/${dec.finding_id}`}
                        className="text-accent hover:underline font-mono"
                      >
                        Finding #{dec.finding_id} →
                      </Link>
                    )}
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </div>
    </div>
  );
};

export const OverviewPage: React.FC = () => {
  useDocumentTitle("Overview");

  // Fetch all repos
  const {
    data: repos = [],
    isLoading,
    isError,
  } = useQuery<Repo[]>({
    queryKey: ["repos"],
    queryFn: () => apiFetch<Repo[]>("/api/repos"),
  });

  const readyRepos = repos.filter((r) => r.status === "ready");

  return (
    <div className="p-6 md:p-8 space-y-6">
      {/* Top Header */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 pb-4 border-b border-border">
        <div>
          <h1 className="text-2xl md:text-3xl font-bold tracking-tight text-white">
            Overview
          </h1>
          <p className="text-sm text-gray-400 mt-1">
            Reachability posture, active vulnerability counters, and recorded
            decisions
          </p>
        </div>
      </div>

      {/* Loading Skeletons */}
      {isLoading && (
        <div className="space-y-6">
          {[1, 2].map((i) => (
            <div
              key={i}
              className="bg-bg-surface border border-border rounded-xl p-6 animate-pulse space-y-4"
            >
              <div className="h-6 bg-bg-card rounded w-1/3" />
              <div className="grid grid-cols-3 gap-4">
                <div className="h-20 bg-bg-card rounded" />
                <div className="h-20 bg-bg-card rounded" />
                <div className="h-20 bg-bg-card rounded" />
              </div>
            </div>
          ))}
        </div>
      )}

      {/* Query Error State */}
      {isError && (
        <div className="p-5 rounded-xl bg-red-500/10 border border-red-500/30 text-red-400">
          <h2 className="text-sm font-bold text-red-300">
            Failed to fetch repositories
          </h2>
          <p className="text-xs text-red-400/80 mt-1">
            Unable to connect to ReachGuard backend API.
          </p>
        </div>
      )}

      {/* Empty State when no repos or no ready repos */}
      {!isLoading && !isError && readyRepos.length === 0 && (
        <div className="rounded-xl border border-border bg-bg-surface p-12 text-center shadow-xl">
          <div className="w-14 h-14 mx-auto mb-4 rounded-xl bg-accent/15 border border-accent/30 flex items-center justify-center text-accent">
            <svg
              className="w-7 h-7"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth="2"
              strokeLinecap="round"
              strokeLinejoin="round"
            >
              <path d="M4 19.5v-15A2.5 2.5 0 0 1 6.5 2H20v20H6.5a2.5 2.5 0 0 1-2.5-2.5Z" />
              <path d="M6 6h10" />
              <path d="M6 10h10" />
            </svg>
          </div>
          <h2 className="text-xl font-semibold text-white mb-2">
            No analyzed repositories
          </h2>
          <p className="text-sm text-gray-400 max-w-md mx-auto">
            Repositories will appear here once ingested and analyzed for
            reachability.
          </p>
        </div>
      )}

      {/* Ready Repos Cards List */}
      {!isLoading && !isError && readyRepos.length > 0 && (
        <div className="space-y-6">
          {readyRepos.map((repo) => (
            <ReadyRepoCard key={repo.id} repo={repo} />
          ))}
        </div>
      )}

      {/* Footer limits notice line */}
      <div className="pt-4 border-t border-border/60 text-center">
        <p className="text-xs text-gray-500 leading-relaxed max-w-3xl mx-auto">
          <span className="text-gray-400 font-medium">Notice:</span> Python
          only. Module-level analysis. Heuristic auth detection. Results show
          reachability in the analyzed model, not proof of exploitability.
        </p>
      </div>
    </div>
  );
};

export default OverviewPage;
