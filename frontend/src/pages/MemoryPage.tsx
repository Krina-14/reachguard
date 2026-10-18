import React, { useState, useMemo } from "react";
import { Link } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { apiFetch } from "../api/client";
import { VerdictBadge } from "../components/VerdictBadge";
import type {
  MemoryResponse,
  Investigation,
  Decision,
  Repo,
} from "../api/types";
import { useDocumentTitle } from "../lib/useDocumentTitle";

type TimelineFilter = "all" | "investigations" | "decisions";

interface TimelineItemBase {
  id: string;
  created_at: string;
  by: string;
  finding_id?: string;
  timestamp: number;
}

interface InvestigationTimelineItem extends TimelineItemBase {
  kind: "investigation";
  data: Investigation;
}

interface DecisionTimelineItem extends TimelineItemBase {
  kind: "decision";
  data: Decision;
}

type TimelineItem = InvestigationTimelineItem | DecisionTimelineItem;

export const MemoryPage: React.FC = () => {
  useDocumentTitle("Memory Timeline");

  const [selectedRepoId, setSelectedRepoId] = useState<string>("");
  const [filter, setFilter] = useState<TimelineFilter>("all");

  // Fetch all repos to allow choosing a repo or default to the first one
  const { data: repos = [], isLoading: isReposLoading } = useQuery<Repo[]>({
    queryKey: ["repos"],
    queryFn: () => apiFetch<Repo[]>("/api/repos"),
  });

  // Effective repo id
  const effectiveRepoId = selectedRepoId || (repos.length > 0 ? repos[0].id : "");

  // Fetch memory for the selected repo
  const {
    data: memoryData,
    isLoading: isMemoryLoading,
    isError,
    refetch,
  } = useQuery<MemoryResponse>({
    queryKey: ["repo-memory", effectiveRepoId],
    queryFn: () => apiFetch<MemoryResponse>(`/api/repos/${effectiveRepoId}/memory`),
    enabled: Boolean(effectiveRepoId),
  });

  const timelineItems: TimelineItem[] = useMemo(() => {
    if (!memoryData) return [];

    const investigations: TimelineItem[] = (memoryData.investigations || []).map(
      (inv) => ({
        id: inv.id,
        created_at: inv.created_at,
        by: inv.by,
        finding_id: inv.finding_id,
        timestamp: new Date(inv.created_at).getTime() || 0,
        kind: "investigation" as const,
        data: inv,
      })
    );

    const decisions: TimelineItem[] = (memoryData.decisions || []).map((dec) => ({
      id: dec.id,
      created_at: dec.created_at,
      by: dec.by,
      finding_id: dec.finding_id,
      timestamp: new Date(dec.created_at).getTime() || 0,
      kind: "decision" as const,
      data: dec,
    }));

    const combined = [...investigations, ...decisions];
    combined.sort((a, b) => b.timestamp - a.timestamp);

    if (filter === "investigations") {
      return combined.filter((i) => i.kind === "investigation");
    }
    if (filter === "decisions") {
      return combined.filter((i) => i.kind === "decision");
    }
    return combined;
  }, [memoryData, filter]);

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

  const getDecisionStatusBadge = (status: string) => {
    switch (status) {
      case "approved":
        return (
          <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-semibold bg-emerald-500/15 text-emerald-400 border border-emerald-500/30">
            Approved
          </span>
        );
      case "pending":
        return (
          <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-semibold bg-amber-500/15 text-amber-400 border border-amber-500/30">
            Pending Approval
          </span>
        );
      case "rejected":
        return (
          <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-semibold bg-red-500/15 text-red-400 border border-red-500/30">
            Rejected
          </span>
        );
      default:
        return (
          <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-semibold bg-slate-500/15 text-slate-400 border border-slate-500/30">
            {status}
          </span>
        );
    }
  };

  const selectedRepo = repos.find((r) => r.id === effectiveRepoId);

  return (
    <div className="p-6 md:p-8 space-y-6">
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 pb-4 border-b border-border">
        <div>
          <h1 className="text-2xl md:text-3xl font-bold tracking-tight text-white">
            Memory
          </h1>
          <p className="text-sm text-gray-400 mt-1">
            Chronological audit trail of AI investigations and triage decisions
          </p>
        </div>

        {/* Repository Switcher */}
        {repos.length > 0 && (
          <div className="flex items-center gap-2">
            <label htmlFor="memory-repo-select" className="text-xs text-gray-400 font-medium">
              Repository:
            </label>
            <select
              id="memory-repo-select"
              value={effectiveRepoId}
              onChange={(e) => setSelectedRepoId(e.target.value)}
              className="px-3 py-1.5 bg-bg-surface border border-border rounded-lg text-xs text-white focus:outline-none focus:ring-1 focus:ring-accent"
            >
              {repos.map((r) => (
                <option key={r.id} value={r.id}>
                  {r.source}
                </option>
              ))}
            </select>
          </div>
        )}
      </div>

      {/* Filter Tabs */}
      {effectiveRepoId && (
        <div className="flex items-center gap-2 border-b border-border/70 pb-3">
          <button
            type="button"
            onClick={() => setFilter("all")}
            className={`px-3 py-1.5 rounded-lg text-xs font-medium transition-colors ${
              filter === "all"
                ? "bg-accent text-white"
                : "text-gray-400 hover:text-gray-200 hover:bg-bg-card"
            }`}
          >
            All Activity
          </button>
          <button
            type="button"
            onClick={() => setFilter("investigations")}
            className={`px-3 py-1.5 rounded-lg text-xs font-medium transition-colors ${
              filter === "investigations"
                ? "bg-accent text-white"
                : "text-gray-400 hover:text-gray-200 hover:bg-bg-card"
            }`}
          >
            Investigations ({memoryData?.investigations?.length || 0})
          </button>
          <button
            type="button"
            onClick={() => setFilter("decisions")}
            className={`px-3 py-1.5 rounded-lg text-xs font-medium transition-colors ${
              filter === "decisions"
                ? "bg-accent text-white"
                : "text-gray-400 hover:text-gray-200 hover:bg-bg-card"
            }`}
          >
            Decisions ({memoryData?.decisions?.length || 0})
          </button>
        </div>
      )}

      {/* Loading state */}
      {(isReposLoading || (effectiveRepoId && isMemoryLoading)) && (
        <div className="space-y-4">
          {[1, 2, 3].map((i) => (
            <div
              key={i}
              className="bg-bg-surface border border-border rounded-xl p-5 animate-pulse space-y-3"
            >
              <div className="h-4 bg-bg-card rounded w-1/4" />
              <div className="h-4 bg-bg-card rounded w-3/4" />
            </div>
          ))}
        </div>
      )}

      {/* Error state */}
      {isError && (
        <div className="p-4 rounded-xl bg-red-500/10 border border-red-500/30 text-red-400 flex items-center justify-between">
          <span className="text-sm">Failed to load memory timeline.</span>
          <button
            type="button"
            onClick={() => refetch()}
            className="px-3 py-1 bg-red-500/20 text-red-300 text-xs rounded hover:bg-red-500/30"
          >
            Retry
          </button>
        </div>
      )}

      {/* Empty state when no repos exist */}
      {!isReposLoading && repos.length === 0 && (
        <div className="bg-bg-surface border border-border rounded-xl p-12 text-center shadow-xl">
          <div className="w-12 h-12 mx-auto mb-3 rounded-lg bg-bg-card border border-border flex items-center justify-center text-gray-400">
            <svg className="w-6 h-6" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <circle cx="12" cy="12" r="10" />
              <polyline points="12 6 12 12 16 14" />
            </svg>
          </div>
          <h2 className="text-base font-semibold text-white mb-1">Nothing saved yet</h2>
          <p className="text-xs text-gray-400 max-w-md mx-auto">
            Nothing saved yet. Investigations appear here when an analyst chats with saving enabled or records a decision.
          </p>
        </div>
      )}

      {/* Empty state when repo has no memory records */}
      {!isMemoryLoading && effectiveRepoId && timelineItems.length === 0 && (
        <div className="bg-bg-surface border border-border rounded-xl p-12 text-center shadow-xl">
          <div className="w-12 h-12 mx-auto mb-3 rounded-lg bg-bg-card border border-border flex items-center justify-center text-gray-400">
            <svg className="w-6 h-6" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <circle cx="12" cy="12" r="10" />
              <polyline points="12 6 12 12 16 14" />
            </svg>
          </div>
          <h2 className="text-base font-semibold text-white mb-1">Nothing saved yet</h2>
          <p className="text-xs text-gray-400 max-w-md mx-auto">
            Nothing saved yet. Investigations appear here when an analyst chats with saving enabled or records a decision.
          </p>
        </div>
      )}

      {/* Timeline items list */}
      {!isMemoryLoading && timelineItems.length > 0 && (
        <div className="space-y-4">
          {timelineItems.map((item) => (
            <div
              key={item.id}
              className="bg-bg-surface border border-border rounded-xl p-5 shadow-lg space-y-3"
            >
              <div className="flex flex-wrap items-center justify-between gap-2 border-b border-border/60 pb-3">
                <div className="flex items-center gap-2">
                  <span
                    className={`text-[10px] uppercase font-mono font-bold px-2 py-0.5 rounded ${
                      item.kind === "investigation"
                        ? "bg-purple-500/15 text-purple-300 border border-purple-500/30"
                        : "bg-blue-500/15 text-blue-300 border border-blue-500/30"
                    }`}
                  >
                    {item.kind}
                  </span>
                  <span className="text-xs text-gray-400">by {item.by}</span>
                  <span className="text-xs text-gray-500">•</span>
                  <span className="text-xs text-gray-400">{formatDate(item.created_at)}</span>
                </div>

                {item.kind === "decision" && (
                  <div>{getDecisionStatusBadge(item.data.status)}</div>
                )}
              </div>

              {item.kind === "investigation" ? (
                <div className="space-y-2">
                  <div className="flex items-center gap-3">
                    {item.data.verdict && <VerdictBadge verdict={item.data.verdict} />}
                    {typeof item.data.score === "number" && (
                      <span className="text-xs font-mono text-gray-300">
                        Score: {item.data.score}
                      </span>
                    )}
                  </div>
                  <p className="text-xs text-gray-300 leading-relaxed bg-bg-card/50 p-3 rounded-lg border border-border/50">
                    {item.data.summary}
                  </p>
                </div>
              ) : (
                <div className="space-y-2">
                  <div className="text-xs text-gray-300 font-mono">
                    Type: <span className="font-semibold text-white">{item.data.type}</span>
                  </div>
                  <p className="text-xs text-gray-300 leading-relaxed bg-bg-card/50 p-3 rounded-lg border border-border/50">
                    {item.data.reason}
                  </p>
                </div>
              )}

              {item.finding_id && selectedRepo && (
                <div className="pt-1">
                  <Link
                    to={`/repos/${selectedRepo.id}/findings/${item.finding_id}`}
                    className="text-xs text-accent hover:underline inline-flex items-center gap-1 font-mono"
                  >
                    View finding: {item.finding_id} →
                  </Link>
                </div>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  );
};

export default MemoryPage;
