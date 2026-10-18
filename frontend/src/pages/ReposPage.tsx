import React, { useState, useMemo } from "react";
import { Link, useNavigate } from "react-router-dom";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { apiFetch } from "../api/client";
import { useCan } from "../auth/useCan";
import { useAuth } from "../auth/useAuth";

import { StatusChip } from "../components/StatusChip";
import { AddRepoModal } from "../components/AddRepoModal";
import { DeleteRepoModal } from "../components/DeleteRepoModal";
import type { Repo } from "../api/types";
import { useDocumentTitle } from "../lib/useDocumentTitle";

function formatRepoName(sourceStr?: string | null, repoId?: string | null): string {
  if (!sourceStr || sourceStr.trim() === "" || sourceStr.trim().toLowerCase() === "unknown") {
    return repoId ? `repo-${repoId.slice(0, 8)}` : "repository";
  }
  const s = sourceStr.trim().replace(/\.git$/i, "").replace(/\/+$/, "");

  // Match git@github.com:owner/repo
  const sshMatch = s.match(/[:/]([^/:]+\/[^/:]+)$/);
  if (sshMatch && sshMatch[1]) {
    const parts = sshMatch[1].split("/");
    if (parts.length >= 2) {
      const owner = parts[parts.length - 2].trim();
      const repo = parts[parts.length - 1].trim();
      if (owner && repo && owner.toLowerCase() !== "unknown" && repo.toLowerCase() !== "unknown") {
        return `${owner}/${repo}`;
      }
      if (repo && repo.toLowerCase() !== "unknown") return repo;
    }
  }

  // Match http(s) URLs or paths
  const slashParts = s.split("/").filter(Boolean);
  if (slashParts.length >= 2) {
    const owner = slashParts[slashParts.length - 2].trim();
    const repo = slashParts[slashParts.length - 1].trim();
    if (owner && repo && owner.toLowerCase() !== "unknown" && repo.toLowerCase() !== "unknown") {
      return `${owner}/${repo}`;
    }
    if (repo && repo.toLowerCase() !== "unknown") return repo;
  } else if (slashParts.length === 1 && slashParts[0].toLowerCase() !== "unknown") {
    return slashParts[0];
  }

  return repoId ? `repo-${repoId.slice(0, 8)}` : "repository";
}

function formatDate(iso: string): string {
  try {
    const d = new Date(iso);
    return isNaN(d.getTime())
      ? iso
      : d.toLocaleDateString(undefined, {
          month: "short",
          day: "numeric",
          hour: "2-digit",
          minute: "2-digit",
        });
  } catch {
    return iso;
  }
}

const FIFTEEN_MINUTES_MS = 15 * 60 * 1000;
const PAGE_SIZE = 12;

const isStaleRepo = (r: Repo) => {
  if (!["queued", "cloning", "parsing"].includes(r.status)) return false;
  const createdAt = new Date(r.created_at).getTime();
  if (isNaN(createdAt)) return false;
  return Date.now() - createdAt > FIFTEEN_MINUTES_MS;
};

const isFailedOrStale = (r: Repo) => r.status === "failed" || isStaleRepo(r);

export const ReposPage: React.FC = () => {
  useDocumentTitle("ReachGuard — Repositories");
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const { user } = useAuth();
  const { canAddRepo } = useCan();
  const isAdmin = user?.role === "admin";

  const [isAddModalOpen, setIsAddModalOpen] = useState(false);
  const [repoToDelete, setRepoToDelete] = useState<Repo | null>(null);
  const [searchQuery, setSearchQuery] = useState("");
  const [statusFilter, setStatusFilter] = useState("all");
  const [visibleCount, setVisibleCount] = useState(PAGE_SIZE);
  const [showFailed, setShowFailed] = useState(false);

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
      if (!Array.isArray(data)) return false;
      const hasActive = data.some(
        (r) => r?.status && r.status !== "ready" && r.status !== "failed"
      );
      return hasActive ? 3000 : false;
    },
  });

  // Filter repositories by search and status
  const filteredRepos = useMemo(() => {
    return repos.filter((r) => {
      // Search query filter (matches owner/repo, source, or ID)
      if (searchQuery.trim()) {
        const term = searchQuery.toLowerCase().trim();
        const name = formatRepoName(r.source, r.id).toLowerCase();
        const source = (r.source || "").toLowerCase();
        const id = (r.id || "").toLowerCase();
        if (!name.includes(term) && !source.includes(term) && !id.includes(term)) {
          return false;
        }
      }

      // Status filter
      if (statusFilter === "ready") return r.status === "ready";
      if (statusFilter === "in_progress") {
        return ["cloning", "parsing", "scanning"].includes(r.status);
      }
      if (statusFilter === "queued") return r.status === "queued";
      if (statusFilter === "failed") return r.status === "failed" || isStaleRepo(r);

      return true;
    });
  }, [repos, searchQuery, statusFilter]);

  // Separate healthy/active repos from failed/stale repos
  const { healthyOrActiveRepos, failedOrStaleRepos } = useMemo(() => {
    const failedOrStale: Repo[] = [];
    const healthyOrActive: Repo[] = [];

    for (const r of filteredRepos) {
      if (isFailedOrStale(r)) {
        failedOrStale.push(r);
      } else {
        healthyOrActive.push(r);
      }
    }
    return { healthyOrActiveRepos: healthyOrActive, failedOrStaleRepos: failedOrStale };
  }, [filteredRepos]);

  // Paginated visible cards
  const visibleCards = useMemo(() => {
    return healthyOrActiveRepos.slice(0, visibleCount);
  }, [healthyOrActiveRepos, visibleCount]);

  const hasMore = healthyOrActiveRepos.length > visibleCount;

  const hasActivePipelines = Boolean(
    Array.isArray(repos) &&
      repos.some(
        (r) => r?.status && r.status !== "ready" && r.status !== "failed"
      )
  );

  // Render a repository card
  const renderRepoCard = (repo: Repo, isFailedOrStaleCard = false) => {
    const sourceStr = repo?.source || "";
    const isGit =
      sourceStr.startsWith("http://") ||
      sourceStr.startsWith("https://") ||
      repo?.source_type === "git";
    const repoStatus = repo?.status || "queued";
    const isReady = repoStatus === "ready";
    const isFailed = repoStatus === "failed";
    const isStale = isStaleRepo(repo);
    const stats = repo?.stats;
    const displayName = formatRepoName(sourceStr, repo.id);

    return (
      <div
        key={repo.id}
        className={`group relative bg-bg-surface hover:bg-bg-surface/90 border rounded-xl p-5 shadow-lg transition-all flex flex-col justify-between ${
          isFailedOrStaleCard
            ? "border-red-500/30 bg-red-950/5 hover:border-red-500/50"
            : "border-border hover:border-gray-600"
        }`}
      >
        <div>
          {/* Card Header: Source Icon, Name & Status Chip */}
          <div className="flex items-start justify-between gap-3 mb-3">
            <div className="flex items-start gap-2.5 min-w-0">
              <div className="w-8 h-8 rounded-lg bg-bg-card border border-border flex items-center justify-center flex-shrink-0 text-gray-400 group-hover:text-accent group-hover:border-accent/40 transition-colors">
                {isGit ? (
                  <svg className="w-4 h-4" viewBox="0 0 24 24" fill="currentColor">
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
                  title={displayName}
                >
                  {displayName}
                </Link>
                <p className="text-[11px] text-gray-500 font-mono truncate">
                  {sourceStr || `repo-${repo.id.slice(0, 8)}`}
                </p>
              </div>
            </div>

            <StatusChip
              status={repoStatus}
              stageDetail={repo?.stage_detail}
              className="flex-shrink-0"
            />
          </div>

          {/* Failed / Stale State Error Callout */}
          {(isFailed || isStale) && (
            <div className="mt-3 p-3 rounded-lg bg-red-500/10 border border-red-500/30 text-red-400 text-xs space-y-1">
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
                  {isStale
                    ? "Pipeline stuck for > 15 minutes without progress."
                    : repo.error || "Pipeline failed during analysis"}
                </span>
              </div>
            </div>
          )}

          {/* In-progress Active Stage Indicator */}
          {!isReady && !isFailed && !isStale && (
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
            {/* Delete button: ONLY FOR ADMIN */}
            {isAdmin && (
              <button
                type="button"
                onClick={(e) => {
                  e.stopPropagation();
                  setRepoToDelete(repo);
                }}
                className="px-2.5 py-1 rounded bg-red-500/10 hover:bg-red-500/20 text-red-400 border border-red-500/30 transition-colors flex items-center gap-1.5 cursor-pointer"
                title="Delete repository (Admin only)"
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
              className="text-gray-400 hover:text-white flex items-center gap-1 transition-colors cursor-pointer"
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
  };

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
            {/* Add button only for analyst and admin */}
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

        {/* ════════════════════════════════════════════════════════════════
            SEARCH, FILTER & STALE/FAILED TOGGLE TOOLBAR
            ════════════════════════════════════════════════════════════════ */}
        <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 bg-bg-surface border border-border rounded-xl p-3 shadow-sm">
          <div className="flex items-center gap-3 flex-1 flex-wrap">
            {/* Search Input */}
            <div className="relative flex-1 min-w-[220px] max-w-sm">
              <input
                type="text"
                value={searchQuery}
                onChange={(e) => {
                  setSearchQuery(e.target.value);
                  setVisibleCount(PAGE_SIZE);
                }}
                placeholder="Search repository name or URL..."
                className="w-full bg-bg-card border border-border rounded-lg pl-8 pr-3 py-1.5 text-xs text-gray-200 placeholder-gray-500 focus:outline-none focus:ring-1 focus:ring-accent"
              />
              <svg
                className="w-3.5 h-3.5 text-gray-500 absolute left-2.5 top-2.5"
                viewBox="0 0 24 24"
                fill="none"
                stroke="currentColor"
                strokeWidth="2"
              >
                <circle cx="11" cy="11" r="8" />
                <path d="m21 21-4.35-4.35" />
              </svg>
            </div>

            {/* Status Filter */}
            <div className="flex items-center gap-1.5 text-xs text-gray-400">
              <span>Status:</span>
              <select
                value={statusFilter}
                onChange={(e) => {
                  setStatusFilter(e.target.value);
                  setVisibleCount(PAGE_SIZE);
                }}
                className="bg-bg-card border border-border rounded-lg px-2.5 py-1.5 text-xs text-white focus:outline-none focus:ring-1 focus:ring-accent cursor-pointer"
              >
                <option value="all">All Statuses ({repos.length})</option>
                <option value="ready">Ready</option>
                <option value="in_progress">In Progress</option>
                <option value="queued">Queued</option>
                <option value="failed">Failed / Stale</option>
              </select>
            </div>
          </div>

          {/* Collapsible toggle for failed / stale repos */}
          {failedOrStaleRepos.length > 0 && (
            <button
              type="button"
              onClick={() => setShowFailed(!showFailed)}
              className={`inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg border text-xs font-semibold transition-colors cursor-pointer shrink-0 ${
                showFailed
                  ? "bg-red-500/20 text-red-300 border-red-500/40"
                  : "bg-bg-card hover:bg-bg-subtle text-gray-300 border-border"
              }`}
            >
              <span>{showFailed ? "Hide failed" : "Show failed"}</span>
              <span className="px-1.5 py-0.2 rounded-full text-[10px] font-mono bg-red-500/30 text-red-300">
                {failedOrStaleRepos.length}
              </span>
              <svg
                className={`w-3.5 h-3.5 transition-transform ${showFailed ? "rotate-180" : ""}`}
                viewBox="0 0 24 24"
                fill="none"
                stroke="currentColor"
                strokeWidth="2"
              >
                <polyline points="6 9 12 15 18 9" />
              </svg>
            </button>
          )}
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
              className="px-3 py-1.5 rounded-lg bg-bg-card border border-red-500/40 text-xs text-white hover:bg-bg-subtle transition-colors cursor-pointer"
            >
              Retry
            </button>
          </div>
        )}

        {/* ════════════════════════════════════════════════════════════════
            COLLAPSIBLE FAILED / STALE REPOSITORIES SECTION
            ════════════════════════════════════════════════════════════════ */}
        {showFailed && failedOrStaleRepos.length > 0 && (
          <div className="p-5 rounded-2xl border border-red-500/30 bg-red-950/10 space-y-4">
            <div className="flex items-center justify-between">
              <h2 className="text-sm font-bold text-red-300 uppercase tracking-wider flex items-center gap-2 font-mono">
                <svg
                  className="w-4 h-4 text-red-400"
                  viewBox="0 0 24 24"
                  fill="none"
                  stroke="currentColor"
                  strokeWidth="2"
                >
                  <circle cx="12" cy="12" r="10" />
                  <line x1="12" y1="8" x2="12" y2="12" />
                  <line x1="12" y1="16" x2="12.01" y2="16" />
                </svg>
                Failed & Stale Pipelines ({failedOrStaleRepos.length})
              </h2>
              <span className="text-xs text-red-400/80">
                Repositories with ingestion errors or stuck pipelines
              </span>
            </div>

            <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-5">
              {failedOrStaleRepos.map((r) => renderRepoCard(r, true))}
            </div>
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

        {/* ════════════════════════════════════════════════════════════════
            ACTIVE & HEALTHY REPOSITORY CARDS GRID
            ════════════════════════════════════════════════════════════════ */}
        {!isLoading && !isError && repos.length > 0 && (
          <div className="space-y-6">
            {healthyOrActiveRepos.length === 0 ? (
              <div className="p-8 text-center bg-bg-surface border border-border rounded-xl text-xs text-gray-400">
                No active repositories match your filter criteria.
                {failedOrStaleRepos.length > 0 && (
                  <span className="block mt-1 text-gray-300">
                    Check &quot;Show failed ({failedOrStaleRepos.length})&quot; above to inspect failed or stale pipelines.
                  </span>
                )}
              </div>
            ) : (
              <>
                <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-5">
                  {visibleCards.map((r) => renderRepoCard(r, false))}
                </div>

                {/* Pagination / "Load more" at 12 cards */}
                {hasMore && (
                  <div className="pt-4 text-center">
                    <button
                      type="button"
                      onClick={() => setVisibleCount((prev) => prev + PAGE_SIZE)}
                      className="inline-flex items-center gap-2 px-5 py-2.5 rounded-xl bg-bg-card hover:bg-bg-subtle text-gray-200 text-xs font-semibold border border-border transition-colors shadow-sm cursor-pointer"
                    >
                      <span>
                        Load more ({healthyOrActiveRepos.length - visibleCount} remaining)
                      </span>
                      <svg
                        className="w-3.5 h-3.5"
                        viewBox="0 0 24 24"
                        fill="none"
                        stroke="currentColor"
                        strokeWidth="2"
                      >
                        <polyline points="6 9 12 15 18 9" />
                      </svg>
                    </button>
                  </div>
                )}
              </>
            )}
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

export default ReposPage;
