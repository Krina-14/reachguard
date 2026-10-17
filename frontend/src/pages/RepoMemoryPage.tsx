import React, { useState, useMemo } from "react";
import { useParams, Link } from "react-router-dom";
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

export const RepoMemoryPage: React.FC = () => {
  const { repoId } = useParams<{ repoId: string }>();
  const [filter, setFilter] = useState<TimelineFilter>("all");

  // 1. Fetch Repo info for header/breadcrumbs
  const { data: repo } = useQuery<Repo>({
    queryKey: ["repo", repoId],
    queryFn: () => apiFetch<Repo>(`/api/repos/${repoId}`),
    enabled: Boolean(repoId),
  });

  useDocumentTitle(repo ? `Memory — ${repo.source}` : "Memory Timeline");

  // 2. Fetch Memory (investigations and decisions)
  const {
    data: memoryData,
    isLoading,
    isError,
    error,
    refetch,
  } = useQuery<MemoryResponse>({
    queryKey: ["repo-memory", repoId],
    queryFn: () => apiFetch<MemoryResponse>(`/api/repos/${repoId}/memory`),
    enabled: Boolean(repoId),
  });

  // 3. Merge investigations and decisions into a single timeline, sorted newest first
  const timeline = useMemo<TimelineItem[]>(() => {
    if (!memoryData) return [];

    const items: TimelineItem[] = [];

    if (memoryData.investigations) {
      for (const inv of memoryData.investigations) {
        items.push({
          id: `inv-${inv.id}`,
          kind: "investigation",
          created_at: inv.created_at,
          by: inv.by || "analyst",
          finding_id: inv.finding_id,
          timestamp: new Date(inv.created_at).getTime() || 0,
          data: inv,
        });
      }
    }

    if (memoryData.decisions) {
      for (const dec of memoryData.decisions) {
        items.push({
          id: `dec-${dec.id}`,
          kind: "decision",
          created_at: dec.created_at,
          by: dec.by || "analyst",
          finding_id: dec.finding_id,
          timestamp: new Date(dec.created_at).getTime() || 0,
          data: dec,
        });
      }
    }

    // Sort newest first
    return items.sort((a, b) => b.timestamp - a.timestamp);
  }, [memoryData]);

  // Filtered timeline
  const filteredTimeline = useMemo(() => {
    if (filter === "investigations") {
      return timeline.filter((item) => item.kind === "investigation");
    }
    if (filter === "decisions") {
      return timeline.filter((item) => item.kind === "decision");
    }
    return timeline;
  }, [timeline, filter]);

  const formatDate = (dateStr: string) => {
    try {
      const d = new Date(dateStr);
      if (isNaN(d.getTime())) return dateStr;
      return d.toLocaleString(undefined, {
        month: "short",
        day: "numeric",
        year: "numeric",
        hour: "2-digit",
        minute: "2-digit",
      });
    } catch {
      return dateStr;
    }
  };

  const formatDecisionType = (type: string) => {
    switch (type) {
      case "accept_risk":
        return "Accept Risk";
      case "fix_planned":
        return "Fix Planned";
      case "false_positive":
        return "False Positive";
      case "fixed":
        return "Fixed";
      default:
        return type.replace(/_/g, " ");
    }
  };

  const getDecisionStatusBadge = (status: string) => {
    switch (status) {
      case "approved":
        return (
          <span className="px-2 py-0.5 rounded text-[10px] font-bold bg-emerald-500/15 text-emerald-300 border border-emerald-500/30 uppercase">
            Approved
          </span>
        );
      case "rejected":
        return (
          <span className="px-2 py-0.5 rounded text-[10px] font-bold bg-red-500/15 text-red-300 border border-red-500/30 uppercase">
            Rejected
          </span>
        );
      case "pending":
      default:
        return (
          <span className="px-2 py-0.5 rounded text-[10px] font-bold bg-amber-500/15 text-amber-300 border border-amber-500/30 uppercase">
            Pending
          </span>
        );
    }
  };

  return (
    <div className="min-h-screen bg-bg text-gray-200">
      <div className="max-w-6xl mx-auto px-4 sm:px-6 lg:px-8 py-6 space-y-6">
        {/* Navigation Breadcrumbs */}
        <div className="flex items-center gap-2 text-xs font-mono text-gray-400">
          <Link to="/" className="hover:text-accent transition-colors">
            Repositories
          </Link>
          <span>/</span>
          <Link to={`/repos/${repoId}`} className="hover:text-accent transition-colors truncate max-w-xs">
            {repo?.source || "Repository"}
          </Link>
          <span>/</span>
          <span className="text-gray-200">Memory Timeline</span>
        </div>

        {/* Page Header */}
        <div className="flex items-start justify-between flex-wrap gap-4 pb-4 border-b border-border">
          <div>
            <h1 className="text-2xl font-bold font-mono text-white flex items-center gap-2.5">
              <span className="p-1.5 rounded-lg bg-accent/15 text-accent border border-accent/25">
                <svg className="w-5 h-5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                  <path d="M12 8v4l3 3" />
                  <circle cx="12" cy="12" r="10" />
                </svg>
              </span>
              Repository Memory Timeline
            </h1>
            <p className="text-xs text-gray-400 mt-1 max-w-2xl leading-relaxed">
              Historical record of AI triage investigations, analyst decisions, and risk acceptances persisted in the graph knowledge memory.
            </p>
          </div>

          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={() => refetch()}
              className="px-3 py-1.5 rounded-lg border border-border bg-bg-surface hover:bg-bg-card text-xs text-gray-300 font-medium transition-colors flex items-center gap-1.5"
            >
              <svg className="w-3.5 h-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                <path d="M3 12a9 9 0 1 0 9-9 9.75 9.75 0 0 0-6.74 2.74L3 8" />
                <path d="M3 3v5h5" />
              </svg>
              Refresh
            </button>
            <Link
              to={`/repos/${repoId}`}
              className="px-3 py-1.5 rounded-lg border border-border bg-bg-surface hover:bg-bg-card text-xs text-gray-300 font-medium transition-colors"
            >
              ← Back to Repository
            </Link>
          </div>
        </div>

        {/* Filters Row */}
        <div className="flex items-center justify-between flex-wrap gap-3 pb-2">
          <div className="flex items-center gap-1.5 bg-bg-surface p-1 rounded-lg border border-border">
            <button
              type="button"
              onClick={() => setFilter("all")}
              className={`px-3 py-1 rounded text-xs font-medium transition-all ${
                filter === "all"
                  ? "bg-accent text-white shadow font-semibold"
                  : "text-gray-400 hover:text-white"
              }`}
            >
              All Events ({timeline.length})
            </button>
            <button
              type="button"
              onClick={() => setFilter("investigations")}
              className={`px-3 py-1 rounded text-xs font-medium transition-all ${
                filter === "investigations"
                  ? "bg-accent text-white shadow font-semibold"
                  : "text-gray-400 hover:text-white"
              }`}
            >
              Investigations ({memoryData?.investigations?.length || 0})
            </button>
            <button
              type="button"
              onClick={() => setFilter("decisions")}
              className={`px-3 py-1 rounded text-xs font-medium transition-all ${
                filter === "decisions"
                  ? "bg-accent text-white shadow font-semibold"
                  : "text-gray-400 hover:text-white"
              }`}
            >
              Decisions ({memoryData?.decisions?.length || 0})
            </button>
          </div>

          {timeline.length > 0 && (
            <span className="text-xs text-gray-400 font-mono">
              Showing {filteredTimeline.length} of {timeline.length} items (newest first)
            </span>
          )}
        </div>

        {/* Loading Skeletons */}
        {isLoading && (
          <div className="space-y-4 animate-pulse">
            {[1, 2, 3].map((i) => (
              <div
                key={i}
                className="bg-bg-surface border border-border rounded-xl p-5 space-y-3"
              >
                <div className="flex items-center justify-between">
                  <div className="h-4 bg-bg-card rounded w-48" />
                  <div className="h-4 bg-bg-card rounded w-24" />
                </div>
                <div className="h-3 bg-bg-card rounded w-full" />
                <div className="h-3 bg-bg-card rounded w-3/4" />
              </div>
            ))}
          </div>
        )}

        {/* Error State with Retry Button */}
        {isError && (
          <div className="p-6 rounded-xl bg-red-500/10 border border-red-500/30 text-center space-y-3">
            <p className="text-sm font-semibold text-red-200">Failed to Load Memory Timeline</p>
            <p className="text-xs text-red-300">
              {error instanceof Error ? error.message : "Network error"}
            </p>
            <div>
              <button
                type="button"
                onClick={() => refetch()}
                className="px-4 py-2 bg-accent hover:bg-accent-hover text-white text-xs font-semibold rounded-lg transition-colors cursor-pointer"
              >
                Retry
              </button>
            </div>
          </div>
        )}

        {/* Empty State */}
        {!isLoading && !isError && timeline.length === 0 && (
          <div className="p-12 rounded-2xl bg-bg-surface border border-border text-center space-y-4 max-w-2xl mx-auto shadow-sm">
            <div className="w-14 h-14 mx-auto rounded-full bg-accent/10 border border-accent/25 flex items-center justify-center text-accent">
              <svg className="w-7 h-7" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.75">
                <path d="M12 8v4l3 3" />
                <circle cx="12" cy="12" r="10" />
                <path d="M19 19h-6a2 2 0 0 1-2-2V5" />
              </svg>
            </div>
            <div className="space-y-1.5">
              <h3 className="text-base font-bold text-white">No Memory Records Found</h3>
              <p className="text-xs text-gray-300 leading-relaxed max-w-lg mx-auto">
                Nothing saved yet. Investigations appear here when an analyst chats with saving enabled or records a decision.
              </p>
            </div>
            <div className="pt-2">
              <Link
                to={`/repos/${repoId}`}
                className="inline-flex items-center gap-1.5 px-4 py-2 rounded-lg bg-accent hover:bg-accent-hover text-white text-xs font-semibold shadow-md transition-all"
              >
                Go to Repository Findings
              </Link>
            </div>
          </div>
        )}

        {/* Filtered Empty State */}
        {!isLoading && !isError && timeline.length > 0 && filteredTimeline.length === 0 && (
          <div className="p-8 rounded-xl bg-bg-surface border border-border text-center text-xs text-gray-400">
            No items matching the selected filter ({filter}).
          </div>
        )}

        {/* Timeline List */}
        {!isLoading && !isError && filteredTimeline.length > 0 && (
          <div className="relative border-l-2 border-border/70 ml-4 sm:ml-6 pl-6 sm:pl-8 space-y-6">
            {filteredTimeline.map((item) => {
              const isInv = item.kind === "investigation";

              return (
                <div key={item.id} className="relative group">
                  {/* Timeline Dot Indicator */}
                  <span
                    className={`absolute -left-[31px] sm:-left-[39px] top-1.5 w-4 h-4 rounded-full border-2 border-bg ${
                      isInv
                        ? "bg-sky-400 ring-4 ring-sky-500/10"
                        : "bg-amber-400 ring-4 ring-amber-500/10"
                    }`}
                  />

                  {/* Timeline Item Card */}
                  <div className="bg-bg-surface border border-border hover:border-gray-600 rounded-xl p-5 shadow-sm space-y-3 transition-colors">
                    {/* Header Row: Kind Badge, Who, When */}
                    <div className="flex items-center justify-between flex-wrap gap-2 pb-2 border-b border-border/70">
                      <div className="flex items-center gap-2">
                        {isInv ? (
                          <span className="px-2 py-0.5 rounded text-[10px] font-bold bg-sky-500/15 text-sky-300 border border-sky-500/35 uppercase flex items-center gap-1">
                            <span className="w-1.5 h-1.5 rounded-full bg-sky-400" />
                            Investigation
                          </span>
                        ) : (
                          <span className="px-2 py-0.5 rounded text-[10px] font-bold bg-amber-500/15 text-amber-300 border border-amber-500/35 uppercase flex items-center gap-1">
                            <span className="w-1.5 h-1.5 rounded-full bg-amber-400" />
                            Decision
                          </span>
                        )}

                        <span className="text-xs font-semibold text-gray-200">
                          {item.by}
                        </span>
                      </div>

                      <span className="text-[11px] font-mono text-gray-400">
                        {formatDate(item.created_at)}
                      </span>
                    </div>

                    {/* Meta Row: Finding link, Verdict or Decision Type/Status */}
                    <div className="flex items-center flex-wrap gap-3 text-xs">
                      {/* Finding Link */}
                      {item.finding_id ? (
                        <div className="flex items-center gap-1.5">
                          <span className="text-gray-400 text-[11px] uppercase">Finding:</span>
                          <Link
                            to={`/repos/${repoId}/findings/${item.finding_id}`}
                            className="font-mono font-semibold text-accent hover:underline bg-accent/10 px-1.5 py-0.5 rounded border border-accent/25 hover:bg-accent/20 transition-colors"
                            title={`Navigate to finding ${item.finding_id}`}
                          >
                            {item.finding_id}
                          </Link>
                        </div>
                      ) : (
                        <span className="text-gray-500 text-[11px] italic">
                          Repository-wide
                        </span>
                      )}

                      {/* Investigation Specifics */}
                      {isInv && (
                        <div className="flex items-center gap-2">
                          <span className="text-gray-400 text-[11px] uppercase">Verdict:</span>
                          <VerdictBadge verdict={item.data.verdict} />
                          {item.data.score !== undefined && (
                            <span className="text-[11px] font-mono text-gray-300 bg-bg-card px-1.5 py-0.5 rounded border border-border">
                              Score: {item.data.score}
                            </span>
                          )}
                        </div>
                      )}

                      {/* Decision Specifics */}
                      {!isInv && (
                        <div className="flex items-center flex-wrap gap-2">
                          <span className="text-gray-400 text-[11px] uppercase">Action:</span>
                          <span className="px-2 py-0.5 rounded text-[11px] font-medium bg-bg-card border border-border text-gray-200">
                            {formatDecisionType(item.data.type)}
                          </span>
                          {getDecisionStatusBadge(item.data.status)}
                          {item.data.approved_by && (
                            <span className="text-[10px] text-gray-400 font-mono">
                              (by {item.data.approved_by})
                            </span>
                          )}
                        </div>
                      )}
                    </div>

                    {/* Summary or Reason */}
                    <div className="text-xs text-gray-300 leading-relaxed bg-bg-card/70 p-3 rounded-lg border border-border/70 break-words whitespace-pre-wrap">
                      {isInv
                        ? item.data.summary || "No summary provided."
                        : item.data.reason || "No reason recorded."}
                    </div>
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
