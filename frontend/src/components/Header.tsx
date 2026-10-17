import React, { useState, useRef, useEffect } from "react";
import { Link, useNavigate } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { useAuth } from "../auth/useAuth";
import { useCan } from "../auth/useCan";
import { apiFetch } from "../api/client";
import { ChangePasswordModal } from "./ChangePasswordModal";
import type { HealthResponse } from "../api/types";

export const Header: React.FC = () => {
  const { user, logout } = useAuth();
  const { canManageUsers } = useCan();
  const navigate = useNavigate();

  const [isChangePasswordOpen, setIsChangePasswordOpen] = useState(false);
  const [isUserMenuOpen, setIsUserMenuOpen] = useState(false);
  const userMenuRef = useRef<HTMLDivElement>(null);

  // Close user menu on outside click
  useEffect(() => {
    const handleClickOutside = (event: MouseEvent) => {
      if (
        userMenuRef.current &&
        !userMenuRef.current.contains(event.target as Node)
      ) {
        setIsUserMenuOpen(false);
      }
    };
    document.addEventListener("mousedown", handleClickOutside);
    return () => {
      document.removeEventListener("mousedown", handleClickOutside);
    };
  }, []);

  // Poll GET /api/health every 30 seconds
  const { data: health, isError } = useQuery<HealthResponse>({
    queryKey: ["backend-health"],
    queryFn: () => apiFetch<HealthResponse>("/api/health"),
    refetchInterval: 30000,
    retry: false,
  });

  const handleLogout = () => {
    logout();
    navigate("/login");
  };

  const isGraphDbUp = Boolean(health?.falkordb && !isError);
  const aiMode = health?.llm?.mode;
  const aiModel = health?.llm?.model;

  return (
    <header className="h-16 bg-bg-surface/90 border-b border-border backdrop-blur-md sticky top-0 z-50 px-6 flex items-center justify-between">
      {/* Left: Product Name & Repo Switcher */}
      <div className="flex items-center gap-6">
        <Link
          to="/"
          className="flex items-center gap-2.5 text-white hover:text-accent transition-colors"
        >
          <div className="w-8 h-8 rounded-lg bg-accent/15 border border-accent/30 text-accent flex items-center justify-center">
            <svg
              className="w-5 h-5"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth="2.2"
              strokeLinecap="round"
              strokeLinejoin="round"
            >
              <path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z" />
            </svg>
          </div>
          <span className="font-bold text-lg tracking-tight">ReachGuard</span>
        </Link>

        {/* Repo Switcher Placeholder */}
        <div className="hidden sm:flex items-center">
          <div
            className="flex items-center gap-2 px-3 py-1.5 rounded-lg bg-bg-card border border-border text-xs text-gray-300 hover:border-gray-600 transition-colors cursor-pointer select-none"
            title="Repository selector"
          >
            <svg
              className="w-3.5 h-3.5 text-gray-400"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth="2"
            >
              <path d="M4 19.5v-15A2.5 2.5 0 0 1 6.5 2H20v20H6.5a2.5 2.5 0 0 1-2.5-2.5Z" />
              <path d="M6 6h10" />
              <path d="M6 10h10" />
            </svg>
            <span>All Repositories</span>
            <svg
              className="w-3.5 h-3.5 text-gray-500"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth="2"
            >
              <polyline points="6 9 12 15 18 9" />
            </svg>
          </div>
        </div>
      </div>

      {/* Center/Right: Backend Health Badge (Graph DB + AI Mode) */}
      <div className="flex items-center gap-4">
        <div className="hidden md:flex items-center gap-2 bg-bg-card/70 border border-border/80 rounded-lg px-2.5 py-1 text-xs">
          {/* Graph DB indicator */}
          <div className="flex items-center gap-1.5" title="FalkorDB multigraph status">
            <span
              className={`w-2 h-2 rounded-full ${
                isGraphDbUp ? "bg-emerald-400" : "bg-red-400 animate-pulse"
              }`}
            />
            <span className="text-gray-300 font-mono text-[11px]">
              {isGraphDbUp ? "Graph DB" : "Graph Down"}
            </span>
          </div>

          <span className="text-gray-600">|</span>

          {/* AI Mode indicator */}
          <div className="flex items-center gap-1.5">
            {aiMode === "llm" ? (
              <>
                <span className="w-2 h-2 rounded-full bg-purple-400" />
                <span className="text-purple-300 font-mono text-[11px]">
                  LLM: {aiModel || "Active"}
                </span>
              </>
            ) : aiMode === "deterministic" ? (
              <>
                <span className="w-2 h-2 rounded-full bg-amber-400" />
                <span className="text-amber-300 font-mono text-[11px]">
                  Deterministic mode
                </span>
              </>
            ) : (
              <>
                <span className="w-2 h-2 rounded-full bg-gray-500" />
                <span className="text-gray-400 font-mono text-[11px]">
                  AI: Connecting...
                </span>
              </>
            )}
          </div>
        </div>

        {/* Role-Gated Admin Link (Hidden for non-admin) */}
        {canManageUsers && (
          <Link
            to="/admin/users"
            className="text-xs font-medium text-gray-300 hover:text-white px-2.5 py-1.5 rounded-lg bg-bg-card border border-border hover:border-gray-600 transition-colors"
          >
            Admin
          </Link>
        )}

        {/* User Identity & Dropdown Menu */}
        {user && (
          <div ref={userMenuRef} className="relative pl-2 border-l border-border">
            <button
              type="button"
              onClick={() => setIsUserMenuOpen((prev) => !prev)}
              className="flex items-center gap-2.5 p-1 rounded-lg hover:bg-bg-card transition-colors select-none text-left"
              title="User menu"
            >
              <div className="flex flex-col items-end">
                <span className="text-xs font-medium text-gray-200">
                  {user.email}
                </span>
                <span
                  className={`text-[10px] font-semibold uppercase tracking-wider px-1.5 py-0.2 rounded ${
                    user.role === "admin"
                      ? "bg-purple-500/15 text-purple-400 border border-purple-500/30"
                      : user.role === "analyst"
                      ? "bg-blue-500/15 text-blue-400 border border-blue-500/30"
                      : "bg-slate-500/15 text-slate-400 border border-slate-500/30"
                  }`}
                >
                  {user.role}
                </span>
              </div>
              <svg
                className={`w-3.5 h-3.5 text-gray-400 transition-transform ${
                  isUserMenuOpen ? "rotate-180" : ""
                }`}
                viewBox="0 0 24 24"
                fill="none"
                stroke="currentColor"
                strokeWidth="2"
              >
                <polyline points="6 9 12 15 18 9" />
              </svg>
            </button>

            {/* Dropdown Menu */}
            {isUserMenuOpen && (
              <div className="absolute right-0 mt-2 w-56 rounded-xl bg-bg-surface border border-border shadow-2xl p-1.5 z-50 text-xs space-y-1 animate-fade-in">
                <div className="px-3 py-2 border-b border-border/70">
                  <span className="text-[10px] uppercase font-mono text-gray-400 block">
                    Signed in as
                  </span>
                  <span className="font-semibold text-white truncate block">
                    {user.email}
                  </span>
                  <span className="text-[10px] text-gray-400 capitalize">
                    Role: {user.role}
                  </span>
                </div>

                {/* Change Password Option */}
                <button
                  type="button"
                  onClick={() => {
                    setIsUserMenuOpen(false);
                    setIsChangePasswordOpen(true);
                  }}
                  className="w-full text-left px-3 py-2 rounded-lg text-gray-300 hover:text-white hover:bg-bg-card transition-colors flex items-center gap-2"
                >
                  <svg className="w-4 h-4 text-accent" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                    <rect x="3" y="11" width="18" height="11" rx="2" ry="2" />
                    <path d="M7 11V7a5 5 0 0 1 10 0v4" />
                  </svg>
                  <span>Change Password</span>
                </button>

                {/* Sign Out Option */}
                <button
                  type="button"
                  onClick={() => {
                    setIsUserMenuOpen(false);
                    handleLogout();
                  }}
                  className="w-full text-left px-3 py-2 rounded-lg text-red-400 hover:text-red-300 hover:bg-red-500/10 transition-colors flex items-center gap-2"
                >
                  <svg
                    className="w-4 h-4"
                    viewBox="0 0 24 24"
                    fill="none"
                    stroke="currentColor"
                    strokeWidth="2"
                  >
                    <path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4" />
                    <polyline points="16 17 21 12 16 7" />
                    <line x1="21" y1="12" x2="9" y2="12" />
                  </svg>
                  <span>Sign Out</span>
                </button>
              </div>
            )}
          </div>
        )}
      </div>

      {/* Change Password Dialog */}
      <ChangePasswordModal
        isOpen={isChangePasswordOpen}
        onClose={() => setIsChangePasswordOpen(false)}
      />
    </header>
  );
};
