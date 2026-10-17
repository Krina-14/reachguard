import React, { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { apiFetch } from "../api/client";
import { useCan } from "../auth/useCan";

import { StatusChip } from "../components/StatusChip";
import { AddRepoModal } from "../components/AddRepoModal";
import { DeleteRepoModal } from "../components/DeleteRepoModal";
import type { Repo } from "../api/types";
import { useDocumentTitle } from "../lib/useDocumentTitle";

export const ReposPage: React.FC = () => {
  useDocumentTitle("Repositories");
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const { canAddRepo, canManageUsers } = useCan();

  const [isAddModalOpen, setIsAddModalOpen] = useState(false);
  const [repoToDelete, setRepoToDelete] = useState<Repo | null>(null);

  // Poll every 3 seconds while ANY repo is not in a terminal state ('ready' or 'failed')
  const {
    data: repos = [],
    isLoading,
    isError,
    error,
    refetch,
  } = useQuery<Repo[]>({
    queryKey: ["repos"],
    queryFn: () => apiFetch<Repo[]>("/api/repos"),
    refetchInterval: (query) => {
      const data = query.state.data;
      if (!data || !Array.isArray(data)) return false;
      const hasActive = data.some(
        (r) => r.status !== "ready" && r.status !== "failed"
      );
      return hasActive ? 3000 : false;
    },
  });

  const formatRepoName = (source?: string | null) => {
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
      // Fallback
    }
    return source;
  };

  const formatDate = (dateStr?: string | null) => {
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
  };

  const hasActivePipelines = Boolean(
    Array.isArray(repos) &&
      repos.some((r) => r?.status && r.status !== "ready" && r.status !== "failed")
  );


  return (
    <div className="min-h-screen bg-bg text-gray-200 p-6 md:p-8">
      <div className="max-w-7xl mx-auto space-y-6">
        {/* Top Header & Actions Bar */}
        <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 pb-4 border-b border-border">
          <div>
            <div className="flex items-center gap-3">
              <h1 className="text-2xl md:text-3xl font-bold tracking-tight text-white">
                Repositories
              </h1>
              {hasActivePipelines && (
                <span className="inline-flex items-center gap-1.5 px-2 py-0.5 rounded-full text-xs font-medium bg-accent/15 text-accent border border-accent/30 animate-pulse">
                  <span className="w-1.5 h-1.5 rounded-full bg-accent" />
                  Live Syncing (3s)
                </span>
              )}
            </div>
            <p className="text-sm text-gray-400 mt-1">
              Reachability-aware vulnerability inspection & call-graph analysis
            </p>
          </div>

          <div className="flex items-center gap-3">
            {canAddRepo && (
              <button
                type="button"
                onClick={() => setIsAddModalOpen(true)}
                className="inline-flex items-center gap-2 px-4 py-2 rounded-lg text-sm font-semibold text-white bg-accent hover:bg-accent-hover active:bg-accent/90 shadow-lg shadow-accent/20 transition-all cursor-pointer"
              >
                <svg
                  className="w-4 h-4"
                  viewBox="0 0 24 24"
                  fill="none"
                  stroke="currentColor"
                  strokeWidth="2"
                >
                  <path d="M12 5v14M5 12h14" />
                </svg>
                <span>Analyze a repository</span>
              </button>
            )}
          </div>
        </div>

        {/* Loading Skeleton */}
        {isLoading && (
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-5">
            {[1, 2, 3].map((i) => (
              <div
                key={i}
                className="bg-bg-surface border border-border rounded-xl p-5 animate-pulse space-y-4"
              >
                <div className="h-5 bg-bg-card rounded w-2/3" />
                <div className="h-4 bg-bg-card rounded w-1/3" />
                <div className="h-10 bg-bg-card rounded w-full" />
              </div>
            ))}
          </div>
        )}

        {/* Query Error State */}
        {isError && (
          <div className="p-5 rounded-xl bg-red-500/10 border border-red-500/30 text-red-400 flex items-start justify-between gap-4">
            <div className="flex items-start gap-3">
              <svg
                className="w-5 h-5 flex-shrink-0 mt-0.5"
                viewBox="0 0 24 24"
                fill="none"
                stroke="currentColor"
                strokeWidth="2"
              >
                <circle cx="12" cy="12" r="10" />
                <line x1="12" y1="8" x2="12" y2="12" />
                <line x1="12" y1="16" x2="12.01" y2="16" />
              </svg>
              <div>
                <h2 className="text-sm font-bold text-red-300">
                  Failed to fetch repositories
                </h2>
                <p className="text-xs text-red-400/90 mt-1">
                  {error instanceof Error ? error.message : "Network error"}
                </p>
              </div>
            </div>
            <button
              onClick={() => refetch()}
              className="px-3 py-1.5 rounded-lg bg-bg-card border border-red-500/40 text-xs text-white hover:bg-bg-subtle transition-colors"
            >
              Retry
            </button>
          </div>
        )}

        {/* Empty State */}
        {!isLoading && !isError && repos.length === 0 && (
          <div className="bg-bg-surface border border-border rounded-2xl p-8 md:p-14 text-center max-w-2xl mx-auto shadow-2xl">
            <div className="w-16 h-16 rounded-2xl bg-accent/15 border border-accent/30 text-accent mx-auto flex items-center justify-center mb-6">
              <svg
                className="w-9 h-9"
                viewBox="0 0 24 24"
                fill="none"
                stroke="currentColor"
                strokeWidth="1.8"
                strokeLinecap="round"
                strokeLinejoin="round"
              >
                <path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z" />
              </svg>
            </div>

            <h2 className="text-2xl font-bold text-white mb-3">
              Welcome to ReachGuard
            </h2>
            <p className="text-sm text-gray-400 leading-relaxed mb-6">
              ReachGuard performs reachability-aware vulnerability inspection on
              Python applications. By mapping Python AST call chains and public
              entrypoints directly against the OSV vulnerability database in
              FalkorDB, it separates truly exploitable CVEs from inert, unreachable
              code.
            </p>

            {canAddRepo ? (
              <div className="space-y-3">
                <button
                  type="button"
                  onClick={() => setIsAddModalOpen(true)}
                  className="inline-flex items-center gap-2 px-6 py-3 rounded-xl text-sm font-semibold text-white bg-accent hover:bg-accent-hover active:bg-accent/90 shadow-xl shadow-accent/25 transition-all cursor-pointer"
                >
                  <svg
                    className="w-4 h-4"
                    viewBox="0 0 24 24"
                    fill="none"
                    stroke="currentColor"
                    strokeWidth="2"
                  >
                    <path d="M12 5v14M5 12h14" />
                  </svg>
                  <span>Analyze a repository</span>
                </button>
                <p className="text-xs text-gray-500">
                  Provide a public GitHub URL or upload a project zip archive (max 50 MB)
                </p>
              </div>
            ) : (
              <div className="inline-flex items-center gap-2 px-4 py-2.5 rounded-lg bg-bg-card border border-border text-xs text-gray-400">
                <svg
                  className="w-4 h-4 text-amber-400"
                  viewBox="0 0 24 24"
                  fill="none"
                  stroke="currentColor"
                  strokeWidth="2"
                >
                  <circle cx="12" cy="12" r="10" />
                  <line x1="12" y1="8" x2="12" y2="12" />
                  <line x1="12" y1="16" x2="12.01" y2="16" />
                </svg>
                <span>Ask an analyst to add a repository</span>
              </div>
            )}
          </div>
        )}

        {/* Repository Cards Grid */}
        {!isLoading && !isError && repos.length > 0 && (
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-5">
            {repos.map((repo) => {
              const sourceStr = repo?.source || "Untitled Repository";
              const isGit =
                sourceStr.startsWith("http://") ||
                sourceStr.startsWith("https://") ||
                repo?.source_type === "git";
              const repoStatus = repo?.status || "queued";
              const isReady = repoStatus === "ready";
              const isFailed = repoStatus === "failed";
              const stats = repo?.stats;


              return (
                <div
                  key={repo.id}
                  className="group relative bg-bg-surface hover:bg-bg-surface/80 border border-border hover:border-gray-600 rounded-xl p-5 shadow-lg transition-all flex flex-col justify-between"
                >
                  <div>
                    {/* Card Header: Source Icon, Name & Status Chip */}
                    <div className="flex items-start justify-between gap-3 mb-3">
                      <div className="flex items-start gap-2.5 min-w-0">
                        <div className="w-8 h-8 rounded-lg bg-bg-card border border-border flex items-center justify-center flex-shrink-0 text-gray-400 group-hover:text-accent group-hover:border-accent/40 transition-colors">
                          {isGit ? (
                            <svg
                              className="w-4 h-4"
                              viewBox="0 0 24 24"
                              fill="currentColor"
                            >
                              <path d="M12 0C5.37 0 0 5.37 0 12c0 5.31 3.435 9.795 8.205 11.385.6.105.825-.255.825-.57 0-.285-.015-1.23-.015-2.235-3.015.555-3.795-.735-4.035-1.41-.135-.345-.72-1.41-1.23-1.695-.42-.225-1.02-.78-.015-.795.945-.015 1.62.87 1.845 1.23 1.08 1.815 2.805 1.305 3.495.99.105-.78.42-1.305.765-1.605-2.67-.3-5.46-1.335-5.46-5.925 0-1.305.465-2.385 1.23-3.225-.12-.3-.54-1.53.12-3.18 0 0 1.005-.315 3.3 1.23.96-.27 1.98-.405 3-.405s2.04.135 3 .405c2.295-1.56 3.3-1.23 3.3-1.23.66 1.65.24 2.88.12 3.18.765.84 1.23 1.905 1.23 3.225 0 4.605-2.805 5.625-5.475 5.925.435.375.81 1.095.81 2.22 0 1.605-.015 2.895-.015 3.3 0 .315.225.69.825.57A12.02 12.02 0 0024 12c0-6.63-5.37-12-12-12z" />
                            </svg>
                          ) : (
                            <svg
                              className="w-4 h-4"
                              viewBox="0 0 24 24"
                              fill="none"
                              stroke="currentColor"
                              strokeWidth="2"
                            >
                              <polyline points="21 8 21 21 3 21 3 8" />
                              <rect x="1" y="3" width="22" height="5" />
                              <line x1="10" y1="12" x2="14" y2="12" />
                            </svg>
                          )}
                        </div>
                        <div className="min-w-0">
                          <Link
                            to={`/repos/${repo.id}`}
                            className="font-semibold text-white hover:text-accent transition-colors truncate block text-sm focus:outline-none"
                            title={sourceStr}
                          >
                            {formatRepoName(sourceStr)}
                          </Link>
                          <p className="text-[11px] text-gray-500 font-mono truncate">
                            {sourceStr}
                          </p>
                        </div>
                      </div>

                      <StatusChip
                        status={repoStatus}
                        stageDetail={repo?.stage_detail}
                        className="flex-shrink-0"
                      />
                    </div>


                    {/* Failed State Error Callout */}
                    {isFailed && (
                      <div className="mt-3 p-3 rounded-lg bg-red-500/10 border border-red-500/30 text-red-400 text-xs">
                        <div className="flex items-start gap-2">
                          <svg
                            className="w-4 h-4 flex-shrink-0 mt-0.5"
                            viewBox="0 0 24 24"
                            fill="none"
                            stroke="currentColor"
                            strokeWidth="2"
                          >
                            <circle cx="12" cy="12" r="10" />
                            <line x1="12" y1="8" x2="12" y2="12" />
                            <line x1="12" y1="16" x2="12.01" y2="16" />
                          </svg>
                          <span className="leading-snug break-words">
                            {repo.error || "Pipeline failed during analysis"}
                          </span>
                        </div>
                      </div>
                    )}

                    {/* In-progress Active Stage Indicator */}
                    {!isReady && !isFailed && (
                      <div className="mt-3 p-2.5 rounded-lg bg-bg-card border border-border text-xs text-gray-300 flex items-center gap-2">
                        <svg
                          className="animate-spin w-3.5 h-3.5 text-accent flex-shrink-0"
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
                        <span className="truncate">
                          {repo.stage_detail || `Current stage: ${repo.status}`}
                        </span>
                      </div>
                    )}

                    {/* Ready Key Stats Grid */}
                    {isReady && stats && (
                      <div className="mt-4 grid grid-cols-2 sm:grid-cols-4 gap-2 pt-3 border-t border-border/80">
                        <div className="bg-bg-card/70 border border-border/60 rounded-lg p-2 text-center">
                          <span className="block text-base font-bold text-white font-mono">
                            {stats.modules ?? "—"}
                          </span>
                          <span className="block text-[10px] uppercase tracking-wider text-gray-400">
                            Modules
                          </span>
                        </div>
                        <div className="bg-bg-card/70 border border-border/60 rounded-lg p-2 text-center">
                          <span className="block text-base font-bold text-white font-mono">
                            {stats.entrypoints ?? "—"}
                          </span>
                          <span className="block text-[10px] uppercase tracking-wider text-gray-400">
                            Entrypoints
                          </span>
                        </div>
                        <div className="bg-bg-card/70 border border-border/60 rounded-lg p-2 text-center">
                          <span className="block text-base font-bold text-white font-mono">
                            {stats.packages ?? "—"}
                          </span>
                          <span className="block text-[10px] uppercase tracking-wider text-gray-400">
                            Packages
                          </span>
                        </div>
                        <div
                          className={`rounded-lg p-2 text-center border ${
                            (stats.findings ?? 0) > 0
                              ? "bg-red-500/10 border-red-500/30 text-red-400"
                              : "bg-emerald-500/10 border-emerald-500/30 text-emerald-400"
                          }`}
                        >
                          <span className="block text-base font-bold font-mono">
                            {stats.findings ?? 0}
                          </span>
                          <span className="block text-[10px] uppercase tracking-wider">
                            Findings
                          </span>
                        </div>
                      </div>
                    )}
                  </div>

                  {/* Card Footer: Timestamp & Action Buttons */}
                  <div className="mt-4 pt-3 border-t border-border flex items-center justify-between text-xs text-gray-400">
                    <span title={repo.created_at}>
                      Created {formatDate(repo.created_at)}
                    </span>

                    <div className="flex items-center gap-2">
                      {/* Delete button: Failed repos show Delete for admins */}
                      {isFailed && canManageUsers && (
                        <button
                          type="button"
                          onClick={(e) => {
                            e.stopPropagation();
                            setRepoToDelete(repo);
                          }}
                          className="px-2.5 py-1 rounded bg-red-500/10 hover:bg-red-500/20 text-red-400 border border-red-500/30 transition-colors flex items-center gap-1.5"
                          title="Delete failed repository (Admin only)"
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

                      <button
                        type="button"
                        onClick={() => navigate(`/repos/${repo.id}`)}
                        className="text-gray-400 hover:text-white flex items-center gap-1 transition-colors"
                      >
                        <span>View</span>
                        <svg
                          className="w-3.5 h-3.5"
                          viewBox="0 0 24 24"
                          fill="none"
                          stroke="currentColor"
                          strokeWidth="2"
                        >
                          <polyline points="9 18 15 12 9 6" />
                        </svg>
                      </button>
                    </div>
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </div>

      {/* Add Repository Modal */}
      <AddRepoModal
        isOpen={isAddModalOpen}
        onClose={() => setIsAddModalOpen(false)}
      />

      {/* Admin Delete Confirmation Modal */}
      <DeleteRepoModal
        repo={repoToDelete}
        isOpen={Boolean(repoToDelete)}
        onClose={() => setRepoToDelete(null)}
        onDeleted={() => {
          queryClient.invalidateQueries({ queryKey: ["repos"] });
        }}
      />
    </div>
  );
};
