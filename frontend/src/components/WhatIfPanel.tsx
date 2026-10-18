import React, { useState, useMemo } from "react";
import { apiFetch } from "../api/client";
import { useCan } from "../auth/useCan";
import { VerdictBadge } from "./VerdictBadge";
import { CytoscapeGraph } from "./CytoscapeGraph";
import { ApiError } from "../api/types";
import type {
  TracePath,
  TraceResult,
  GraphResponse,
  WhatIfChange,
  WhatIfRequest,
  WhatIfResponse,
} from "../api/types";

interface WhatIfPanelProps {
  repoId: string;
  findingId: string;
  currentPath?: TracePath | null;
  graphData?: GraphResponse;
}

interface UsesEdgeItem {
  moduleId: string;
  moduleName: string;
  packageId: string;
  packageName: string;
  edgeId: string;
}

export const WhatIfPanel: React.FC<WhatIfPanelProps> = ({
  repoId,
  findingId,
  currentPath,
  graphData,
}) => {
  const { canSave } = useCan(); // Only analyst and admin canSave

  const [activeChange, setActiveChange] = useState<WhatIfChange | null>(null);
  const [isSimulating, setIsSimulating] = useState(false);
  const [simulationResult, setSimulationResult] = useState<WhatIfResponse | null>(null);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);


  // 1. Extract public entrypoints on the current proof path
  const publicEntrypoints = useMemo(() => {
    if (!currentPath) return [];

    const eps: Array<{ id: string; name: string }> = [];
    const seen = new Set<string>();

    if (currentPath.nodes) {
      for (const node of currentPath.nodes) {
        if (node.label === "Entrypoint" && !seen.has(node.id)) {
          seen.add(node.id);
          eps.push({ id: node.id, name: node.name || node.id });
        }
      }
    }

    // Fallback if no node was explicitly labeled Entrypoint but entrypoint_id is defined
    if (eps.length === 0 && currentPath.entrypoint_id) {
      eps.push({
        id: currentPath.entrypoint_id,
        name: currentPath.entrypoint || currentPath.entrypoint_id,
      });
    }

    return eps;
  }, [currentPath]);

  // 2. Extract module -> package USES edges on the current proof path
  const usesEdges = useMemo(() => {
    if (!currentPath?.nodes || !currentPath?.edges) return [];

    const items: UsesEdgeItem[] = [];
    const seen = new Set<string>();

    for (let i = 0; i < currentPath.edges.length; i++) {
      const edge = currentPath.edges[i];
      const source = currentPath.nodes[i];
      const target = currentPath.nodes[i + 1];

      if (!source || !target) continue;

      const isUses =
        edge?.type?.toUpperCase() === "USES" ||
        (source.label === "Module" && target.label === "Package");

      if (isUses) {
        const key = `${source.id}->${target.id}`;
        if (!seen.has(key)) {
          seen.add(key);
          items.push({
            moduleId: source.id,
            moduleName: source.name || source.id,
            packageId: target.id,
            packageName: target.name || target.id,
            edgeId: edge.id,
          });
        }
      }
    }

    return items;
  }, [currentPath]);

  // Execute simulation
  const handleSimulate = async (change: WhatIfChange) => {
    setIsSimulating(true);
    setErrorMessage(null);
    setActiveChange(change);

    const payload: WhatIfRequest = {
      finding_id: findingId,
      changes: [change],
    };

    try {
      const res = await apiFetch<WhatIfResponse>(`/api/repos/${repoId}/whatif`, {
        method: "POST",
        body: JSON.stringify(payload),
      });
      setSimulationResult(res);
    } catch (err: unknown) {
      setSimulationResult(null);
      if (err instanceof ApiError) {
        if (err.statusCode === 422) {
          setErrorMessage(
            `Invalid simulation change (422): ${err.message || "Unknown entity or invalid change specification."}`
          );
        } else if (
          err.statusCode === 501 ||
          (err.statusCode === 500 &&
            (err.message.toLowerCase().includes("copy") ||
              err.message.toLowerCase().includes("not supported") ||
              err.message.toLowerCase().includes("notimplemented")))
        ) {
          setErrorMessage(
            `Graph copy unsupported (${err.statusCode}): Temporary graph copying is not supported in this database environment.`
          );
        } else if (err.statusCode === 500) {
          setErrorMessage(
            `Simulation failed (500): Server encountered an error processing graph copy or query.`
          );
        } else {
          setErrorMessage(`Simulation error (${err.statusCode}): ${err.message}`);
        }
      } else if (err instanceof Error) {
        setErrorMessage(`Simulation error: ${err.message}`);
      } else {
        setErrorMessage("An unexpected error occurred during what-if simulation.");
      }
    } finally {
      setIsSimulating(false);
    }
  };

  const handleReset = () => {
    setSimulationResult(null);
    setActiveChange(null);
    setErrorMessage(null);
  };

  // Prepare graph elements for the after-graph Cytoscape instance
  const afterGraphData: GraphResponse = useMemo(() => {
    if (!graphData) return { nodes: [], edges: [] };

    let nodes = Array.isArray(graphData.nodes) ? [...graphData.nodes] : [];
    let edges = Array.isArray(graphData.edges) ? [...graphData.edges] : [];

    if (activeChange) {
      if (activeChange.type === "remove_import") {
        const { module_id, package_id } = activeChange;
        edges = edges.filter(
          (e) =>
            !(
              e.type === "USES" &&
              ((e.source === module_id && e.target === package_id) ||
                (e.source === package_id && e.target === module_id))
            )
        );
      } else if (activeChange.type === "add_auth") {
        const { entrypoint_id } = activeChange;
        nodes = nodes.map((n) =>
          n.id === entrypoint_id
            ? { ...n, props: { ...n.props, public: false } }
            : n
        );
      }
    }

    return {
      ...graphData,
      nodes,
      edges,
    };
  }, [graphData, activeChange]);

  // Extract after-path node and edge highlights
  const { afterHighlightedNodeIds, afterHighlightedEdgeIds } = useMemo(() => {
    if (!simulationResult?.after || !("paths" in simulationResult.after)) {
      return { afterHighlightedNodeIds: [], afterHighlightedEdgeIds: [] };
    }
    const afterTrace = simulationResult.after as TraceResult;
    const paths = afterTrace.paths || [];
    const nodeIds = new Set<string>();
    const edgeIds = new Set<string>();

    for (const p of paths) {
      if (p.nodes) {
        for (const n of p.nodes) {
          nodeIds.add(n.id);
        }
      }
      if (p.edges) {
        for (const e of p.edges) {
          edgeIds.add(e.id);
        }
      }
    }

    return {
      afterHighlightedNodeIds: Array.from(nodeIds),
      afterHighlightedEdgeIds: Array.from(edgeIds),
    };
  }, [simulationResult]);

  // Type-guard trace result
  const beforeTrace =
    simulationResult?.before && "verdict" in simulationResult.before
      ? (simulationResult.before as TraceResult)
      : null;

  const afterTrace =
    simulationResult?.after && "verdict" in simulationResult.after
      ? (simulationResult.after as TraceResult)
      : null;

  const hasSimulatableItems = publicEntrypoints.length > 0 || usesEdges.length > 0;

  // If user is not analyst or admin, do not render panel
  if (!canSave) {
    return null;
  }

  return (
    <div className="bg-bg-surface border border-border rounded-xl p-5 shadow-sm space-y-5">
      {/* Panel Header */}
      <div className="flex items-center justify-between flex-wrap gap-2 pb-3 border-b border-border">
        <div className="flex items-center gap-2">
          <span className="p-1.5 rounded-lg bg-accent/15 text-accent border border-accent/25">
            <svg className="w-4 h-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <path d="M12 2v4M12 18v4M4.93 4.93l2.83 2.83M16.24 16.24l2.83 2.83M2 12h4M18 12h4M4.93 19.07l2.83-2.83M16.24 7.76l2.83-2.83" />
            </svg>
          </span>
          <div>
            <h3 className="text-sm font-bold uppercase tracking-wider text-white">
              What-If Simulation
            </h3>
            <p className="text-xs text-gray-400">
              Hypothetical reachability analysis for analyst & admin
            </p>
          </div>
        </div>

        {simulationResult && (
          <button
            type="button"
            onClick={handleReset}
            className="px-2.5 py-1 text-xs rounded border border-border bg-bg-card hover:bg-slate-700 text-gray-300 transition-colors flex items-center gap-1.5"
          >
            <svg className="w-3.5 h-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <path d="M3 12a9 9 0 1 0 9-9 9.75 9.75 0 0 0-6.74 2.74L3 8" />
              <path d="M3 3v5h5" />
            </svg>
            Reset Simulation
          </button>
        )}
      </div>

      {/* Error Message Box */}
      {errorMessage && (
        <div className="p-3.5 rounded-lg bg-red-500/10 border border-red-500/30 text-xs text-red-300 flex items-start justify-between gap-3 animate-fade-in">
          <div className="flex items-start gap-2">
            <svg className="w-4 h-4 text-red-400 shrink-0 mt-0.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <circle cx="12" cy="12" r="10" />
              <line x1="12" y1="8" x2="12" y2="12" />
              <line x1="12" y1="16" x2="12.01" y2="16" />
            </svg>
            <div>
              <p className="font-semibold text-red-200">Simulation Error</p>
              <p className="mt-0.5 leading-relaxed text-red-300">{errorMessage}</p>
            </div>
          </div>
          <button
            type="button"
            onClick={() => setErrorMessage(null)}
            className="text-red-400 hover:text-red-200 p-0.5"
            title="Dismiss error"
          >
            ✕
          </button>
        </div>
      )}

      {/* Available Simulation Actions from Current Proof Path */}
      {!simulationResult && (
        <div className="space-y-4">
          <p className="text-xs text-gray-300">
            Select an architectural mitigation below to simulate its impact on this vulnerability's reachability:
          </p>

          {!hasSimulatableItems ? (
            <div className="p-4 rounded-lg bg-bg-card border border-border/70 text-center text-xs text-gray-400 italic">
              No public entrypoints or module-to-package USES edges found on the selected proof path to simulate.
            </div>
          ) : (
            <div className="space-y-4">
              {/* 1. Public Entrypoints */}
              {publicEntrypoints.length > 0 && (
                <div className="space-y-2">
                  <div className="flex items-center gap-1.5 text-xs font-semibold uppercase tracking-wider text-sky-400">
                    <span className="w-2 h-2 rounded-full bg-sky-400" />
                    Public Entrypoints on Current Path
                  </div>
                  <div className="flex flex-col gap-2">
                    {publicEntrypoints.map((ep) => (
                      <div
                        key={ep.id}
                        className="flex items-center justify-between flex-wrap gap-2 p-3 rounded-lg bg-bg-card/80 border border-border hover:border-sky-500/40 transition-colors"
                      >
                        <div className="flex items-center gap-2 min-w-0">
                          <span className="px-2 py-0.5 rounded text-[10px] font-mono bg-sky-500/20 text-sky-300 border border-sky-500/35 uppercase">
                            Entrypoint
                          </span>
                          <span className="font-mono text-xs font-medium text-white truncate">
                            {ep.name}
                          </span>
                        </div>
                        <button
                          type="button"
                          disabled={isSimulating}
                          onClick={() =>
                            handleSimulate({ type: "add_auth", entrypoint_id: ep.id })
                          }
                          className="px-3 py-1.5 rounded-lg bg-sky-600 hover:bg-sky-500 disabled:opacity-50 text-white text-xs font-medium transition-all shadow-sm flex items-center gap-1.5"
                        >
                          {isSimulating && activeChange?.type === "add_auth" ? (
                            <>
                              <svg className="animate-spin h-3.5 w-3.5 text-white" viewBox="0 0 24 24" fill="none">
                                <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                                <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z" />
                              </svg>
                              <span>Simulating...</span>
                            </>
                          ) : (
                            <span>Simulate: add authentication to {ep.name}</span>
                          )}
                        </button>
                      </div>
                    ))}
                  </div>
                </div>
              )}

              {/* 2. Module -> Package USES Edges */}
              {usesEdges.length > 0 && (
                <div className="space-y-2">
                  <div className="flex items-center gap-1.5 text-xs font-semibold uppercase tracking-wider text-amber-400">
                    <span className="w-2 h-2 rounded-full bg-amber-400" />
                    Module → Package USES Edges on Current Path
                  </div>
                  <div className="flex flex-col gap-2">
                    {usesEdges.map((edge) => (
                      <div
                        key={edge.edgeId}
                        className="flex items-center justify-between flex-wrap gap-2 p-3 rounded-lg bg-bg-card/80 border border-border hover:border-amber-500/40 transition-colors"
                      >
                        <div className="flex items-center gap-1.5 text-xs font-mono min-w-0">
                          <span className="text-gray-300 font-medium truncate max-w-xs">
                            {edge.moduleName}
                          </span>
                          <span className="text-amber-400 text-[10px] px-1 bg-amber-500/10 rounded">
                            USES
                          </span>
                          <span className="text-gray-400">→</span>
                          <span className="text-amber-300 font-semibold truncate max-w-xs">
                            {edge.packageName}
                          </span>
                        </div>
                        <button
                          type="button"
                          disabled={isSimulating}
                          onClick={() =>
                            handleSimulate({
                              type: "remove_import",
                              module_id: edge.moduleId,
                              package_id: edge.packageId,
                            })
                          }
                          className="px-3 py-1.5 rounded-lg bg-amber-600 hover:bg-amber-500 disabled:opacity-50 text-white text-xs font-medium transition-all shadow-sm flex items-center gap-1.5"
                        >
                          {isSimulating && activeChange?.type === "remove_import" ? (
                            <>
                              <svg className="animate-spin h-3.5 w-3.5 text-white" viewBox="0 0 24 24" fill="none">
                                <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                                <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z" />
                              </svg>
                              <span>Simulating...</span>
                            </>
                          ) : (
                            <span>
                              Simulate: remove import of {edge.packageName} from {edge.moduleName}
                            </span>
                          )}
                        </button>
                      </div>
                    ))}
                  </div>
                </div>
              )}
            </div>
          )}
        </div>
      )}

      {/* Simulation Results (Side-by-Side Comparison) */}
      {simulationResult && (
        <div className="space-y-4">
          {/* Simulation Disclaimer Banner */}
          <div className="flex items-center gap-2.5 p-3 rounded-lg bg-blue-500/15 border border-blue-500/35 text-xs text-blue-200 shadow-sm">
            <svg className="w-4 h-4 text-blue-400 shrink-0" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <circle cx="12" cy="12" r="10" />
              <line x1="12" y1="16" x2="12" y2="12" />
              <line x1="12" y1="8" x2="12.01" y2="8" />
            </svg>
            <span className="font-semibold tracking-wide">
              Simulation on a temporary copy. Nothing was changed.
            </span>
          </div>

          {/* Side by Side Grid */}
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4 items-start">
            {/* ── BEFORE COLUMN ── */}
            <div className="p-4 rounded-xl bg-bg-card border border-border space-y-3">
              <div className="flex items-center justify-between pb-2 border-b border-border/70">
                <span className="text-xs font-bold uppercase tracking-wider text-gray-400 flex items-center gap-1.5">
                  <span className="w-2 h-2 rounded-full bg-gray-400" />
                  Before Simulation
                </span>
                {beforeTrace && <VerdictBadge verdict={beforeTrace.verdict} />}
              </div>

              {beforeTrace ? (
                <div className="space-y-3 text-xs">
                  <div className="flex items-center justify-between py-1 bg-bg-surface/50 px-2.5 rounded border border-border/50 font-mono">
                    <span className="text-gray-400">Active Proof Paths</span>
                    <span className="font-bold text-white">
                      {beforeTrace.paths?.length || 0}
                    </span>
                  </div>

                  <div className="flex items-center justify-between py-1 bg-bg-surface/50 px-2.5 rounded border border-border/50 font-mono">
                    <span className="text-gray-400">Reaching Entrypoints</span>
                    <span className="font-bold text-white">
                      {beforeTrace.reaching_entrypoints} / {beforeTrace.total_public_entrypoints}
                    </span>
                  </div>

                  {beforeTrace.paths?.[0] && (
                    <div className="pt-1 text-[11px] text-gray-400">
                      <span className="block uppercase text-[10px] text-gray-400 mb-1">
                        Initial Route
                      </span>
                      <span className="font-mono text-gray-300 break-all bg-bg-surface px-2 py-1 rounded block border border-border/40">
                        {beforeTrace.paths[0].entrypoint} → {findingId}
                      </span>
                    </div>
                  )}
                </div>
              ) : (
                <p className="text-xs text-gray-400 italic">No trace baseline recorded.</p>
              )}
            </div>

            {/* ── AFTER COLUMN ── */}
            <div className="p-4 rounded-xl bg-bg-card border border-accent/40 space-y-3 shadow-md">
              <div className="flex items-center justify-between pb-2 border-b border-border/70">
                <span className="text-xs font-bold uppercase tracking-wider text-accent flex items-center gap-1.5">
                  <span className="w-2 h-2 rounded-full bg-accent animate-pulse" />
                  After Simulation
                </span>
                {afterTrace && <VerdictBadge verdict={afterTrace.verdict} />}
              </div>

              {afterTrace ? (
                <div className="space-y-3 text-xs">
                  <div className="flex items-center justify-between py-1 bg-bg-surface/50 px-2.5 rounded border border-border/50 font-mono">
                    <span className="text-gray-400">Remaining Proof Paths</span>
                    <span
                      className={`font-bold ${
                        afterTrace.paths?.length === 0
                          ? "text-emerald-400 font-extrabold"
                          : "text-amber-400"
                      }`}
                    >
                      {afterTrace.paths?.length || 0}
                    </span>
                  </div>

                  <div className="flex items-center justify-between py-1 bg-bg-surface/50 px-2.5 rounded border border-border/50 font-mono">
                    <span className="text-gray-400">Reaching Entrypoints</span>
                    <span
                      className={`font-bold ${
                        afterTrace.reaching_entrypoints === 0
                          ? "text-emerald-400"
                          : "text-amber-400"
                      }`}
                    >
                      {afterTrace.reaching_entrypoints} / {afterTrace.total_public_entrypoints}
                    </span>
                  </div>

                  {/* Verdict Transition Highlight */}
                  {beforeTrace && beforeTrace.verdict !== afterTrace.verdict && (
                    <div className="p-2 rounded bg-emerald-500/10 border border-emerald-500/30 text-emerald-300 text-[11px] font-medium flex items-center gap-1.5">
                      <svg className="w-3.5 h-3.5 shrink-0" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                        <polyline points="20 6 9 17 4 12" />
                      </svg>
                      <span>
                        Verdict improved: <strong>{beforeTrace.verdict}</strong> →{" "}
                        <strong>{afterTrace.verdict}</strong>
                      </span>
                    </div>
                  )}

                  {/* After-Graph Highlight Visualization */}
                  <div className="pt-2 space-y-1.5">
                    <div className="flex items-center justify-between">
                      <span className="text-[11px] font-semibold uppercase tracking-wider text-gray-400">
                        After-Graph Highlight
                      </span>
                      {afterTrace.paths?.length === 0 ? (
                        <span className="text-[10px] text-emerald-400 font-semibold uppercase">
                          Paths Eliminated
                        </span>
                      ) : (
                        <span className="text-[10px] text-amber-400 font-mono">
                          {afterHighlightedNodeIds.length} highlighted
                        </span>
                      )}
                    </div>

                    <div className="rounded-lg overflow-hidden border border-border">
                      <CytoscapeGraph
                        graphData={afterGraphData}
                        highlightedNodeIds={afterHighlightedNodeIds}
                        highlightedEdgeIds={afterHighlightedEdgeIds}
                        height="260px"
                        compact={true}
                        showLegend={false}
                      />
                    </div>
                  </div>
                </div>
              ) : (
                <p className="text-xs text-gray-400 italic">No after-trace data returned.</p>
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  );
};
