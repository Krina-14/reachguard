import React, { useState, useMemo } from "react";
import { useParams, Link } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { apiFetch } from "../api/client";
import { VerdictBadge } from "../components/VerdictBadge";
import { ScoreBreakdownCard } from "../components/ScoreBreakdownCard";
import { CytoscapeGraph } from "../components/CytoscapeGraph";
import { ProofPathPanel } from "../components/ProofPathPanel";
import { DecisionAndMemoryPanel } from "../components/DecisionAndMemoryPanel";
import { WhatIfPanel } from "../components/WhatIfPanel";
import { ChatPanel } from "../components/ChatPanel";
import type { FindingDetail, GraphResponse, Severity } from "../api/types";
import { useDocumentTitle } from "../lib/useDocumentTitle";

export const FindingDetailPage: React.FC = () => {
  const { repoId, findingId } = useParams<{
    repoId: string;
    findingId: string;
  }>();

  const [selectedPathIndex, setSelectedPathIndex] = useState<number>(0);

  // 1. Fetch Finding Detail
  const {
    data: finding,
    isLoading: isFindingLoading,
    isError: isFindingError,
    error: findingError,
    refetch,
  } = useQuery<FindingDetail>({
    queryKey: ["finding", repoId, findingId],
    queryFn: () =>
      apiFetch<FindingDetail>(`/api/repos/${repoId}/findings/${findingId}`),
    enabled: Boolean(repoId && findingId),
  });

  // 2. Fetch Finding Subgraph
  const {
    data: graphData,
    isLoading: isGraphLoading,
  } = useQuery<GraphResponse>({
    queryKey: ["graph", repoId, findingId],
    queryFn: () =>
      apiFetch<GraphResponse>(`/api/repos/${repoId}/graph`, {
        params: { finding_id: findingId },
      }),
    enabled: Boolean(repoId && findingId),
  });

  // Calculate active highlighted nodes & edges based on selected path
  const { activeNodeIds, activeEdgeIds } = useMemo(() => {
    if (!finding?.trace?.paths || finding.trace.paths.length === 0) {
      return {
        activeNodeIds: graphData?.highlight?.nodes || [],
        activeEdgeIds: graphData?.highlight?.edges || [],
      };
    }
    const path = finding.trace.paths[selectedPathIndex] || finding.trace.paths[0];
    return {
      activeNodeIds: path.nodes.map((n) => n.id),
      activeEdgeIds: path.edges.map((e) => e.id),
    };
  }, [finding?.trace?.paths, selectedPathIndex, graphData?.highlight]);

  const getSeverityBadge = (sev: Severity) => {
    switch (sev) {
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

  const pageTitle = finding
    ? `${finding.package || "Finding"} (${finding.severity || "CVE"})`
    : "Finding Detail";
  useDocumentTitle(pageTitle);

  if (isFindingLoading) {
    return (
      <div className="min-h-screen bg-bg p-6 md:p-8 space-y-6 max-w-7xl mx-auto animate-pulse">
        {/* Breadcrumb Skeleton */}
        <div className="h-4 bg-bg-card rounded w-64" />

        {/* Header Card Skeleton */}
        <div className="bg-bg-surface border border-border rounded-2xl p-6 md:p-8 space-y-4">
          <div className="flex flex-col md:flex-row md:items-center justify-between gap-4">
            <div className="space-y-2 flex-1">
              <div className="h-7 bg-bg-card rounded w-2/5" />
              <div className="h-4 bg-bg-card rounded w-3/5" />
            </div>
            <div className="flex gap-2">
              <div className="h-8 bg-bg-card rounded w-28" />
              <div className="h-8 bg-bg-card rounded w-24" />
            </div>
          </div>
        </div>

        {/* Two-Column Detail Grid Skeleton */}
        <div className="grid grid-cols-1 lg:grid-cols-12 gap-6">
          <div className="lg:col-span-8 space-y-6">
            <div className="bg-bg-surface border border-border rounded-xl p-6 h-96" />
            <div className="bg-bg-surface border border-border rounded-xl p-6 h-48" />
          </div>
          <div className="lg:col-span-4 space-y-6">
            <div className="bg-bg-surface border border-border rounded-xl p-6 h-64" />
            <div className="bg-bg-surface border border-border rounded-xl p-6 h-72" />
          </div>
        </div>
      </div>
    );
  }

  if (isFindingError || !finding) {
    return (
      <div className="min-h-screen bg-bg p-8 flex items-center justify-center">
        <div className="max-w-md w-full bg-bg-surface border border-red-500/30 rounded-2xl p-8 text-center space-y-4 shadow-xl">
          <div className="w-12 h-12 mx-auto rounded-full bg-red-500/10 flex items-center justify-center text-red-400">
            <svg className="w-6 h-6" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <circle cx="12" cy="12" r="10" />
              <line x1="12" y1="8" x2="12" y2="12" />
              <line x1="12" y1="16" x2="12.01" y2="16" />
            </svg>
          </div>
          <h2 className="text-xl font-bold text-white">Finding Not Found</h2>
          <p className="text-gray-400 text-xs">
            {findingError instanceof Error
              ? findingError.message
              : `Finding '${findingId}' could not be loaded.`}
          </p>
          <div className="flex items-center justify-center gap-3 pt-2">
            <Link
              to={`/repos/${repoId}`}
              className="inline-flex items-center gap-2 px-4 py-2 bg-bg-card hover:bg-bg-subtle text-gray-200 text-xs font-medium rounded-lg border border-border transition-colors"
            >
              ← Back to Repository
            </Link>
            <button
              type="button"
              onClick={() => refetch()}
              className="px-4 py-2 bg-accent hover:bg-accent-hover text-white text-xs font-semibold rounded-lg transition-colors cursor-pointer"
            >
              Retry
            </button>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-bg text-gray-200">
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-6 space-y-6">
        {/* Navigation Breadcrumb */}
        <div className="flex items-center gap-2 text-xs font-mono text-gray-400">
          <Link to="/" className="hover:text-accent transition-colors">
            Repositories
          </Link>
          <span>/</span>
          <Link to={`/repos/${repoId}`} className="hover:text-accent transition-colors">
            Repository
          </Link>
          <span>/</span>
          <span className="text-gray-200 truncate max-w-xs">{finding.vuln_id}</span>
        </div>

        {/* Page Header */}
        <div className="flex items-start justify-between flex-wrap gap-4 pb-4 border-b border-border">
          <div>
            <div className="flex items-center gap-3 flex-wrap">
              <h1 className="text-2xl font-bold font-mono text-white flex items-center gap-2">
                {finding.vuln_id}
                <a
                  href={`https://osv.dev/vulnerability/${finding.vuln_id}`}
                  target="_blank"
                  rel="noopener noreferrer"
                  title="View on OSV.dev"
                  className="text-gray-400 hover:text-accent transition-colors"
                >
                  <svg className="w-4 h-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                    <path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6" />
                    <polyline points="15 3 21 3 21 9" />
                    <line x1="10" y1="14" x2="21" y2="3" />
                  </svg>
                </a>
              </h1>
              {getSeverityBadge(finding.severity)}
              <VerdictBadge verdict={finding.verdict} />
            </div>
            {finding.summary && (
              <p className="text-sm text-gray-300 mt-2 max-w-3xl leading-relaxed">
                {finding.summary}
              </p>
            )}
          </div>

          <Link
            to={`/repos/${repoId}`}
            className="px-3 py-1.5 rounded-lg border border-border bg-bg-surface hover:bg-bg-card text-xs text-gray-300 font-medium transition-colors flex items-center gap-1.5"
          >
            ← Back to findings
          </Link>
        </div>

        {/* ════════════════════════════════════════════════════════════════
            TWO-COLUMN MAIN LAYOUT
            Left Column: Summary, Score Breakdown, Owners, Next Steps
            Right Column: Proof Paths, Graph, Verdict Cards, Decisions
            ════════════════════════════════════════════════════════════════ */}
        <div className="grid grid-cols-1 lg:grid-cols-12 gap-6 items-start">
          {/* ────────────────────────────────────────────────────────────
              LEFT COLUMN (4 Cols on lg)
              ──────────────────────────────────────────────────────────── */}
          <div className="lg:col-span-4 space-y-6">
            {/* Finding Summary Card */}
            <div className="bg-bg-surface border border-border rounded-xl p-5 shadow-sm space-y-4">
              <h3 className="text-xs font-semibold uppercase tracking-wider text-gray-400">
                Package Details
              </h3>

              <div className="space-y-3 text-xs">
                <div>
                  <span className="text-gray-400 block text-[11px] uppercase font-mono">Affected Package</span>
                  <span className="font-mono font-semibold text-white text-sm">
                    {finding.package}
                    <span className="text-accent ml-1 font-normal">@{finding.version}</span>
                  </span>
                </div>

                {finding.aliases && finding.aliases.length > 0 && (
                  <div>
                    <span className="text-gray-400 block text-[11px] uppercase font-mono mb-1">Aliases</span>
                    <div className="flex flex-wrap gap-1">
                      {finding.aliases.map((alias) => (
                        <span
                          key={alias}
                          className="px-2 py-0.5 rounded bg-bg-card border border-border text-[11px] font-mono text-gray-300"
                        >
                          {alias}
                        </span>
                      ))}
                    </div>
                  </div>
                )}

                <div>
                  <span className="text-gray-400 block text-[11px] uppercase font-mono mb-1">
                    Fixed Versions
                  </span>
                  {finding.fixed_versions && finding.fixed_versions.length > 0 ? (
                    <div className="flex flex-wrap gap-1">
                      {finding.fixed_versions.map((v) => (
                        <span
                          key={v}
                          className="px-2 py-0.5 rounded bg-emerald-500/15 border border-emerald-500/30 text-emerald-300 font-mono text-[11px] font-semibold"
                        >
                          {v}
                        </span>
                      ))}
                    </div>
                  ) : (
                    <span className="text-gray-400 text-xs italic">
                      No fixed versions recorded in OSV advisory
                    </span>
                  )}
                </div>
              </div>
            </div>

            {/* Score Breakdown Small Table */}
            {finding.score_breakdown && (
              <ScoreBreakdownCard
                score={finding.score}
                breakdown={finding.score_breakdown}
              />
            )}

            {/* Owners Card */}
            <div className="bg-bg-surface border border-border rounded-xl p-5 shadow-sm space-y-3">
              <h3 className="text-xs font-semibold uppercase tracking-wider text-gray-400 flex items-center gap-1.5">
                <svg className="w-3.5 h-3.5 text-accent" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                  <path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2" />
                  <circle cx="9" cy="7" r="4" />
                  <path d="M23 21v-2a4 4 0 0 0-3-3.87" />
                  <path d="M16 3.13a4 4 0 0 1 0 7.75" />
                </svg>
                Code Owners
              </h3>

              {finding.owners && finding.owners.length > 0 ? (
                <div className="flex flex-wrap gap-1.5">
                  {Array.from(new Set(finding.owners)).map((owner) => (
                    <span
                      key={owner}
                      className="px-2.5 py-1 rounded-full text-xs font-medium bg-slate-800 text-slate-200 border border-slate-700 inline-flex items-center gap-1.5"
                    >
                      <span className="w-1.5 h-1.5 rounded-full bg-accent" />
                      {owner}
                    </span>
                  ))}
                </div>
              ) : (
                <p className="text-xs text-gray-400 italic">
                  No owners declared in graph for modules importing this package.
                </p>
              )}
            </div>

            {/* Suggested Next Step Card (NEVER claims a fix is applied) */}
            <div className="bg-bg-surface border border-border rounded-xl p-5 shadow-sm space-y-2">
              <h3 className="text-xs font-semibold uppercase tracking-wider text-accent flex items-center gap-1.5">
                <svg className="w-4 h-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                  <circle cx="12" cy="12" r="10" />
                  <polyline points="12 6 12 12 14 14" />
                </svg>
                Suggested Next Step
              </h3>

              {finding.fixed_versions && finding.fixed_versions.length > 0 ? (
                <div className="text-xs text-gray-300 space-y-1.5">
                  <p>
                    Consider upgrading <strong>{finding.package}</strong> from{" "}
                    <code className="text-amber-400 font-mono">{finding.version}</code> to{" "}
                    <code className="text-emerald-400 font-mono">
                      {finding.fixed_versions.join(", ")}
                    </code>
                    .
                  </p>
                  <p className="text-[11px] text-gray-400 italic">
                    Verify test suites and dependency compatibility before applying version updates.
                  </p>
                </div>
              ) : (
                <div className="text-xs text-gray-300 space-y-1">
                  <p>
                    No upstream fixed version is currently listed for this vulnerability in OSV.dev.
                  </p>
                  <p className="text-[11px] text-gray-400">
                    Review whether the package usage can be isolated, or evaluate alternative libraries.
                  </p>
                </div>
              )}
            </div>
          </div>

          {/* ────────────────────────────────────────────────────────────
              RIGHT COLUMN (8 Cols on lg)
              ──────────────────────────────────────────────────────────── */}
          <div className="lg:col-span-8 space-y-6">
            {/* Proof Path Panel above the graph */}
            {finding.trace?.paths && finding.trace.paths.length > 0 && (
              <ProofPathPanel
                paths={finding.trace.paths}
                selectedPathIndex={selectedPathIndex}
                onSelectPath={setSelectedPathIndex}
              />
            )}

            {/* Cytoscape Graph Visualization */}
            <div>
              <div className="flex items-center justify-between mb-2">
                <span className="text-xs font-semibold uppercase tracking-wider text-gray-400">
                  Call Graph Subgraph Visualization
                </span>
                {graphData?.nodes && (
                  <span className="text-xs text-gray-400 font-mono">
                    {graphData.nodes.length} nodes, {graphData.edges.length} edges
                  </span>
                )}
              </div>

              {isGraphLoading ? (
                <div className="w-full h-[520px] bg-[#090d16] border border-border rounded-xl flex items-center justify-center text-gray-400 text-xs font-mono">
                  Loading graph elements...
                </div>
              ) : graphData && graphData.nodes.length > 0 ? (
                <CytoscapeGraph
                  graphData={graphData}
                  highlightedNodeIds={activeNodeIds}
                  highlightedEdgeIds={activeEdgeIds}
                />
              ) : (
                <div className="w-full h-[320px] bg-[#090d16] border border-border rounded-xl flex flex-col items-center justify-center text-gray-400 text-xs p-6 text-center">
                  <svg className="w-10 h-10 text-gray-600 mb-2" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5">
                    <circle cx="12" cy="12" r="10" />
                    <line x1="4.93" y1="4.93" x2="19.07" y2="19.07" />
                  </svg>
                  <p className="font-semibold text-gray-300">No Graph Elements to Render</p>
                  <p className="text-[11px] text-gray-500 mt-1">
                    No connected call paths or neighbor nodes were found for this package in the model.
                  </p>
                </div>
              )}
            </div>

            {/* ════════════════════════════════════════════════════════════
                CONDITIONAL VERDICT CARDS
                1. No Path Found -> Search Scope Card + Disclaimer
                2. Unknown -> Blind Spots Table
                ════════════════════════════════════════════════════════════ */}
            {finding.verdict === "no_path_found" && (
              <div className="bg-bg-surface border border-slate-700/80 rounded-xl p-5 shadow-sm space-y-4">
                <div className="flex items-center gap-2">
                  <span className="w-2.5 h-2.5 rounded-full bg-slate-400" />
                  <h3 className="text-sm font-semibold uppercase tracking-wider text-white">
                    Search Scope & Reachability Assessment
                  </h3>
                </div>

                {finding.trace?.reason === "declared_not_imported" && (
                  <div className="p-3 rounded-lg bg-amber-500/10 border border-amber-500/25 text-amber-300 text-xs">
                    This package is in the dependency file but no import of it was found.
                  </div>
                )}

                <div className="p-3.5 rounded-lg bg-bg-card border border-border text-xs text-gray-300">
                  <p className="font-medium text-amber-200 mb-1">Important Safety Notice:</p>
                  <p className="leading-relaxed">
                    This is not proof of safety. It only means no path was found in the analyzed graph.
                  </p>
                </div>

                {finding.trace?.searched_scope && (
                  <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 text-xs font-mono">
                    <div className="p-3 rounded-lg bg-bg-card border border-border">
                      <span className="text-[10px] text-gray-400 block uppercase">Modules Searched</span>
                      <span className="text-base font-bold text-white">
                        {finding.trace.searched_scope.modules}
                      </span>
                    </div>
                    <div className="p-3 rounded-lg bg-bg-card border border-border">
                      <span className="text-[10px] text-gray-400 block uppercase">Files Parsed / Failed</span>
                      <span className="text-base font-bold text-white">
                        {finding.trace.searched_scope.files_parsed} /{" "}
                        <span className="text-red-400">{finding.trace.searched_scope.files_failed}</span>
                      </span>
                    </div>
                    <div className="p-3 rounded-lg bg-bg-card border border-border">
                      <span className="text-[10px] text-gray-400 block uppercase">Lockfile Kind</span>
                      <span className="text-base font-bold text-white capitalize">
                        {finding.trace.searched_scope.lockfile_kind}
                      </span>
                    </div>
                    <div className="p-3 rounded-lg bg-bg-card border border-border">
                      <span className="text-[10px] text-gray-400 block uppercase">Transitive Available</span>
                      <span className="text-base font-bold text-white">
                        {finding.trace.searched_scope.transitive_available ? "Yes" : "No"}
                      </span>
                    </div>
                  </div>
                )}
              </div>
            )}

            {finding.verdict === "unknown" && (
              <div className="bg-bg-surface border border-amber-500/40 rounded-xl p-5 shadow-sm space-y-4">
                <div className="flex items-center justify-between">
                  <h3 className="text-sm font-semibold uppercase tracking-wider text-amber-400 flex items-center gap-2">
                    <svg className="w-4 h-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                      <polygon points="7.86 2 16.14 2 22 7.86 22 16.14 16.14 22 7.86 22 2 16.14 2 7.86 7.86 2" />
                      <line x1="12" y1="8" x2="12" y2="12" />
                      <line x1="12" y1="16" x2="12.01" y2="16" />
                    </svg>
                    Analysis Scope & Blind Spots
                  </h3>
                  <span className="text-xs text-gray-400">
                    {finding.trace?.reason === "no_entrypoints_detected"
                      ? "No entrypoints detected"
                      : `${finding.trace?.blind_spots?.length || 0} items prevent conclusive reachability`}
                  </span>
                </div>

                {finding.trace?.reason === "no_entrypoints_detected" ? (
                  <div className="p-3.5 bg-amber-500/10 border border-amber-500/25 rounded-lg text-xs text-amber-200/90 leading-relaxed">
                    <span className="font-semibold text-amber-400">No entrypoints detected: </span>
                    No public HTTP entrypoints were detected in this repository. ReachGuard marks this finding as{" "}
                    <span className="font-bold text-amber-300">Unknown</span> because reachability cannot be conclusively established without entrypoints.
                  </div>
                ) : (
                  <>
                    <p className="text-xs text-gray-300 leading-relaxed">
                      The model encountered unparsed files, dynamic imports, or unresolved references in reachable code paths:
                    </p>

                {finding.trace?.blind_spots && finding.trace.blind_spots.length > 0 ? (
                  <div className="overflow-x-auto border border-border rounded-lg">
                    <table className="w-full text-left text-xs">
                      <thead className="bg-bg-card text-gray-400 border-b border-border text-[11px]">
                        <tr>
                          <th className="py-2 px-3 font-medium">Kind</th>
                          <th className="py-2 px-3 font-medium">File</th>
                          <th className="py-2 px-3 font-medium">Line</th>
                          <th className="py-2 px-3 font-medium">Reason</th>
                        </tr>
                      </thead>
                      <tbody className="divide-y divide-border/60 font-mono text-[11px]">
                        {finding.trace.blind_spots.map((bs, idx) => (
                          <tr key={idx} className="hover:bg-bg-card/40">
                            <td className="py-2 px-3 font-semibold text-amber-300">
                              {bs.kind}
                            </td>
                            <td className="py-2 px-3 text-gray-200 break-all font-sans">
                              {bs.file}
                            </td>
                            <td className="py-2 px-3 text-gray-400">
                              {bs.line || "—"}
                            </td>
                            <td className="py-2 px-3 text-gray-300 font-sans">
                              {bs.reason}
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                ) : (
                  <p className="text-xs text-gray-400 italic">
                    No specific blind spots listed in trace data.
                  </p>
                )}
                  </>
                )}
              </div>
            )}

            {/* ════════════════════════════════════════════════════════════
                WHAT-IF SIMULATION PANEL (Analyst/Admin)
                ════════════════════════════════════════════════════════════ */}
            <WhatIfPanel
              repoId={repoId!}
              findingId={findingId!}
              currentPath={
                finding.trace?.paths
                  ? finding.trace.paths[selectedPathIndex] || finding.trace.paths[0]
                  : null
              }
              graphData={graphData}
            />

            {/* ════════════════════════════════════════════════════════════
                DECISION AND MEMORY SECTION
                ════════════════════════════════════════════════════════════ */}
            <DecisionAndMemoryPanel
              repoId={repoId!}
              findingId={findingId!}
              decisions={finding.decisions || []}
              investigations={finding.investigations || []}
              onUpdated={refetch}
            />
          </div>
        </div>

        {/* Collapsible Chat Panel on the right */}
        {repoId && (
          <ChatPanel
            repoId={repoId}
            currentFindingId={findingId}
          />
        )}
      </div>
    </div>
  );
};
