import React, { useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { useDocumentTitle } from "../lib/useDocumentTitle";
import { ApprovalsPanel } from "../components/control/ApprovalsPanel";
import { SystemHealthPanel } from "../components/control/SystemHealthPanel";
import { CompactUsersPanel } from "../components/control/CompactUsersPanel";
import { AuditLogPanel } from "../components/control/AuditLogPanel";

type ActiveTab = "all" | "approvals" | "health" | "users" | "audit";

export const ControlCenterPage: React.FC = () => {
  useDocumentTitle("Control Center — ReachGuard");
  const queryClient = useQueryClient();
  const [activeTab, setActiveTab] = useState<ActiveTab>("all");
  const [isRefreshing, setIsRefreshing] = useState(false);

  const handleRefreshAll = async () => {
    setIsRefreshing(true);
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: ["admin-pending-decisions"] }),
      queryClient.invalidateQueries({ queryKey: ["backend-health"] }),
      queryClient.invalidateQueries({ queryKey: ["repos"] }),
      queryClient.invalidateQueries({ queryKey: ["admin-users"] }),
      queryClient.invalidateQueries({ queryKey: ["admin-audit"] }),
    ]);
    setTimeout(() => setIsRefreshing(false), 300);
  };

  return (
    <div className="p-4 sm:p-6 lg:p-8 space-y-6 max-w-[1720px] mx-auto min-h-screen">
      {/* ════════════════════════════════════════════════════════════════
          PAGE HEADER
          ════════════════════════════════════════════════════════════════ */}
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-4 pb-5 border-b border-border">
        <div>
          <div className="flex items-center gap-3">
            <h1 className="text-2xl lg:text-3xl font-bold tracking-tight text-white flex items-center gap-2.5">
              <span className="w-8 h-8 rounded-lg bg-red-500/15 border border-red-500/30 text-red-400 inline-flex items-center justify-center">
                <svg
                  className="w-5 h-5"
                  viewBox="0 0 24 24"
                  fill="none"
                  stroke="currentColor"
                  strokeWidth="2"
                  strokeLinecap="round"
                  strokeLinejoin="round"
                >
                  <circle cx="12" cy="12" r="3" />
                  <path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1 0 2.83 2 2 0 0 1-2.83 0l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-2 2 2 2 0 0 1-2-2v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83 0 2 2 0 0 1 0-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1-2-2 2 2 0 0 1 2-2h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 0-2.83 2 2 0 0 1 2.83 0l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 2-2 2 2 0 0 1 2 2v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 0 2 2 0 0 1 0 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 2 2 2 2 0 0 1-2 2h-.09a1.65 1.65 0 0 0-1.51 1z" />
                </svg>
              </span>
              Control Center
            </h1>
            <span className="px-2.5 py-0.5 rounded-full text-xs font-mono font-semibold bg-red-500/15 text-red-400 border border-red-500/30 uppercase">
              Admin Only
            </span>
          </div>
          <p className="text-xs sm:text-sm text-gray-400 mt-1 max-w-2xl">
            Administrative command center: decision approvals, system health diagnostics, user management, and audit records.
          </p>
        </div>

        <button
          type="button"
          onClick={handleRefreshAll}
          className="inline-flex items-center gap-2 px-3.5 py-2 bg-bg-card hover:bg-bg-subtle text-gray-200 text-xs font-medium rounded-lg border border-border transition-colors cursor-pointer self-start md:self-auto"
        >
          <svg
            className={`w-3.5 h-3.5 ${isRefreshing ? "animate-spin text-accent" : ""}`}
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            strokeWidth="2"
          >
            <path d="M21.5 2v6h-6M21.34 15.57a10 10 0 1 1-.57-8.38l5.67-5.67" />
          </svg>
          <span>Refresh All</span>
        </button>
      </div>

      {/* ════════════════════════════════════════════════════════════════
          PANEL SELECTION TABS
          ════════════════════════════════════════════════════════════════ */}
      <div className="flex items-center gap-1.5 p-1 bg-bg-surface border border-border rounded-xl text-xs overflow-x-auto">
        <button
          type="button"
          onClick={() => setActiveTab("all")}
          className={`px-3.5 py-1.5 rounded-lg font-medium transition-all cursor-pointer whitespace-nowrap ${
            activeTab === "all"
              ? "bg-accent text-white shadow-sm font-semibold"
              : "text-gray-400 hover:text-gray-200"
          }`}
        >
          All Panels (4)
        </button>
        <button
          type="button"
          onClick={() => setActiveTab("approvals")}
          className={`px-3.5 py-1.5 rounded-lg font-medium transition-all cursor-pointer whitespace-nowrap flex items-center gap-1.5 ${
            activeTab === "approvals"
              ? "bg-purple-600 text-white shadow-sm font-semibold"
              : "text-gray-400 hover:text-gray-200"
          }`}
        >
          <span>1. Approvals</span>
        </button>
        <button
          type="button"
          onClick={() => setActiveTab("health")}
          className={`px-3.5 py-1.5 rounded-lg font-medium transition-all cursor-pointer whitespace-nowrap flex items-center gap-1.5 ${
            activeTab === "health"
              ? "bg-emerald-600 text-white shadow-sm font-semibold"
              : "text-gray-400 hover:text-gray-200"
          }`}
        >
          <span>2. System Health</span>
        </button>
        <button
          type="button"
          onClick={() => setActiveTab("users")}
          className={`px-3.5 py-1.5 rounded-lg font-medium transition-all cursor-pointer whitespace-nowrap flex items-center gap-1.5 ${
            activeTab === "users"
              ? "bg-sky-600 text-white shadow-sm font-semibold"
              : "text-gray-400 hover:text-gray-200"
          }`}
        >
          <span>3. Users</span>
        </button>
        <button
          type="button"
          onClick={() => setActiveTab("audit")}
          className={`px-3.5 py-1.5 rounded-lg font-medium transition-all cursor-pointer whitespace-nowrap flex items-center gap-1.5 ${
            activeTab === "audit"
              ? "bg-cyan-600 text-white shadow-sm font-semibold"
              : "text-gray-400 hover:text-gray-200"
          }`}
        >
          <span>4. Audit Log</span>
        </button>
      </div>

      {/* ════════════════════════════════════════════════════════════════
          FOUR PANELS LAYOUT
          ════════════════════════════════════════════════════════════════ */}
      <div className="space-y-6">
        {/* Panel 1: Approvals */}
        {(activeTab === "all" || activeTab === "approvals") && (
          <ApprovalsPanel />
        )}

        {/* Panel 2: System Health & Stuck Repos Monitor */}
        {(activeTab === "all" || activeTab === "health") && (
          <SystemHealthPanel />
        )}

        {/* Panel 3: Users Compact Table */}
        {(activeTab === "all" || activeTab === "users") && (
          <CompactUsersPanel />
        )}

        {/* Panel 4: Audit Log */}
        {(activeTab === "all" || activeTab === "audit") && (
          <AuditLogPanel />
        )}
      </div>
    </div>
  );
};

export default ControlCenterPage;
