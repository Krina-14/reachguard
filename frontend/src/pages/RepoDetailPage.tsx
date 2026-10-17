import React, { useState } from "react";
import { useParams, Link, useNavigate } from "react-router-dom";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { apiFetch } from "../api/client";
import { useCan } from "../auth/useCan";
import { StatusChip } from "../components/StatusChip";
import { DeleteRepoModal } from "../components/DeleteRepoModal";
import { FindingsDashboard } from "../components/FindingsDashboard";
import { ChatPanel } from "../components/ChatPanel";
import type { Repo, RepoStatus } from "../api/types";
import { useDocumentTitle } from "../lib/useDocumentTitle";

// Pipeline stage definitions for stepper
interface StageDef {
  key: RepoStatus;
  title: string;
  description: string;
}

const PIPELINE_STAGES: StageDef[] = [
  {
    key: "queued",
    title: "Queued",
    description: "Scheduled for worker execution",
  },
  {
    key: "cloning",
    title: "Ingestion",
    description: "Cloning git repository or extracting zip archive",
  },
  {
    key: "parsing",
    title: "AST Parsing",
    description: "Extracting Python modules, call graphs & entrypoints",
  },
  {
    key: "scanning",
    title: "Vulnerability Scan",
    description: "Cross-referencing lockfile packages with OSV database",
  },
  {
    key: "ready",
    title: "Analysis Ready",
    description: "Call graph & reachability paths fully computed",
  },
];

export const RepoDetailPage: React.FC = () => {
  const { repoId } = useParams<{ repoId: string }>();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const { canManageUsers } = useCan();

  const [isDeleteOpen, setIsDeleteOpen] = useState(false);

  // Poll every 2.5 seconds while status is not in a terminal state ('ready' or 'failed')
  const {
    data: repo,
    isLoading,
    isError,
    error,
    refetch,
  } = useQuery<Repo>({
    queryKey: ["repo", repoId],
    queryFn: () => apiFetch<Repo>(`/api/repos/${repoId}`),
    enabled: Boolean(repoId),
    refetchInterval: (query) => {
      const data = query.state.data;
      if (!data) return false;
      return data.status !== "ready" && data.status !== "failed" ? 2500 : false;
    },
  });

  const getStageIndex = (status: RepoStatus): number => {
    switch (status) {
      case "queued":
        return 0;
      case "cloning":
        return 1;
      case "parsing":
        return 2;
      case "scanning":
        return 3;
      case "ready":
        return 4;
      case "failed":
        return -1; // Handled specially
      default:
        return 0;
    }
  };

  const formatRepoTitle = (source?: string | null) => {
    if (!source) return "Repository";
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
      // Fallback
    }
    return source;
  };

  const repoTitle = formatRepoTitle(repo?.source);
  useDocumentTitle(repo ? repoTitle : "Repository Detail");

  if (isLoading) {
    return (
      <div className="min-h-screen bg-bg p-6 md:p-8 space-y-6 max-w-7xl mx-auto animate-pulse">
        {/* Breadcrumb Skeleton */}
        <div className="h-4 bg-bg-card rounded w-48" />

        {/* Header Skeleton */}
        <div className="bg-bg-surface border border-border rounded-2xl p-6 md:p-8 space-y-4">
          <div className="flex flex-col md:flex-row md:items-center justify-between gap-4">
            <div className="space-y-2 flex-1">
              <div className="h-7 bg-bg-card rounded w-1/3" />
              <div className="h-4 bg-bg-card rounded w-1/2" />
            </div>
            <div className="flex gap-2">
              <div className="h-8 bg-bg-card rounded w-28" />
              <div className="h-8 bg-bg-card rounded w-24" />
            </div>
          </div>
        </div>

        {/* Pipeline Stepper Skeleton */}
        <div className="bg-bg-surface border border-border rounded-xl p-6 space-y-3">
          <div className="h-5 bg-bg-card rounded w-40" />
          <div className="grid grid-cols-2 md:grid-cols-4 gap-4 pt-2">
            {[1, 2, 3, 4].map((i) => (
              <div key={i} className="h-16 bg-bg-card rounded-lg" />
            ))}
          </div>
        </div>

        {/* Findings Dashboard Skeleton */}
        <div className="bg-bg-surface border border-border rounded-xl p-6 space-y-4">
          <div className="h-6 bg-bg-card rounded w-52" />
          <div className="space-y-3 pt-2">
            {[1, 2, 3].map((i) => (
              <div key={i} className="h-12 bg-bg-card rounded" />
            ))}
          </div>
        </div>
      </div>
    );
  }

  if (isError || !repo) {
    return (
      <div className="min-h-screen bg-bg p-8">
        <div className="max-w-4xl mx-auto">
          <div className="p-6 rounded-xl bg-red-500/10 border border-red-500/30 text-red-400">
            <h2 className="text-base font-bold text-red-300 mb-2">
              Repository Not Found
            </h2>
            <p className="text-xs text-red-400/90 mb-4">
              {error instanceof Error
                ? error.message
                : `Could not retrieve repository ${repoId}`}
            </p>
            <div className="flex items-center gap-3">
              <Link
                to="/"
                className="px-4 py-2 rounded-lg bg-bg-card border border-border text-xs text-white hover:bg-bg-subtle transition-colors"
              >
                ← Back to Repositories
              </Link>
              <button
                onClick={() => refetch()}
                className="px-4 py-2 rounded-lg bg-accent text-xs font-semibold text-white hover:bg-accent-hover transition-colors"
              >
                Retry
              </button>
            </div>
          </div>
        </div>
      </div>
    );
  }

  const isReady = repo.status === "ready";
  const isFailed = repo.status === "failed";
  const currentStageIdx = getStageIndex(repo.status);
  const stats = repo.stats;

  return (
    <div className="min-h-screen bg-bg text-gray-200 p-6 md:p-8">
      <div className="max-w-7xl mx-auto space-y-6">
        {/* Breadcrumb Navigation & Top Bar */}
        <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 pb-4 border-b border-border">
          <div>
            <div className="flex items-center gap-2 text-xs text-gray-400 mb-2">
              <Link to="/" className="hover:text-white transition-colors">
                Repositories
              </Link>
              <span>/</span>
              <span className="text-gray-300 font-mono truncate max-w-xs">
                {repo.id}
              </span>
            </div>

            <div className="flex items-center gap-3 flex-wrap">
              <h1 className="text-2xl md:text-3xl font-bold tracking-tight text-white">
                {formatRepoTitle(repo.source)}
              </h1>
              <StatusChip status={repo.status} stageDetail={repo.stage_detail} />
            </div>

            <p className="text-xs text-gray-500 font-mono mt-1 truncate">
              Source: {repo.source}
            </p>
          </div>

          <div className="flex items-center gap-3">
            <Link
              to={`/repos/${repo.id}/memory`}
              className="px-3.5 py-1.5 rounded-lg bg-bg-card border border-border text-xs text-gray-300 hover:text-white hover:bg-bg-subtle transition-colors flex items-center gap-1.5"
              title="View repository memory timeline"
            >
              <svg className="w-3.5 h-3.5 text-accent" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                <path d="M12 8v4l3 3" />
                <circle cx="12" cy="12" r="10" />
              </svg>
              <span>Memory Timeline</span>
            </Link>

            <Link
              to="/"
              className="px-3.5 py-1.5 rounded-lg bg-bg-card border border-border text-xs text-gray-300 hover:text-white hover:bg-bg-subtle transition-colors"
            >
              ← All Repositories
            </Link>

            {/* Admin Delete Action */}
            {canManageUsers && (
              <button
                type="button"
                onClick={() => setIsDeleteOpen(true)}
                className="px-3 py-1.5 rounded-lg bg-red-500/10 border border-red-500/30 text-xs font-medium text-red-400 hover:bg-red-500/20 transition-colors flex items-center gap-1.5"
                title="Delete repository graph"
              >
                <svg
                  className="w-3.5 h-3.5"
                  viewBox="0 0 24 24"
                  fill="none"
                  stroke="currentColor"
                  strokeWidth="2"
                >
                  <polyline points="3 6 5 6 21 6" />
                  <path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2" />
                </svg>
                <span>Delete</span>
              </button>
            )}
          </div>
        </div>

        {/* ════════════════════════════════════════════════════════════════
            IN-PROGRESS & FAILED PIPELINE PROGRESS STEPPER VIEW
            ════════════════════════════════════════════════════════════════ */}
        {!isReady && (
          <div className="bg-bg-surface border border-border rounded-xl p-6 md:p-8 shadow-xl">
            <div className="flex items-center justify-between mb-6 pb-4 border-b border-border">
              <div>
                <h2 className="text-lg font-bold text-white flex items-center gap-2">
                  <span>Pipeline Execution Progress</span>
                  {!isFailed && (
                    <span className="w-2 h-2 rounded-full bg-accent animate-ping" />
                  )}
                </h2>
                <p className="text-xs text-gray-400 mt-0.5">
                  Automated static analysis pipeline status
                </p>
              </div>

              {repo.stage_detail && (
                <div className="text-xs font-mono px-3 py-1.5 rounded bg-bg-card border border-border text-accent">
                  {repo.stage_detail}
                </div>
              )}
            </div>

            {/* Failed Error Message Callout */}
            {isFailed && (
              <div
                role="alert"
                className="mb-8 p-4 rounded-xl bg-red-500/10 border border-red-500/30 text-red-400"
              >
                <div className="flex items-start gap-3">
                  <div className="w-8 h-8 rounded-lg bg-red-500/20 flex items-center justify-center flex-shrink-0 text-red-400">
                    <svg
                      className="w-5 h-5"
                      viewBox="0 0 24 24"
                      fill="none"
                      stroke="currentColor"
                      strokeWidth="2"
                    >
                      <circle cx="12" cy="12" r="10" />
                      <line x1="12" y1="8" x2="12" y2="12" />
                      <line x1="12" y1="16" x2="12.01" y2="16" />
                    </svg>
                  </div>
                  <div>
                    <h3 className="text-sm font-semibold text-white">
                      Analysis Pipeline Terminated with Error
                    </h3>
                    <p className="text-xs text-red-300 font-mono mt-1 break-words">
                      {repo.error || "An unhandled exception occurred during repository analysis."}
                    </p>
                  </div>
                </div>
              </div>
            )}

            {/* Stepper Grid / Timeline */}
            <div className="grid grid-cols-1 md:grid-cols-5 gap-4 relative">
              {PIPELINE_STAGES.map((stage, idx) => {
                const isPassed = !isFailed && currentStageIdx > idx;
                const isCurrent = !isFailed && currentStageIdx === idx;
                const isStageFailed = isFailed && idx === 1; // Early pipeline failure point

                return (
                  <div
                    key={stage.key}
                    className={`relative p-4 rounded-xl border transition-all ${
                      isPassed
                        ? "bg-emerald-500/5 border-emerald-500/30 text-emerald-400"
                        : isCurrent
                        ? "bg-accent/10 border-accent text-accent ring-1 ring-accent/30 shadow-lg shadow-accent/10"
                        : isStageFailed
                        ? "bg-red-500/10 border-red-500/40 text-red-400"
                        : "bg-bg-card border-border text-gray-500"
                    }`}
                  >
                    <div className="flex items-center justify-between mb-3">
                      <span className="text-[10px] font-mono font-bold uppercase tracking-wider">
                        Stage 0{idx + 1}
                      </span>

                      {/* Icon state */}
                      {isPassed && (
                        <div className="w-6 h-6 rounded-full bg-emerald-500/20 text-emerald-400 flex items-center justify-center">
                          <svg
                            className="w-3.5 h-3.5"
                            viewBox="0 0 24 24"
                            fill="none"
                            stroke="currentColor"
                            strokeWidth="3"
                          >
                            <polyline points="20 6 9 17 4 12" />
                          </svg>
                        </div>
                      )}

                      {isCurrent && (
                        <div className="w-6 h-6 rounded-full bg-accent/20 text-accent flex items-center justify-center">
                          <svg
                            className="animate-spin w-3.5 h-3.5"
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
                        </div>
                      )}

                      {isStageFailed && (
                        <div className="w-6 h-6 rounded-full bg-red-500/20 text-red-400 flex items-center justify-center">
                          <svg
                            className="w-3.5 h-3.5"
                            viewBox="0 0 24 24"
                            fill="none"
                            stroke="currentColor"
                            strokeWidth="3"
                          >
                            <line x1="18" y1="6" x2="6" y2="18" />
                            <line x1="6" y1="6" x2="18" y2="18" />
                          </svg>
                        </div>
                      )}

                      {!isPassed && !isCurrent && !isStageFailed && (
                        <div className="w-6 h-6 rounded-full bg-bg-surface border border-border flex items-center justify-center text-gray-500 text-xs">
                          {idx + 1}
                        </div>
                      )}
                    </div>

                    <h3 className="font-semibold text-white text-sm mb-1">
                      {stage.title}
                    </h3>
                    <p className="text-xs text-gray-400 leading-snug">
                      {stage.description}
                    </p>
                  </div>
                );
              })}
            </div>
          </div>
        )}

        {/* ════════════════════════════════════════════════════════════════
            READY STATE: SUMMARY STATS STRIP & HONEST SCOPE LINE
            ════════════════════════════════════════════════════════════════ */}
        {isReady && stats && (
          <div className="space-y-6">
            {/* The Honest Scope Line Strip */}
            <div className="bg-bg-surface border border-border rounded-xl p-4 md:p-5 shadow-lg flex flex-col sm:flex-row sm:items-center justify-between gap-4">
              <div className="flex items-start gap-3">
                <div className="w-8 h-8 rounded-lg bg-accent/15 border border-accent/30 text-accent flex items-center justify-center flex-shrink-0 mt-0.5">
                  <svg
                    className="w-4 h-4"
                    viewBox="0 0 24 24"
                    fill="none"
                    stroke="currentColor"
                    strokeWidth="2"
                  >
                    <circle cx="12" cy="12" r="10" />
                    <line x1="12" y1="16" x2="12" y2="12" />
                    <line x1="12" y1="8" x2="12.01" y2="8" />
                  </svg>
                </div>
                <div>
                  <h3 className="text-xs font-semibold uppercase tracking-wider text-accent mb-1">
                    Analysis Scope & Provenance
                  </h3>
                  {/* Honest Scope Line exact contract format */}
                  <p className="text-sm text-gray-200 font-mono leading-relaxed">
                    Python only. Analysis scope:{" "}
                    <span className="text-white font-bold">
                      {stats.files_parsed} files parsed
                    </span>
                    ,{" "}
                    <span className="text-white font-bold">
                      {stats.files_failed} failed
                    </span>
                    . Dependencies from{" "}
                    <span className="text-accent font-bold">
                      {stats.lockfile_kind || "none"}
                    </span>
                    . Transitive dependencies:{" "}
                    <span
                      className={`font-bold ${
                        stats.transitive_available
                          ? "text-emerald-400"
                          : "text-amber-400"
                      }`}
                    >
                      {stats.transitive_available
                        ? "available"
                        : "not available (no lockfile)"}
                    </span>
                    .
                  </p>
                </div>
              </div>

              <div className="flex items-center gap-2 text-xs text-gray-400 border-t sm:border-t-0 sm:border-l border-border pt-3 sm:pt-0 sm:pl-4 flex-shrink-0">
                <span className="w-2 h-2 rounded-full bg-emerald-400" />
                <span>Call Graph Indexed</span>
              </div>
            </div>

            {/* Key Metrics Stats Strip */}
            <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-4">
              {/* Modules */}
              <div className="bg-bg-surface border border-border rounded-xl p-4 text-center">
                <span className="text-2xl font-bold font-mono text-white block">
                  {stats.modules}
                </span>
                <span className="text-xs uppercase tracking-wider text-gray-400 mt-1 block">
                  Modules
                </span>
              </div>

              {/* Public Entrypoints */}
              <div className="bg-bg-surface border border-border rounded-xl p-4 text-center">
                <span className="text-2xl font-bold font-mono text-white block">
                  {stats.public_entrypoints}
                </span>
                <span className="text-xs uppercase tracking-wider text-gray-400 mt-1 block">
                  Public Entrypoints
                </span>
                <span className="text-[10px] text-gray-500 block">
                  of {stats.entrypoints} total
                </span>
              </div>

              {/* Packages */}
              <div className="bg-bg-surface border border-border rounded-xl p-4 text-center">
                <span className="text-2xl font-bold font-mono text-white block">
                  {stats.packages}
                </span>
                <span className="text-xs uppercase tracking-wider text-gray-400 mt-1 block">
                  Packages
                </span>
                <span className="text-[10px] text-gray-500 block">
                  {stats.direct_packages} direct
                </span>
              </div>

              {/* Total Findings */}
              <div
                className={`border rounded-xl p-4 text-center ${
                  stats.findings > 0
                    ? "bg-red-500/10 border-red-500/30 text-red-400"
                    : "bg-emerald-500/10 border-emerald-500/30 text-emerald-400"
                }`}
              >
                <span className="text-2xl font-bold font-mono block">
                  {stats.findings}
                </span>
                <span className="text-xs uppercase tracking-wider mt-1 block">
                  Findings
                </span>
                <span className="text-[10px] opacity-80 block">
                  OSV matched CVEs
                </span>
              </div>

              {/* Blind Spots */}
              <div className="bg-bg-surface border border-border rounded-xl p-4 text-center">
                <span
                  className={`text-2xl font-bold font-mono block ${
                    stats.blind_spots > 0 ? "text-amber-400" : "text-gray-400"
                  }`}
                >
                  {stats.blind_spots}
                </span>
                <span className="text-xs uppercase tracking-wider text-gray-400 mt-1 block">
                  Blind Spots
                </span>
                <span className="text-[10px] text-gray-500 block">
                  Dynamic/unresolved
                </span>
              </div>

              {/* Parsed Files */}
              <div className="bg-bg-surface border border-border rounded-xl p-4 text-center">
                <span className="text-2xl font-bold font-mono text-white block">
                  {stats.files_parsed}
                </span>
                <span className="text-xs uppercase tracking-wider text-gray-400 mt-1 block">
                  Files Parsed
                </span>
                <span className="text-[10px] text-gray-500 block">
                  {stats.files_failed} unparseable
                </span>
              </div>
            </div>

            {/* Findings Dashboard */}
            <FindingsDashboard
              repoId={repo.id}
              lockfileKind={stats.lockfile_kind}
            />
          </div>
        )}

      </div>

      {/* Admin Delete Confirmation Modal */}
      <DeleteRepoModal
        repo={repo}
        isOpen={isDeleteOpen}
        onClose={() => setIsDeleteOpen(false)}
        onDeleted={() => {
          queryClient.invalidateQueries({ queryKey: ["repos"] });
          navigate("/");
        }}
      />

      {/* Collapsible Chat Panel on the right */}
      {repo && <ChatPanel repoId={repo.id} />}
    </div>
  );
};
