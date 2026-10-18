import React, { useState } from "react";
import { Link } from "react-router-dom";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { apiFetch } from "../../api/client";
import { VerdictBadge } from "../VerdictBadge";
import type { PendingApproval, FindingDetail } from "../../api/types";

const ProofPathSummary: React.FC<{ repoId: string; findingId: string }> = ({
  repoId,
  findingId,
}) => {
  const { data: finding, isLoading, isError } = useQuery<FindingDetail>({
    queryKey: ["finding-summary", repoId, findingId],
    queryFn: () =>
      apiFetch<FindingDetail>(`/api/repos/${repoId}/findings/${findingId}`),
  });

  if (isLoading) {
    return (
      <div className="p-3 bg-bg-card/70 border border-border/70 rounded-lg text-xs text-gray-400 font-mono animate-pulse">
        Fetching call graph & proof path summary...
      </div>
    );
  }

  if (isError || !finding) {
    return (
      <div className="p-3 bg-red-500/10 border border-red-500/25 rounded-lg text-xs text-red-400">
        Could not load proof path for finding {findingId}.
      </div>
    );
  }

  const paths = finding.trace?.paths || [];

  return (
    <div className="p-3.5 bg-bg-card/70 border border-border/70 rounded-lg text-xs space-y-2">
      <div className="flex items-center justify-between text-[11px] text-gray-400 font-mono">
        <span className="uppercase tracking-wider font-semibold text-accent flex items-center gap-1.5">
          <svg className="w-3.5 h-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
            <circle cx="5" cy="6" r="3" />
            <path d="M5 9v6" />
            <circle cx="5" cy="18" r="3" />
            <path d="M12 12h7a2 2 0 0 1 2 2v4" />
            <circle cx="19" cy="18" r="3" />
          </svg>
          Proof Path Trace
        </span>
        <span>
          {paths.length > 0
            ? `${paths.length} confirmed route(s)`
            : finding.verdict === "unknown"
            ? "Unknown verdict"
            : "No path in model"}
        </span>
      </div>

      {paths.length > 0 && paths[0]?.nodes ? (
        <div className="flex items-center flex-wrap gap-1.5 py-1 text-xs font-mono overflow-x-auto">
          {(paths[0].nodes || []).map((node, idx) => {
            const edge = paths[0]?.edges?.[idx];
            return (
              <React.Fragment key={node.id || idx}>
                <span
                  className={`px-2 py-0.5 rounded border inline-flex items-center gap-1 ${
                    node.label === "Entrypoint"
                      ? "bg-sky-500/15 border-sky-500/40 text-sky-300 font-bold"
                      : node.label === "Package"
                      ? "bg-amber-500/15 border-amber-500/40 text-amber-300 font-bold"
                      : "bg-slate-800 border-slate-700 text-slate-200"
                  }`}
                >
                  <span className="text-[10px] text-gray-400 font-sans uppercase">
                    [{node.label}]
                  </span>
                  <span>{node.name}</span>
                </span>
                {edge && <span className="text-gray-500">→</span>}
              </React.Fragment>
            );
          })}
        </div>
      ) : finding.trace?.blind_spots && finding.trace.blind_spots.length > 0 ? (
        <div className="text-[11px] text-amber-300/90 space-y-1">
          <p>
            No complete proof path could be established due to{" "}
            <strong>{finding.trace.blind_spots.length} blind spot(s)</strong>:
          </p>
          <ul className="list-disc list-inside space-y-0.5 font-mono text-[10px] text-gray-400">
            {finding.trace.blind_spots.slice(0, 3).map((bs, i) => (
              <li key={i}>
                {bs.kind} in {bs.file}: {bs.reason}
              </li>
            ))}
          </ul>
        </div>
      ) : (
        <p className="text-[11px] text-gray-400 italic">
          No confirmed call path was traced from public entrypoints to this package.
        </p>
      )}
    </div>
  );
};

export const ApprovalsPanel: React.FC = () => {
  const queryClient = useQueryClient();
  const [expandedId, setExpandedId] = useState<string | null>(null);
  const [processingId, setProcessingId] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);

  // 1. Fetch pending approvals: GET /api/decisions?status=pending
  const {
    data: pendingApprovals = [],
    isLoading,
    isError,
    error,
    refetch,
  } = useQuery<PendingApproval[]>({
    queryKey: ["admin-pending-decisions"],
    queryFn: () =>
      apiFetch<PendingApproval[]>("/api/decisions", {
        params: { status: "pending" },
      }),
    refetchInterval: 10000,
  });

  const handleApprove = async (item: PendingApproval) => {
    setProcessingId(item.id);
    setActionError(null);
    try {
      await apiFetch(
        `/api/repos/${item.repo_id}/decisions/${item.id}/approve`,
        { method: "POST" }
      );
      queryClient.invalidateQueries({ queryKey: ["admin-pending-decisions"] });
      queryClient.invalidateQueries({ queryKey: ["admin-audit"] });
    } catch (err: unknown) {
      setActionError(
        err instanceof Error ? err.message : "Failed to approve decision"
      );
    } finally {
      setProcessingId(null);
    }
  };

  const handleReject = async (item: PendingApproval) => {
    setProcessingId(item.id);
    setActionError(null);
    try {
      await apiFetch(
        `/api/repos/${item.repo_id}/decisions/${item.id}/reject`,
        { method: "POST" }
      );
      queryClient.invalidateQueries({ queryKey: ["admin-pending-decisions"] });
      queryClient.invalidateQueries({ queryKey: ["admin-audit"] });
    } catch (err: unknown) {
      setActionError(
        err instanceof Error ? err.message : "Failed to reject decision"
      );
    } finally {
      setProcessingId(null);
    }
  };

  // A pending decision may refer to a finding which has since been removed.
  // Do not let that stale record take down the administrator's entire control
  // center; it cannot be actioned until the backend can supply a finding.
  const actionableApprovals = pendingApprovals.filter(
    (item): item is PendingApproval => Boolean(item?.finding?.id)
  );

  return (
    <div className="bg-bg-surface border border-border rounded-xl p-5 shadow-sm space-y-4">
      {/* Header */}
      <div className="flex items-center justify-between pb-3 border-b border-border/70 flex-wrap gap-2">
        <div className="flex items-center gap-2.5">
          <div className="w-8 h-8 rounded-lg bg-purple-500/15 border border-purple-500/30 text-purple-400 flex items-center justify-center">
            <svg
              className="w-4 h-4"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth="2"
            >
              <path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z" />
              <path d="m9 12 2 2 4-4" />
            </svg>
          </div>
          <div>
            <h2 className="text-base font-bold text-white flex items-center gap-2">
              Approvals Queue
              <span className="px-2 py-0.2 rounded-full text-xs font-mono font-bold bg-amber-500/20 text-amber-300 border border-amber-500/35">
                {actionableApprovals.length} Pending
              </span>
            </h2>
            <p className="text-xs text-gray-400">
              Risk acceptance decisions awaiting administrator review and sign-off
            </p>
          </div>
        </div>

        <button
          type="button"
          onClick={() => refetch()}
          title="Refresh approvals"
          className="px-2.5 py-1 rounded-lg bg-bg-card hover:bg-bg-subtle text-gray-300 border border-border text-xs transition-colors cursor-pointer"
        >
          Refresh
        </button>
      </div>

      {actionError && (
        <div className="p-3 rounded-lg bg-red-500/15 border border-red-500/30 text-red-400 text-xs">
          {actionError}
        </div>
      )}

      {/* Loading State */}
      {isLoading && (
        <div className="space-y-3 animate-pulse">
          {[1, 2, 3].map((i) => (
            <div
              key={i}
              className="h-20 bg-bg-card/70 border border-border rounded-lg"
            />
          ))}
        </div>
      )}

      {/* Error State */}
      {isError && (
        <div className="p-6 rounded-lg border border-red-500/30 bg-red-500/5 text-center space-y-2">
          <p className="text-red-400 text-xs font-medium">
            Failed to load pending approval requests.
          </p>
          <p className="text-[11px] text-gray-500 font-mono">
            {error instanceof Error ? error.message : "Network error"}
          </p>
          <button
            type="button"
            onClick={() => refetch()}
            className="px-3 py-1 bg-red-600 hover:bg-red-500 text-white rounded text-xs"
          >
            Retry
          </button>
        </div>
      )}

      {/* Empty State */}
      {!isLoading && !isError && actionableApprovals.length === 0 && (
        <div className="p-8 rounded-lg border border-border/80 bg-bg-card/30 text-center space-y-2">
          <div className="w-10 h-10 mx-auto rounded-full bg-emerald-500/10 flex items-center justify-center text-emerald-400">
            <svg
              className="w-5 h-5"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth="2"
            >
              <polyline points="20 6 9 17 4 12" />
            </svg>
          </div>
          <h3 className="text-sm font-semibold text-white">
            No Pending Approvals
          </h3>
          <p className="text-xs text-gray-400 max-w-sm mx-auto">
            All risk acceptance decisions have been processed. New requests submitted by analysts will appear here.
          </p>
        </div>
      )}

      {/* Approvals List */}
      {!isLoading && !isError && actionableApprovals.length > 0 && (
        <div className="space-y-3">
          {actionableApprovals.map((item) => {
            const isExpanded = expandedId === item.id;
            const isProcessing = processingId === item.id;

            return (
              <div
                key={item.id}
                className="p-4 rounded-xl border border-border bg-bg-card/40 hover:border-gray-600 transition-all space-y-3"
              >
                {/* Main Row */}
                <div className="flex flex-col lg:flex-row lg:items-center justify-between gap-3">
                  <div className="space-y-1.5 flex-1">
                    <div className="flex items-center gap-2 flex-wrap">
                      <span className="text-xs font-bold font-mono text-white">
                        {item.finding.vuln_id}
                      </span>
                      <VerdictBadge verdict={item.finding.verdict} />
                      <span className="px-2 py-0.5 rounded text-[11px] font-mono bg-bg-card border border-border text-gray-300">
                        {item.finding.package}
                        <span className="text-accent">@{item.finding.version}</span>
                      </span>
                      <span className="text-xs text-gray-500">•</span>
                      <span className="text-xs text-gray-400 font-mono">
                        Repo:{" "}
                        <Link
                          to={`/repos/${item.repo_id}`}
                          className="text-gray-300 hover:text-accent underline"
                        >
                          {item.repo_source || item.source || item.repo_id}
                        </Link>
                      </span>
                    </div>

                    <div className="text-xs text-gray-300 flex items-center gap-2 flex-wrap">
                      <span>
                        Requested by:{" "}
                        <strong className="text-white font-mono">{item.by}</strong>
                      </span>
                      <span>•</span>
                      <span className="text-gray-400 font-mono text-[11px]">
                        {new Date(item.created_at).toLocaleString()}
                      </span>
                    </div>

                    <p className="text-xs text-gray-300 leading-relaxed font-sans bg-bg-card/60 p-2 rounded border border-border/50">
                      <span className="text-gray-400 font-semibold uppercase text-[10px] block mb-0.5">
                        Justification:
                      </span>
                      {item.reason}
                    </p>
                  </div>

                  {/* Actions & Expand Toggle */}
                  <div className="flex items-center gap-2 shrink-0 self-end lg:self-center">
                    <button
                      type="button"
                      onClick={() => setExpandedId(isExpanded ? null : item.id)}
                      className="px-2.5 py-1.5 rounded-lg border border-border bg-bg-card hover:bg-bg-subtle text-xs text-gray-300 font-medium transition-colors flex items-center gap-1 cursor-pointer"
                    >
                      <span>{isExpanded ? "Hide Trace" : "Proof Path"}</span>
                      <svg
                        className={`w-3.5 h-3.5 transition-transform ${isExpanded ? "rotate-180" : ""}`}
                        viewBox="0 0 24 24"
                        fill="none"
                        stroke="currentColor"
                        strokeWidth="2"
                      >
                        <polyline points="6 9 12 15 18 9" />
                      </svg>
                    </button>

                    <button
                      type="button"
                      disabled={isProcessing}
                      onClick={() => handleApprove(item)}
                      className="px-3 py-1.5 rounded-lg bg-emerald-600 hover:bg-emerald-500 disabled:bg-gray-700 text-white text-xs font-semibold shadow-sm transition-colors cursor-pointer"
                    >
                      {isProcessing ? "Processing..." : "Approve"}
                    </button>

                    <button
                      type="button"
                      disabled={isProcessing}
                      onClick={() => handleReject(item)}
                      className="px-3 py-1.5 rounded-lg bg-red-600 hover:bg-red-500 disabled:bg-gray-700 text-white text-xs font-semibold shadow-sm transition-colors cursor-pointer"
                    >
                      Reject
                    </button>
                  </div>
                </div>

                {/* Expanded Proof Path Summary */}
                {isExpanded && (
                  <ProofPathSummary
                    repoId={item.repo_id}
                    findingId={item.finding.id}
                  />
                )}
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
};
