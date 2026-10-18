import React, { useState } from "react";
import { Link } from "react-router-dom";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { apiFetch } from "../../api/client";
import type { HealthResponse, Repo } from "../../api/types";

const FIFTEEN_MINUTES_MS = 15 * 60 * 1000;

export const SystemHealthPanel: React.FC = () => {
  const queryClient = useQueryClient();
  const [deletingRepoId, setDeletingRepoId] = useState<string | null>(null);
  const [deleteError, setDeleteError] = useState<string | null>(null);

  // 1. Fetch Health: GET /api/health
  const {
    data: health,
    isLoading: isHealthLoading,
    isError: isHealthError,
    error: healthError,
    refetch: refetchHealth,
  } = useQuery<HealthResponse>({
    queryKey: ["backend-health"],
    queryFn: () => apiFetch<HealthResponse>("/api/health"),
    refetchInterval: 15000,
  });

  // 2. Fetch Repos: GET /api/repos
  const {
    data: repos = [],
    isLoading: isReposLoading,
    isError: isReposError,
    error: reposError,
    refetch: refetchRepos,
  } = useQuery<Repo[]>({
    queryKey: ["repos"],
    queryFn: () => apiFetch<Repo[]>("/api/repos"),
    refetchInterval: 15000,
  });

  const isLoading = isHealthLoading || isReposLoading;
  const isError = isHealthError || isReposError;

  // Status counts
  const readyCount = repos.filter((r) => r.status === "ready").length;
  const inProgressCount = repos.filter((r) =>
    ["cloning", "parsing", "scanning"].includes(r.status)
  ).length;
  const queuedCount = repos.filter((r) => r.status === "queued").length;
  const failedCount = repos.filter((r) => r.status === "failed").length;

  // Stuck repos: queued/cloning/parsing for > 15 minutes
  const stuckRepos = repos.filter((r) => {
    if (!["queued", "cloning", "parsing"].includes(r.status)) return false;
    const createdAt = new Date(r.created_at).getTime();
    if (isNaN(createdAt)) return false;
    return Date.now() - createdAt > FIFTEEN_MINUTES_MS;
  });

  const handleDeleteStuckRepo = async (repoId: string, repoSource: string) => {
    if (
      !window.confirm(
        `Are you sure you want to delete stuck repository "${repoSource}"? This will terminate its pipeline and remove its graph data.`
      )
    ) {
      return;
    }

    setDeletingRepoId(repoId);
    setDeleteError(null);
    try {
      await apiFetch(`/api/repos/${repoId}`, {
        method: "DELETE",
      });
      queryClient.invalidateQueries({ queryKey: ["repos"] });
      queryClient.invalidateQueries({ queryKey: ["admin-audit"] });
    } catch (err: unknown) {
      setDeleteError(
        err instanceof Error ? err.message : "Failed to delete stuck repository"
      );
    } finally {
      setDeletingRepoId(null);
    }
  };

  const formatElapsedMinutes = (dateStr: string) => {
    const elapsed = Date.now() - new Date(dateStr).getTime();
    const minutes = Math.floor(elapsed / (60 * 1000));
    if (minutes >= 60) {
      const hours = Math.floor(minutes / 60);
      return `${hours}h ${minutes % 60}m ago`;
    }
    return `${minutes}m ago`;
  };

  return (
    <div className="bg-bg-surface border border-border rounded-xl p-5 shadow-sm space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between pb-3 border-b border-border/70 flex-wrap gap-2">
        <div className="flex items-center gap-2.5">
          <div className="w-8 h-8 rounded-lg bg-emerald-500/15 border border-emerald-500/30 text-emerald-400 flex items-center justify-center">
            <svg
              className="w-4 h-4"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth="2"
            >
              <path d="M22 12h-4l-3 9L9 3l-3 9H2" />
            </svg>
          </div>
          <div>
            <h2 className="text-base font-bold text-white flex items-center gap-2">
              System Health & Diagnostics
            </h2>
            <p className="text-xs text-gray-400">
              Graph database status, LLM agent runtime, and repository pipeline monitoring
            </p>
          </div>
        </div>

        <button
          type="button"
          onClick={() => {
            refetchHealth();
            refetchRepos();
          }}
          title="Refresh health diagnostics"
          className="px-2.5 py-1 rounded-lg bg-bg-card hover:bg-bg-subtle text-gray-300 border border-border text-xs transition-colors cursor-pointer"
        >
          Refresh
        </button>
      </div>

      {deleteError && (
        <div className="p-3 rounded-lg bg-red-500/15 border border-red-500/30 text-red-400 text-xs">
          {deleteError}
        </div>
      )}

      {/* Loading State */}
      {isLoading && (
        <div className="grid grid-cols-2 md:grid-cols-4 gap-4 animate-pulse">
          {[1, 2, 3, 4].map((i) => (
            <div key={i} className="h-24 bg-bg-card/70 border border-border rounded-xl" />
          ))}
        </div>
      )}

      {/* Error State */}
      {isError && !isLoading && (
        <div className="p-6 rounded-lg border border-red-500/30 bg-red-500/5 text-center space-y-2">
          <p className="text-red-400 text-xs font-medium">
            Failed to query system health or repository statistics.
          </p>
          <p className="text-[11px] text-gray-500 font-mono">
            {healthError instanceof Error
              ? healthError.message
              : reposError instanceof Error
              ? reposError.message
              : "Backend unreachable"}
          </p>
          <button
            type="button"
            onClick={() => {
              refetchHealth();
              refetchRepos();
            }}
            className="px-3 py-1 bg-red-600 hover:bg-red-500 text-white rounded text-xs"
          >
            Retry
          </button>
        </div>
      )}

      {!isLoading && !isError && health && (
        <div className="space-y-6">
          {/* Diagnostic Stat Cards */}
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
            {/* FalkorDB Graph Database */}
            <div className="p-4 rounded-xl border border-border bg-bg-card/50 space-y-2">
              <div className="flex items-center justify-between text-xs text-gray-400">
                <span className="font-semibold uppercase tracking-wider text-[11px]">
                  Graph Database
                </span>
                <span
                  className={`w-2.5 h-2.5 rounded-full ${
                    health.falkordb
                      ? "bg-emerald-400 animate-pulse"
                      : "bg-red-500"
                  }`}
                />
              </div>
              <div className="flex items-baseline justify-between">
                <span className="text-lg font-bold text-white font-mono">
                  FalkorDB
                </span>
                <span
                  className={`px-2 py-0.5 rounded text-[11px] font-bold uppercase border ${
                    health.falkordb
                      ? "bg-emerald-500/15 text-emerald-400 border-emerald-500/30"
                      : "bg-red-500/15 text-red-400 border-red-500/30"
                  }`}
                >
                  {health.falkordb ? "Online" : "Offline"}
                </span>
              </div>
              <p className="text-[11px] text-gray-400">
                Primary graph storage for code, AST, and call paths.
              </p>
            </div>

            {/* LLM Provider & Reachability */}
            <div className="p-4 rounded-xl border border-border bg-bg-card/50 space-y-2">
              <div className="flex items-center justify-between text-xs text-gray-400">
                <span className="font-semibold uppercase tracking-wider text-[11px]">
                  LLM Provider
                </span>
                <span
                  className={`w-2.5 h-2.5 rounded-full ${
                    health.llm?.reachable
                      ? "bg-emerald-400"
                      : "bg-amber-400"
                  }`}
                />
              </div>
              <div className="flex items-baseline justify-between">
                <span className="text-lg font-bold text-white font-mono capitalize">
                  {health.llm?.provider || "N/A"}
                </span>
                <span className="px-2 py-0.5 rounded text-[11px] font-mono bg-sky-500/15 text-sky-300 border border-sky-500/30 uppercase">
                  {health.llm?.reachable ? "Reachable" : "Degraded"}
                </span>
              </div>
              <p className="text-[11px] text-gray-400 truncate">
                Model: <code className="text-gray-300">{health.llm?.model || "default"}</code>
              </p>
            </div>

            {/* AI Agent Mode */}
            <div className="p-4 rounded-xl border border-border bg-bg-card/50 space-y-2">
              <div className="flex items-center justify-between text-xs text-gray-400">
                <span className="font-semibold uppercase tracking-wider text-[11px]">
                  Agent Mode
                </span>
                <span className="text-[10px] text-gray-500 font-mono">v{health.version}</span>
              </div>
              <div className="flex items-baseline justify-between">
                <span className="text-lg font-bold text-white font-mono uppercase">
                  {health.llm?.mode || "deterministic"}
                </span>
                <span className="px-2 py-0.5 rounded text-[11px] font-mono bg-purple-500/15 text-purple-300 border border-purple-500/30">
                  {health.llm?.mode === "llm" ? "LLM Powered" : "Deterministic"}
                </span>
              </div>
              <p className="text-[11px] text-gray-400">
                Grounding and what-if simulation engine.
              </p>
            </div>

            {/* Repository Pipeline Summary */}
            <div className="p-4 rounded-xl border border-border bg-bg-card/50 space-y-2">
              <div className="flex items-center justify-between text-xs text-gray-400">
                <span className="font-semibold uppercase tracking-wider text-[11px]">
                  Repositories
                </span>
                <Link to="/repos" className="text-[11px] text-accent hover:underline">
                  View all
                </Link>
              </div>
              <div className="flex items-baseline justify-between">
                <span className="text-2xl font-bold text-white font-mono">
                  {repos.length}
                </span>
                <div className="flex items-center gap-1.5 text-[11px] font-mono">
                  <span className="text-emerald-400 font-semibold">{readyCount} ready</span>
                  {failedCount > 0 && (
                    <span className="text-red-400 font-semibold">• {failedCount} failed</span>
                  )}
                </div>
              </div>
              <div className="flex items-center gap-2 pt-1 text-[11px] text-gray-400">
                <span>In-flight: <strong>{inProgressCount}</strong></span>
                <span>•</span>
                <span>Queued: <strong>{queuedCount}</strong></span>
              </div>
            </div>
          </div>

          {/* ════════════════════════════════════════════════════════════
              STUCK REPOSITORIES MONITOR (> 15 MIN IN QUEUED/CLONING/PARSING)
              ════════════════════════════════════════════════════════════ */}
          <div className="space-y-3">
            <div className="flex items-center justify-between">
              <h3 className="text-xs font-semibold uppercase tracking-wider text-gray-400 flex items-center gap-2 font-mono">
                <svg
                  className="w-4 h-4 text-amber-400"
                  viewBox="0 0 24 24"
                  fill="none"
                  stroke="currentColor"
                  strokeWidth="2"
                >
                  <circle cx="12" cy="12" r="10" />
                  <polyline points="12 6 12 12 16 14" />
                </svg>
                Stuck Repositories Monitor (Over 15 Minutes)
              </h3>
              {stuckRepos.length > 0 && (
                <span className="px-2 py-0.5 rounded text-[11px] font-mono font-bold bg-amber-500/20 text-amber-300 border border-amber-500/35">
                  {stuckRepos.length} Stuck
                </span>
              )}
            </div>

            {stuckRepos.length === 0 ? (
              <div className="p-4 rounded-xl border border-border/80 bg-bg-card/25 text-xs text-gray-400 flex items-center gap-2.5">
                <svg
                  className="w-4 h-4 text-emerald-400 shrink-0"
                  viewBox="0 0 24 24"
                  fill="none"
                  stroke="currentColor"
                  strokeWidth="2"
                >
                  <path d="M22 11.08V12a10 10 0 1 1-5.93-9.14" />
                  <polyline points="22 4 12 14.01 9 11.01" />
                </svg>
                <span>
                  No stuck repositories detected. All repository pipelines are healthy or completed within normal thresholds.
                </span>
              </div>
            ) : (
              <div className="border border-amber-500/40 rounded-xl overflow-hidden bg-amber-500/5">
                <div className="p-3 bg-amber-500/10 border-b border-amber-500/30 text-xs text-amber-200">
                  The following repositories have remained in queued, cloning, or parsing status for more than 15 minutes. You may delete them to release system resources.
                </div>
                <div className="overflow-x-auto">
                  <table className="w-full text-left text-xs">
                    <thead className="bg-bg-card text-gray-400 border-b border-border/70 text-[11px]">
                      <tr>
                        <th className="py-2 px-3 font-medium">Repository</th>
                        <th className="py-2 px-3 font-medium">Status</th>
                        <th className="py-2 px-3 font-medium">Stage Detail</th>
                        <th className="py-2 px-3 font-medium">Started</th>
                        <th className="py-2 px-3 font-medium text-right">Action</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-border/60 font-mono text-[11px]">
                      {stuckRepos.map((r) => {
                        const isDeleting = deletingRepoId === r.id;

                        return (
                          <tr key={r.id} className="hover:bg-bg-card/40">
                            <td className="py-2.5 px-3 font-semibold text-white font-sans">
                              <Link
                                to={`/repos/${r.id}`}
                                className="hover:text-accent underline"
                              >
                                {r.source}
                              </Link>
                              <span className="block text-[10px] text-gray-400 font-mono">
                                ID: {r.id}
                              </span>
                            </td>
                            <td className="py-2.5 px-3">
                              <span className="px-2 py-0.5 rounded uppercase font-bold text-[10px] bg-amber-500/20 text-amber-300 border border-amber-500/30">
                                {r.status}
                              </span>
                            </td>
                            <td className="py-2.5 px-3 text-gray-300 font-sans">
                              {r.stage_detail || r.error || "Awaiting pipeline worker"}
                            </td>
                            <td className="py-2.5 px-3 text-gray-400">
                              {formatElapsedMinutes(r.created_at)}
                            </td>
                            <td className="py-2.5 px-3 text-right">
                              <button
                                type="button"
                                disabled={isDeleting}
                                onClick={() => handleDeleteStuckRepo(r.id, r.source)}
                                className="px-2.5 py-1 bg-red-600 hover:bg-red-500 disabled:bg-gray-700 text-white rounded text-xs font-semibold transition-colors cursor-pointer"
                              >
                                {isDeleting ? "Deleting..." : "Delete"}
                              </button>
                            </td>
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>
                </div>
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
};
