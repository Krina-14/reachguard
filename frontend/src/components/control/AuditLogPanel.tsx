import React, { useState, useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
import { apiFetch } from "../../api/client";
import type { AuditEvent } from "../../api/types";

export const AuditLogPanel: React.FC = () => {
  const [filterText, setFilterText] = useState("");

  // 1. Fetch Audit Events: GET /api/admin/audit?limit=200
  const {
    data: auditEvents = [],
    isLoading,
    isError,
    error,
    refetch,
  } = useQuery<AuditEvent[]>({
    queryKey: ["admin-audit"],
    queryFn: () =>
      apiFetch<AuditEvent[]>("/api/admin/audit", {
        params: { limit: 200 },
      }),
    refetchInterval: 10000,
  });

  // Filter events by search text
  const filteredEvents = useMemo(() => {
    if (!filterText.trim()) return auditEvents;
    const term = filterText.toLowerCase().trim();
    return auditEvents.filter(
      (ev) =>
        ev.actor.toLowerCase().includes(term) ||
        ev.action.toLowerCase().includes(term) ||
        ev.target.toLowerCase().includes(term)
    );
  }, [auditEvents, filterText]);

  const getActionBadge = (action: string) => {
    const act = action.toUpperCase();
    if (act.includes("APPROVE") || act.includes("CREATE")) {
      return (
        <span className="px-2 py-0.5 rounded text-[10px] font-bold font-mono bg-emerald-500/15 text-emerald-400 border border-emerald-500/30 uppercase">
          {action}
        </span>
      );
    }
    if (act.includes("REJECT") || act.includes("DELETE") || act.includes("DEACTIVATE")) {
      return (
        <span className="px-2 py-0.5 rounded text-[10px] font-bold font-mono bg-red-500/15 text-red-400 border border-red-500/30 uppercase">
          {action}
        </span>
      );
    }
    if (act.includes("UPDATE") || act.includes("PATCH") || act.includes("ROLE")) {
      return (
        <span className="px-2 py-0.5 rounded text-[10px] font-bold font-mono bg-amber-500/15 text-amber-300 border border-amber-500/30 uppercase">
          {action}
        </span>
      );
    }
    return (
      <span className="px-2 py-0.5 rounded text-[10px] font-bold font-mono bg-cyan-500/15 text-cyan-300 border border-cyan-500/30 uppercase">
        {action}
      </span>
    );
  };

  const formatTimestamp = (dateStr: string) => {
    const d = new Date(dateStr);
    if (isNaN(d.getTime())) return dateStr;
    return d.toLocaleString();
  };

  return (
    <div className="bg-bg-surface border border-border rounded-xl p-5 shadow-sm space-y-4">
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 pb-3 border-b border-border/70">
        <div className="flex items-center gap-2.5">
          <div className="w-8 h-8 rounded-lg bg-cyan-500/15 border border-cyan-500/30 text-cyan-400 flex items-center justify-center">
            <svg
              className="w-4 h-4"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth="2"
            >
              <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
              <polyline points="14 2 14 8 20 8" />
              <line x1="16" y1="13" x2="8" y2="13" />
              <line x1="16" y1="17" x2="8" y2="17" />
              <polyline points="10 9 9 9 8 9" />
            </svg>
          </div>
          <div>
            <h2 className="text-base font-bold text-white flex items-center gap-2">
              Security Audit Log
              <span className="px-2 py-0.2 rounded-full text-xs font-mono font-bold bg-cyan-500/20 text-cyan-300 border border-cyan-500/35">
                {auditEvents.length} Events
              </span>
            </h2>
            <p className="text-xs text-gray-400">
              Immutable record of system actions, risk acceptances, and account alterations
            </p>
          </div>
        </div>

        {/* Text Filter & Refresh */}
        <div className="flex items-center gap-2.5">
          <div className="relative">
            <input
              type="text"
              value={filterText}
              onChange={(e) => setFilterText(e.target.value)}
              placeholder="Filter by actor, action, target..."
              className="w-56 sm:w-64 bg-bg-card border border-border rounded-lg pl-8 pr-3 py-1.5 text-xs text-gray-200 placeholder-gray-500 focus:outline-none focus:ring-1 focus:ring-accent"
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

          <button
            type="button"
            onClick={() => refetch()}
            title="Refresh audit log"
            className="px-2.5 py-1.5 rounded-lg bg-bg-card hover:bg-bg-subtle text-gray-300 border border-border text-xs transition-colors cursor-pointer"
          >
            Refresh
          </button>
        </div>
      </div>

      {/* Loading State */}
      {isLoading && (
        <div className="space-y-2 animate-pulse">
          {[1, 2, 3, 4, 5].map((i) => (
            <div key={i} className="h-10 bg-bg-card/70 border border-border rounded-lg" />
          ))}
        </div>
      )}

      {/* Error State */}
      {isError && !isLoading && (
        <div className="p-6 rounded-lg border border-red-500/30 bg-red-500/5 text-center space-y-2">
          <p className="text-red-400 text-xs font-medium">Failed to retrieve audit log events.</p>
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
      {!isLoading && !isError && filteredEvents.length === 0 && (
        <div className="p-8 rounded-lg border border-border/80 bg-bg-card/30 text-center space-y-2">
          <p className="text-sm font-semibold text-white">
            {filterText ? "No Matching Audit Events" : "No Audit Events Recorded"}
          </p>
          <p className="text-xs text-gray-400">
            {filterText
              ? `No events match "${filterText}". Try clearing your filter query.`
              : "Administrative and governance actions will be captured here."}
          </p>
        </div>
      )}

      {/* Audit Events Table */}
      {!isLoading && !isError && filteredEvents.length > 0 && (
        <div className="border border-border/70 rounded-xl overflow-x-auto max-h-[460px] overflow-y-auto">
          <table className="w-full text-left text-xs">
            <thead className="bg-bg-card text-gray-400 border-b border-border/70 text-[11px] sticky top-0 z-10">
              <tr>
                <th className="py-2.5 px-3 font-medium">Timestamp</th>
                <th className="py-2.5 px-3 font-medium">Actor</th>
                <th className="py-2.5 px-3 font-medium">Action</th>
                <th className="py-2.5 px-3 font-medium">Target</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-border/50 font-mono text-[11px]">
              {filteredEvents.map((ev) => (
                <tr key={ev.id} className="hover:bg-bg-card/40 transition-colors">
                  <td className="py-2.5 px-3 text-gray-400 whitespace-nowrap">
                    {formatTimestamp(ev.at)}
                  </td>
                  <td className="py-2.5 px-3 font-semibold text-gray-200 font-sans">
                    {ev.actor}
                  </td>
                  <td className="py-2.5 px-3 whitespace-nowrap">
                    {getActionBadge(ev.action)}
                  </td>
                  <td className="py-2.5 px-3 text-gray-300 break-all font-sans">
                    {ev.target || "—"}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
};
