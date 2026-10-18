import React, { useState, useMemo, useEffect, useRef } from "react";
import { Link } from "react-router-dom";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { apiFetch } from "../api/client";
import { useDocumentTitle } from "../lib/useDocumentTitle";
import { VerdictBadge } from "../components/VerdictBadge";
import { ScoreBreakdownCard } from "../components/ScoreBreakdownCard";
import { CytoscapeGraph } from "../components/CytoscapeGraph";
import { ProofPathPanel } from "../components/ProofPathPanel";
import { WhatIfPanel } from "../components/WhatIfPanel";
import { DecisionAndMemoryPanel } from "../components/DecisionAndMemoryPanel";
import { AddRepoModal } from "../components/AddRepoModal";
import type {
  FindingRow,
  FindingDetail,
  GraphResponse,
  GraphNode,
  GraphEdge,
  Repo,
  Severity,
} from "../api/types";

export interface TriageQueueItem extends FindingRow {
  repo_id: string;
  repo_source: string;
}

export const TriagePage: React.FC = () => {
  useDocumentTitle("Triage Queue — ReachGuard");
  const queryClient = useQueryClient();

  // State
  const [selectedRepoFilter, setSelectedRepoFilter] = useState<string>("all");
  const [selectedFindingKey, setSelectedFindingKey] = useState<string | null>(null);
  const [selectedPathIndex, setSelectedPathIndex] = useState<number>(0);
  const [isDecisionFormOpen, setIsDecisionFormOpen] = useState<boolean>(false);
  const [isAddModalOpen, setIsAddModalOpen] = useState<boolean>(false);
  const [searchFilter, setSearchFilter] = useState<string>("");

  // Refs for keyboard scroll-into-view
  const itemRefs = useRef<(HTMLDivElement | null)[]>([]);

  // 1. Fetch repositories
  const {
    data: repos = [],
    isLoading: isReposLoading,
    refetch: refetchRepos,
  } = useQuery<Repo[]>({
    queryKey: ["repos"],
    queryFn: () => apiFetch<Repo[]>("/api/repos"),
  });

  const readyRepos = useMemo(
    () => repos.filter((r) => r.status === "ready"),
    [repos]
  );

  // Target repos according to repo filter
  const reposToQuery = useMemo(() => {
    if (selectedRepoFilter === "all") {
      return readyRepos;
    }
    return readyRepos.filter((r) => r.id === selectedRepoFilter);
  }, [readyRepos, selectedRepoFilter]);

  // 2. Fetch triage queue findings:
  // GET /api/repos/{id}/findings?verdict=reachable_in_model&status=open
  // and GET /api/repos/{id}/findings?verdict=unknown&status=open
  // merged across ready repos, sorted by score
  const {
    data: rawQueueItems = [],
    isLoading: isQueueLoading,
    isFetching: isQueueFetching,
    refetch: refetchQueue,
  } = useQuery<TriageQueueItem[]>({
    queryKey: ["triage-queue", selectedRepoFilter, reposToQuery.map((r) => r.id)],
    queryFn: async () => {
      if (reposToQuery.length === 0) return [];

      const repoPromises = reposToQuery.map(async (repo) => {
        try {
          const [reachableFindings, unknownFindings] = await Promise.all([
            apiFetch<FindingRow[]>(`/api/repos/${repo.id}/findings`, {
              params: {
                verdict: "reachable_in_model",
                status: "open",
                limit: 500,
              },
            }).catch(() => [] as FindingRow[]),
            apiFetch<FindingRow[]>(`/api/repos/${repo.id}/findings`, {
              params: {
                verdict: "unknown",
                status: "open",
                limit: 500,
              },
            }).catch(() => [] as FindingRow[]),
          ]);

          const combined: TriageQueueItem[] = [
            ...reachableFindings.map((f) => ({
              ...f,
              repo_id: repo.id,
              repo_source: repo.source,
            })),
            ...unknownFindings.map((f) => ({
              ...f,
              repo_id: repo.id,
              repo_source: repo.source,
            })),
          ];

          return combined;
        } catch {
          return [] as TriageQueueItem[];
        }
      });

      const allResults = await Promise.all(repoPromises);
      const flattened = allResults.flat();

      // Deduplicate by repo_id + id
      const uniqueMap = new Map<string, TriageQueueItem>();
      for (const item of flattened) {
        const key = `${item.repo_id}:${item.id}`;
        if (!uniqueMap.has(key)) {
          uniqueMap.set(key, item);
        }
      }
      const uniqueItems = Array.from(uniqueMap.values());

      // Sort by score descending
      uniqueItems.sort((a, b) => (b.score ?? 0) - (a.score ?? 0));
      return uniqueItems;
    },
    enabled: !isReposLoading,
    refetchInterval: 10000,
  });

  // Filter items by local search text (package name or vuln id)
  const queueItems = useMemo(() => {
    if (!searchFilter.trim()) return rawQueueItems;
    const term = searchFilter.toLowerCase().trim();
    return rawQueueItems.filter(
      (item) =>
        item.package.toLowerCase().includes(term) ||
        item.vuln_id.toLowerCase().includes(term) ||
        (item.summary && item.summary.toLowerCase().includes(term))
    );
  }, [rawQueueItems, searchFilter]);

  // Determine currently selected item
  const selectedIndex = useMemo(() => {
    if (queueItems.length === 0) return -1;
    if (!selectedFindingKey) return 0;
    const idx = queueItems.findIndex(
      (item) => `${item.repo_id}:${item.id}` === selectedFindingKey
    );
    return idx >= 0 ? idx : 0;
  }, [queueItems, selectedFindingKey]);

  const selectedItem = selectedIndex >= 0 ? queueItems[selectedIndex] : null;

  // Reset path index when selected finding changes
  useEffect(() => {
    setSelectedPathIndex(0);
  }, [selectedItem?.id, selectedItem?.repo_id]);

  // 3. Fetch selected finding details
  const {
    data: findingDetail,
    isLoading: isDetailLoading,
    isError: isDetailError,
    refetch: refetchFinding,
  } = useQuery<FindingDetail>({
    queryKey: ["finding", selectedItem?.repo_id, selectedItem?.id],
    queryFn: () =>
      apiFetch<FindingDetail>(
        `/api/repos/${selectedItem!.repo_id}/findings/${selectedItem!.id}`
      ),
    enabled: Boolean(selectedItem),
  });

  // 4. Fetch finding subgraph
  const { data: graphData, isLoading: isGraphLoading } = useQuery<GraphResponse>({
    queryKey: ["graph", selectedItem?.repo_id, selectedItem?.id],
    queryFn: () =>
      apiFetch<GraphResponse>(
        `/api/repos/${selectedItem!.repo_id}/graph`,
        {
          params: { finding_id: selectedItem!.id },
        }
      ),
    enabled: Boolean(selectedItem),
  });

  // Effective graph data: prefers API subgraph, falls back cleanly to trace paths
  const effectiveGraphData: GraphResponse | undefined = useMemo(() => {
    if (graphData?.nodes && graphData.nodes.length > 0) {
      return graphData;
    }
    const paths = findingDetail?.trace?.paths;
    if (paths && paths.length > 0) {
      const nodeMap = new Map<string, GraphNode>();
      const edges: GraphEdge[] = [];
      const highlightNodeIds: string[] = [];
      const highlightEdgeIds: string[] = [];

      paths.forEach((p, pIdx) => {
        const pNodes = p.nodes || [];
        const pEdges = p.edges || [];

        pNodes.forEach((node) => {
          if (!nodeMap.has(node.id)) {
            nodeMap.set(node.id, {
              id: node.id,
              label: node.label,
              name: node.name || node.id,
              props: {},
            });
          }
          if (!highlightNodeIds.includes(node.id)) {
            highlightNodeIds.push(node.id);
          }
        });

        for (let i = 0; i < pNodes.length - 1; i++) {
          const src = pNodes[i].id;
          const dst = pNodes[i + 1].id;
          const edgeInfo = pEdges[i];
          const edgeId = edgeInfo?.id || `e_p${pIdx}_${i}_${src}_${dst}`;
          const edgeType = edgeInfo?.type || "CONNECTS_TO";

          edges.push({
            id: edgeId,
            source: src,
            target: dst,
            type: edgeType,
          });
          if (!highlightEdgeIds.includes(edgeId)) {
            highlightEdgeIds.push(edgeId);
          }
        }
      });

      if (nodeMap.size > 0) {
        return {
          nodes: Array.from(nodeMap.values()),
          edges,
          highlight: {
            nodes: highlightNodeIds,
            edges: highlightEdgeIds,
          },
        };
      }
    }
    return graphData;
  }, [graphData, findingDetail?.trace?.paths]);

  // Active highlighted graph elements based on selected path
  const { activeNodeIds, activeEdgeIds } = useMemo(() => {
    if (
      !findingDetail?.trace?.paths ||
      findingDetail.trace.paths.length === 0
    ) {
      return {
        activeNodeIds: effectiveGraphData?.highlight?.nodes || [],
        activeEdgeIds: effectiveGraphData?.highlight?.edges || [],
      };
    }
    const path =
      findingDetail.trace.paths[selectedPathIndex] ||
      findingDetail.trace.paths[0];
    return {
      activeNodeIds: (path?.nodes || []).map((n) => n.id),
      activeEdgeIds: (path?.edges || []).map((e) => e.id),
    };
  }, [findingDetail?.trace?.paths, selectedPathIndex, effectiveGraphData?.highlight]);

  // 5. Keyboard Navigation:
  // j: next item in queue
  // k: previous item in queue
  // d: opens decision form
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      // Don't intercept when user is typing in form controls
      const target = e.target as HTMLElement | null;
      const tagName = target?.tagName?.toLowerCase();
      if (
        tagName === "input" ||
        tagName === "textarea" ||
        tagName === "select" ||
        target?.isContentEditable
      ) {
        return;
      }
      if (e.metaKey || e.ctrlKey || e.altKey) {
        return;
      }
      if (isAddModalOpen) {
        return;
      }

      if (e.key === "j" || e.key === "J") {
        e.preventDefault();
        if (queueItems.length > 0) {
          const nextIdx = Math.min(queueItems.length - 1, selectedIndex + 1);
          const nextItem = queueItems[nextIdx];
          if (nextItem) {
            setSelectedFindingKey(`${nextItem.repo_id}:${nextItem.id}`);
            itemRefs.current[nextIdx]?.scrollIntoView({
              block: "nearest",
              behavior: "smooth",
            });
          }
        }
      } else if (e.key === "k" || e.key === "K") {
        e.preventDefault();
        if (queueItems.length > 0) {
          const prevIdx = Math.max(0, selectedIndex - 1);
          const prevItem = queueItems[prevIdx];
          if (prevItem) {
            setSelectedFindingKey(`${prevItem.repo_id}:${prevItem.id}`);
            itemRefs.current[prevIdx]?.scrollIntoView({
              block: "nearest",
              behavior: "smooth",
            });
          }
        }
      } else if (e.key === "d" || e.key === "D") {
        e.preventDefault();
        setIsDecisionFormOpen(true);
        setTimeout(() => {
          const container = document.getElementById("triage-decision-form");
          if (container) {
            container.scrollIntoView({ behavior: "smooth", block: "center" });
            const textarea = container.querySelector("textarea");
            if (textarea) {
              textarea.focus();
            }
          }
        }, 60);
      }
    };

    window.addEventListener("keydown", handleKeyDown);
    return () => {
      window.removeEventListener("keydown", handleKeyDown);
    };
  }, [queueItems, selectedIndex, isAddModalOpen]);

  // Severity badge helper
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

  const getScoreColor = (score: number) => {
    if (score >= 75) return "text-red-400 bg-red-500/15 border-red-500/35";
    if (score >= 45) return "text-amber-400 bg-amber-500/15 border-amber-500/35";
    return "text-slate-400 bg-slate-500/15 border-slate-500/35";
  };

  const handleFindingUpdated = () => {
    refetchFinding();
    refetchQueue();
  };

  const isLoadingInitial = isReposLoading || isQueueLoading;

  return (
    <div className="p-4 sm:p-6 lg:p-8 space-y-6 max-w-[1720px] mx-auto min-h-screen">
      {/* ════════════════════════════════════════════════════════════════
          TOP BAR & ACTION HEADER
          ════════════════════════════════════════════════════════════════ */}
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-4 pb-5 border-b border-border">
        <div>
          <div className="flex items-center gap-3">
            <h1 className="text-2xl lg:text-3xl font-bold tracking-tight text-white flex items-center gap-2.5">
              <span className="w-8 h-8 rounded-lg bg-accent/20 border border-accent/40 text-accent inline-flex items-center justify-center">
                <svg
                  className="w-5 h-5"
                  viewBox="0 0 24 24"
                  fill="none"
                  stroke="currentColor"
                  strokeWidth="2"
                  strokeLinecap="round"
                  strokeLinejoin="round"
                >
                  <path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z" />
                  <path d="m9 12 2 2 4-4" />
                </svg>
              </span>
              Triage Queue
            </h1>
            <span className="px-2.5 py-0.5 rounded-full text-xs font-mono font-semibold bg-accent/15 text-accent border border-accent/30">
              {rawQueueItems.length} Open
            </span>
          </div>
          <p className="text-xs sm:text-sm text-gray-400 mt-1 max-w-2xl">
            Prioritize and remediate reachable and unknown vulnerabilities across active repositories.
          </p>
        </div>

        {/* Top Bar Actions & Keyboard Shortcuts Hint */}
        <div className="flex items-center flex-wrap gap-2.5">
          {/* Keyboard hints badge */}
          <div className="hidden sm:flex items-center gap-2 px-3 py-1.5 rounded-lg bg-bg-card border border-border text-[11px] text-gray-400 font-mono">
            <span className="text-gray-500 font-sans">Navigate:</span>
            <kbd className="px-1.5 py-0.5 rounded bg-bg-surface border border-border text-gray-200">
              j
            </kbd>
            <kbd className="px-1.5 py-0.5 rounded bg-bg-surface border border-border text-gray-200">
              k
            </kbd>
            <span className="text-gray-500 font-sans ml-1">Decision:</span>
            <kbd className="px-1.5 py-0.5 rounded bg-bg-surface border border-border text-gray-200">
              d
            </kbd>
          </div>

          {/* Refresh queue */}
          <button
            type="button"
            onClick={() => {
              refetchRepos();
              refetchQueue();
            }}
            title="Refresh queue"
            className="p-2 rounded-lg bg-bg-card hover:bg-bg-subtle text-gray-300 border border-border transition-colors cursor-pointer"
          >
            <svg
              className={`w-4 h-4 ${isQueueFetching ? "animate-spin text-accent" : ""}`}
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth="2"
            >
              <path d="M21.5 2v6h-6M21.34 15.57a10 10 0 1 1-.57-8.38l5.67-5.67" />
            </svg>
          </button>

          {/* Top Bar Button: "Analyze a repository" */}
          <button
            type="button"
            onClick={() => setIsAddModalOpen(true)}
            className="inline-flex items-center gap-2 px-4 py-2 bg-accent hover:bg-accent-hover text-white text-xs font-semibold rounded-lg shadow-sm transition-colors cursor-pointer"
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
        </div>
      </div>

      {/* ════════════════════════════════════════════════════════════════
          REPO FILTER & SEARCH CONTROLS
          ════════════════════════════════════════════════════════════════ */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 bg-bg-surface/80 border border-border rounded-xl p-3 shadow-sm">
        <div className="flex items-center gap-3 flex-1 flex-wrap">
          {/* Repo Filter Dropdown */}
          <div className="flex items-center gap-2 min-w-[240px]">
            <span className="text-xs font-medium text-gray-400 font-sans">Repository:</span>
            <select
              value={selectedRepoFilter}
              onChange={(e) => {
                setSelectedRepoFilter(e.target.value);
                setSelectedFindingKey(null);
              }}
              className="flex-1 bg-bg-card border border-border rounded-lg px-3 py-1.5 text-xs text-gray-200 focus:outline-none focus:ring-1 focus:ring-accent cursor-pointer"
            >
              <option value="all">
                All Ready Repositories ({readyRepos.length})
              </option>
              {readyRepos.map((repo) => (
                <option key={repo.id} value={repo.id}>
                  {repo.source}
                </option>
              ))}
            </select>
          </div>

          {/* Quick Search */}
          <div className="relative flex-1 max-w-xs">
            <input
              type="text"
              value={searchFilter}
              onChange={(e) => setSearchFilter(e.target.value)}
              placeholder="Filter by package or vuln ID..."
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
        </div>

        {/* Breakdown Stats */}
        <div className="flex items-center gap-2 text-xs">
          <span className="px-2 py-0.5 rounded bg-red-500/10 text-red-400 border border-red-500/25 font-mono text-[11px]">
            {rawQueueItems.filter((i) => i.verdict === "reachable_in_model").length} Reachable
          </span>
          <span className="px-2 py-0.5 rounded bg-amber-500/10 text-amber-400 border border-amber-500/25 font-mono text-[11px]">
            {rawQueueItems.filter((i) => i.verdict === "unknown").length} Unknown
          </span>
        </div>
      </div>

      {/* ════════════════════════════════════════════════════════════════
          LOADING STATE
          ════════════════════════════════════════════════════════════════ */}
      {isLoadingInitial && (
        <div className="grid grid-cols-1 lg:grid-cols-12 gap-6 animate-pulse">
          {/* Left Column Skeleton */}
          <div className="lg:col-span-4 xl:col-span-4 space-y-3">
            {[1, 2, 3, 4, 5].map((i) => (
              <div
                key={i}
                className="h-24 bg-bg-surface border border-border rounded-xl p-4"
              />
            ))}
          </div>

          {/* Right Column Skeleton */}
          <div className="lg:col-span-8 xl:col-span-8 space-y-6">
            <div className="h-32 bg-bg-surface border border-border rounded-xl" />
            <div className="h-72 bg-bg-surface border border-border rounded-xl" />
            <div className="h-48 bg-bg-surface border border-border rounded-xl" />
          </div>
        </div>
      )}

      {/* ════════════════════════════════════════════════════════════════
          EMPTY STATE
          (When the queue has 0 open reachable or unknown findings)
          ════════════════════════════════════════════════════════════════ */}
      {!isLoadingInitial && rawQueueItems.length === 0 && (
        <div className="rounded-2xl border border-border bg-bg-surface p-12 text-center shadow-xl max-w-3xl mx-auto space-y-6 my-8">
          <div className="w-16 h-16 mx-auto rounded-2xl bg-emerald-500/10 border border-emerald-500/30 flex items-center justify-center text-emerald-400 shadow-inner">
            <svg
              className="w-8 h-8"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth="2"
              strokeLinecap="round"
              strokeLinejoin="round"
            >
              <path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z" />
              <path d="m9 12 2 2 4-4" />
            </svg>
          </div>

          <div className="space-y-2">
            <h2 className="text-xl md:text-2xl font-bold text-white">
              Nothing reachable or unknown right now
            </h2>
            <p className="text-sm text-gray-400 max-w-xl mx-auto">
              No open findings with <code>reachable_in_model</code> or{" "}
              <code>unknown</code> verdicts require triage in the selected repositories.
            </p>
          </div>

          {/* Safety Reminder */}
          <div className="p-4 rounded-xl bg-amber-500/10 border border-amber-500/25 text-amber-200/90 text-xs text-left max-w-lg mx-auto flex items-start gap-3">
            <svg
              className="w-5 h-5 text-amber-400 shrink-0 mt-0.5"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth="2"
            >
              <circle cx="12" cy="12" r="10" />
              <line x1="12" y1="8" x2="12" y2="12" />
              <line x1="12" y1="16" x2="12.01" y2="16" />
            </svg>
            <div className="space-y-1">
              <span className="font-semibold text-amber-300 block">
                Important Reminder:
              </span>
              <p className="leading-relaxed">
                This is not proof of safety. It only means no open reachable or unknown findings were identified in the current graph model.
              </p>
            </div>
          </div>

          <div className="pt-2 flex items-center justify-center gap-3">
            <button
              type="button"
              onClick={() => setIsAddModalOpen(true)}
              className="px-4 py-2 bg-accent hover:bg-accent-hover text-white text-xs font-semibold rounded-lg shadow-sm transition-colors cursor-pointer"
            >
              Analyze a repository
            </button>
            <Link
              to="/repos"
              className="px-4 py-2 bg-bg-card hover:bg-bg-subtle text-gray-300 text-xs font-medium rounded-lg border border-border transition-colors"
            >
              View all repositories
            </Link>
          </div>
        </div>
      )}

      {/* ════════════════════════════════════════════════════════════════
          TWO-COLUMN TRIAGE WORKSPACE
          Left: Queue List (package@version, vuln id, verdict badge, score)
          Right: Selected Finding's Detail in one view
          ════════════════════════════════════════════════════════════════ */}
      {!isLoadingInitial && rawQueueItems.length > 0 && (
        <div className="grid grid-cols-1 lg:grid-cols-12 gap-6 items-start">
          {/* ────────────────────────────────────────────────────────────
              LEFT COLUMN: QUEUE LIST
              ──────────────────────────────────────────────────────────── */}
          <div className="lg:col-span-4 xl:col-span-4 space-y-3">
            <div className="flex items-center justify-between px-1">
              <span className="text-xs font-semibold uppercase tracking-wider text-gray-400 font-mono">
                Queue ({queueItems.length})
              </span>
              <span className="text-[11px] text-gray-500 font-mono">
                Sorted by Score ↓
              </span>
            </div>

            {queueItems.length === 0 && searchFilter && (
              <div className="p-6 rounded-xl border border-border bg-bg-surface text-center text-xs text-gray-400">
                No queue items match filter &quot;{searchFilter}&quot;.
              </div>
            )}

            <div className="space-y-2.5 max-h-[calc(100vh-220px)] overflow-y-auto pr-1">
              {queueItems.map((item, index) => {
                const isSelected = selectedIndex === index;
                const scoreColor = getScoreColor(item.score);

                return (
                  <div
                    key={`${item.repo_id}:${item.id}`}
                    ref={(el) => (itemRefs.current[index] = el)}
                    onClick={() =>
                      setSelectedFindingKey(`${item.repo_id}:${item.id}`)
                    }
                    className={`group relative p-3.5 rounded-xl border transition-all cursor-pointer select-none ${
                      isSelected
                        ? "bg-bg-surface border-accent shadow-md ring-1 ring-accent/40"
                        : "bg-bg-surface/70 border-border hover:bg-bg-surface hover:border-gray-600"
                    }`}
                  >
                    {/* Active Indicator Bar on Left */}
                    {isSelected && (
                      <span className="absolute left-0 top-3 bottom-3 w-1 bg-accent rounded-r" />
                    )}

                    <div className="space-y-2">
                      {/* Top Row: Package@version and Score */}
                      <div className="flex items-center justify-between gap-2">
                        <div className="font-mono font-semibold text-white text-xs truncate max-w-[240px]">
                          {item.package}
                          <span className="text-accent font-normal ml-0.5">
                            @{item.version}
                          </span>
                        </div>

                        {/* Score Badge */}
                        <span
                          className={`px-2 py-0.5 rounded text-[11px] font-mono font-bold border shrink-0 ${scoreColor}`}
                        >
                          Score: {item.score}
                        </span>
                      </div>

                      {/* Middle Row: Vuln ID and Badges */}
                      <div className="flex items-center justify-between gap-2 flex-wrap">
                        <span className="text-xs font-mono text-gray-300 font-medium">
                          {item.vuln_id}
                        </span>
                        <div className="flex items-center gap-1.5 shrink-0">
                          {getSeverityBadge(item.severity)}
                          <VerdictBadge verdict={item.verdict} />
                        </div>
                      </div>

                      {/* Bottom Row: Repo Source tag */}
                      <div className="flex items-center justify-between text-[11px] text-gray-400 pt-1 border-t border-border/40">
                        <span className="truncate max-w-[200px] text-gray-400 font-mono">
                          {item.repo_source}
                        </span>
                        <span className="text-[10px] text-gray-500 font-mono">
                          #{index + 1}
                        </span>
                      </div>
                    </div>
                  </div>
                );
              })}
            </div>
          </div>

          {/* ────────────────────────────────────────────────────────────
              RIGHT COLUMN: SELECTED FINDING'S DETAIL IN ONE VIEW
              - Proof path graph (ProofPathPanel, CytoscapeGraph)
              - Score breakdown (ScoreBreakdownCard)
              - What-if buttons (WhatIfPanel)
              - Decision form & Past investigations (DecisionAndMemoryPanel)
              ──────────────────────────────────────────────────────────── */}
          <div className="lg:col-span-8 xl:col-span-8 space-y-6">
            {!selectedItem ? (
              <div className="bg-bg-surface border border-border rounded-xl p-12 text-center text-gray-400 text-sm">
                Select a finding from the triage queue to inspect its call graph and record decisions.
              </div>
            ) : isDetailLoading ? (
              <div className="bg-bg-surface border border-border rounded-xl p-8 space-y-4 animate-pulse">
                <div className="h-6 bg-bg-card rounded w-1/3" />
                <div className="h-4 bg-bg-card rounded w-2/3" />
                <div className="h-64 bg-bg-card rounded" />
              </div>
            ) : isDetailError || !findingDetail ? (
              <div className="bg-bg-surface border border-red-500/30 rounded-xl p-8 text-center space-y-3">
                <p className="text-red-400 text-sm font-semibold">
                  Failed to load finding details for {selectedItem.vuln_id}.
                </p>
                <button
                  type="button"
                  onClick={() => refetchFinding()}
                  className="px-3 py-1.5 bg-accent hover:bg-accent-hover text-white text-xs font-medium rounded-lg"
                >
                  Retry
                </button>
              </div>
            ) : (
              <div className="space-y-6">
                {/* ── 1. Detail Header ───────────────────────────────── */}
                <div className="bg-bg-surface border border-border rounded-xl p-5 shadow-sm space-y-4">
                  <div className="flex flex-col sm:flex-row sm:items-start justify-between gap-4">
                    <div className="space-y-1.5">
                      <div className="flex items-center gap-3 flex-wrap">
                        <h2 className="text-xl font-bold font-mono text-white flex items-center gap-2">
                          {findingDetail.vuln_id}
                          <a
                            href={`https://osv.dev/vulnerability/${findingDetail.vuln_id}`}
                            target="_blank"
                            rel="noopener noreferrer"
                            title="View on OSV.dev"
                            className="text-gray-400 hover:text-accent transition-colors"
                          >
                            <svg
                              className="w-4 h-4"
                              viewBox="0 0 24 24"
                              fill="none"
                              stroke="currentColor"
                              strokeWidth="2"
                            >
                              <path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6" />
                              <polyline points="15 3 21 3 21 9" />
                              <line x1="10" y1="14" x2="21" y2="3" />
                            </svg>
                          </a>
                        </h2>
                        {getSeverityBadge(findingDetail.severity)}
                        <VerdictBadge verdict={findingDetail.verdict} />
                      </div>

                      <div className="text-xs text-gray-400 font-mono flex items-center gap-2 flex-wrap">
                        <span>
                          Package:{" "}
                          <strong className="text-white">
                            {findingDetail.package}@{findingDetail.version}
                          </strong>
                        </span>
                        <span>•</span>
                        <span>
                          Repo:{" "}
                          <Link
                            to={`/repos/${selectedItem.repo_id}`}
                            className="text-accent hover:underline"
                          >
                            {selectedItem.repo_source}
                          </Link>
                        </span>
                      </div>
                    </div>

                    <div className="flex items-center gap-2 shrink-0">
                      <Link
                        to={`/repos/${selectedItem.repo_id}/findings/${selectedItem.id}`}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="px-3 py-1.5 rounded-lg border border-border bg-bg-card hover:bg-bg-subtle text-xs text-gray-300 font-medium transition-colors flex items-center gap-1.5"
                      >
                        <span>Full Page</span>
                        <svg className="w-3.5 h-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                          <path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6" />
                          <polyline points="15 3 21 3 21 9" />
                          <line x1="10" y1="14" x2="21" y2="3" />
                        </svg>
                      </Link>
                    </div>
                  </div>

                  {findingDetail.summary && (
                    <p className="text-xs sm:text-sm text-gray-300 leading-relaxed pt-2 border-t border-border/50">
                      {findingDetail.summary}
                    </p>
                  )}
                </div>

                {/* ── 2. Proof Path & Subgraph Visualization ───────────── */}
                <div className="space-y-4">
                  {/* Proof Path Panel */}
                  {findingDetail.trace?.paths &&
                    findingDetail.trace.paths.length > 0 && (
                      <ProofPathPanel
                        paths={findingDetail.trace.paths}
                        selectedPathIndex={selectedPathIndex}
                        onSelectPath={setSelectedPathIndex}
                      />
                    )}

                  {/* Cytoscape Graph */}
                  <div>
                    <div className="flex items-center justify-between mb-2">
                      <span className="text-xs font-semibold uppercase tracking-wider text-gray-400">
                        Call Graph Subgraph Visualization
                      </span>
                      {Array.isArray(effectiveGraphData?.nodes) && (
                        <span className="text-xs text-gray-400 font-mono">
                          {effectiveGraphData.nodes.length} nodes, {effectiveGraphData.edges?.length || 0} edges
                        </span>
                      )}
                    </div>

                    {isGraphLoading ? (
                      <div className="w-full h-[400px] bg-[#090d16] border border-border rounded-xl flex items-center justify-center text-gray-400 text-xs font-mono">
                        Loading graph elements...
                      </div>
                    ) : Array.isArray(effectiveGraphData?.nodes) && effectiveGraphData.nodes.length > 0 ? (
                      <CytoscapeGraph
                        graphData={effectiveGraphData}
                        highlightedNodeIds={activeNodeIds}
                        highlightedEdgeIds={activeEdgeIds}
                      />
                    ) : (
                      <div className="w-full h-[260px] bg-[#090d16] border border-border rounded-xl flex flex-col items-center justify-center text-gray-400 text-xs p-6 text-center">
                        <svg
                          className="w-10 h-10 text-gray-600 mb-2"
                          viewBox="0 0 24 24"
                          fill="none"
                          stroke="currentColor"
                          strokeWidth="1.5"
                        >
                          <circle cx="12" cy="12" r="10" />
                          <line x1="4.93" y1="4.93" x2="19.07" y2="19.07" />
                        </svg>
                        <p className="font-semibold text-gray-300">
                          No Graph Elements to Render
                        </p>
                        <p className="text-[11px] text-gray-500 mt-1">
                          No connected call paths or neighbor nodes were found for this package in the model.
                        </p>
                      </div>
                    )}
                  </div>

                  {/* Conditional Unknown Blind Spots or Search Scope */}
                  {findingDetail.verdict === "unknown" && (
                    <div className="bg-bg-surface border border-amber-500/40 rounded-xl p-5 shadow-sm space-y-4">
                      <div className="flex items-center justify-between">
                        <h3 className="text-sm font-semibold uppercase tracking-wider text-amber-400 flex items-center gap-2">
                          <svg
                            className="w-4 h-4"
                            viewBox="0 0 24 24"
                            fill="none"
                            stroke="currentColor"
                            strokeWidth="2"
                          >
                            <polygon points="7.86 2 16.14 2 22 7.86 22 16.14 16.14 22 7.86 22 2 16.14 2 7.86 7.86 2" />
                            <line x1="12" y1="8" x2="12" y2="12" />
                            <line x1="12" y1="16" x2="12.01" y2="16" />
                          </svg>
                          Analysis Scope & Blind Spots
                        </h3>
                        <span className="text-xs text-gray-400">
                          {findingDetail.trace?.reason === "no_entrypoints_detected"
                            ? "No entrypoints detected"
                            : `${findingDetail.trace?.blind_spots?.length || 0} blind spots`}
                        </span>
                      </div>

                      {findingDetail.trace?.reason === "no_entrypoints_detected" ? (
                        <div className="p-3.5 bg-amber-500/10 border border-amber-500/25 rounded-lg text-xs text-amber-200/90 leading-relaxed">
                          <span className="font-semibold text-amber-400">
                            No entrypoints detected:{" "}
                          </span>
                          No public HTTP entrypoints were detected in this repository. ReachGuard marks this finding as{" "}
                          <span className="font-bold text-amber-300">Unknown</span> because reachability cannot be conclusively established without entrypoints.
                        </div>
                      ) : (
                        findingDetail.trace?.blind_spots &&
                        findingDetail.trace.blind_spots.length > 0 && (
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
                                {findingDetail.trace.blind_spots.map((bs, idx) => (
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
                        )
                      )}
                    </div>
                  )}
                </div>

                {/* ── 3. Score Breakdown Card ─────────────────────────── */}
                {findingDetail.score_breakdown && (
                  <ScoreBreakdownCard
                    score={findingDetail.score}
                    breakdown={findingDetail.score_breakdown}
                  />
                )}

                {/* ── 4. What-If Simulation Panel ─────────────────────── */}
                <WhatIfPanel
                  repoId={selectedItem.repo_id}
                  findingId={selectedItem.id}
                  currentPath={
                    findingDetail.trace?.paths
                      ? findingDetail.trace.paths[selectedPathIndex] ||
                        findingDetail.trace.paths[0]
                      : null
                  }
                  graphData={effectiveGraphData}
                />

                {/* ── 5. Decision Form & Past Investigations ─────────── */}
                <DecisionAndMemoryPanel
                  repoId={selectedItem.repo_id}
                  findingId={selectedItem.id}
                  decisions={findingDetail.decisions || []}
                  investigations={findingDetail.investigations || []}
                  onUpdated={handleFindingUpdated}
                  isFormOpen={isDecisionFormOpen}
                  onToggleForm={setIsDecisionFormOpen}
                  formId="triage-decision-form"
                />
              </div>
            )}
          </div>
        </div>
      )}

      {/* ════════════════════════════════════════════════════════════════
          ADD / ANALYZE REPOSITORY MODAL
          ════════════════════════════════════════════════════════════════ */}
      <AddRepoModal
        isOpen={isAddModalOpen}
        onClose={() => {
          setIsAddModalOpen(false);
          // Refetch repos and queue after modal closes or repo added
          queryClient.invalidateQueries({ queryKey: ["repos"] });
          queryClient.invalidateQueries({ queryKey: ["triage-queue"] });
        }}
      />
    </div>
  );
};

export default TriagePage;
