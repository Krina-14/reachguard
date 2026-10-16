import React from "react";
import { Link, Navigate, useLocation } from "react-router-dom";
import { useAuth } from "./useAuth";
import type { UserRole } from "../api/types";


// ── RequireAuth Guard ──────────────────────────────────────────────

interface RequireAuthProps {
  children: React.ReactNode;
}

export const RequireAuth: React.FC<RequireAuthProps> = ({ children }) => {
  const { user, isAuthenticated, isLoading } = useAuth();
  const location = useLocation();

  if (isLoading) {
    return (
      <div className="min-h-screen bg-bg flex items-center justify-center">
        <div className="flex items-center gap-3 text-gray-400 font-mono text-sm">
          <svg
            className="animate-spin h-5 w-5 text-accent"
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
          <span>Authenticating session...</span>
        </div>
      </div>
    );
  }

  if (!isAuthenticated || !user) {
    return <Navigate to="/login" state={{ from: location }} replace />;
  }

  return <>{children}</>;
};

// ── RequireRole Guard with Friendly 403 Page ───────────────────────

interface RequireRoleProps {
  roles: UserRole[];
  children: React.ReactNode;
}

export const RequireRole: React.FC<RequireRoleProps> = ({ roles, children }) => {
  const { user, isLoading } = useAuth();

  if (isLoading) {
    return null;
  }

  if (!user || !roles.includes(user.role)) {
    return (
      <div className="min-h-screen bg-bg flex items-center justify-center p-6">
        <div className="max-w-md w-full bg-bg-surface border border-border rounded-xl p-8 text-center shadow-2xl">
          <div className="w-14 h-14 mx-auto mb-4 rounded-full bg-red-500/10 border border-red-500/20 flex items-center justify-center text-red-400">
            <svg
              className="w-7 h-7"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth="2"
              strokeLinecap="round"
              strokeLinejoin="round"
            >
              <rect x="3" y="11" width="18" height="11" rx="2" ry="2" />
              <path d="M7 11V7a5 5 0 0 1 10 0v4" />
            </svg>
          </div>
          <h1 className="text-2xl font-bold text-white mb-2">403 - Forbidden</h1>
          <p className="text-gray-400 text-sm mb-6">
            Your current account role (
            <span className="font-mono text-accent">{user?.role || "unknown"}</span>
            ) does not have permission to view or manage this resource.
          </p>
          <Link
            to="/"
            className="inline-flex items-center justify-center px-4 py-2 rounded-lg bg-accent text-white text-sm font-medium hover:bg-accent-hover transition-colors"
          >
            Back to Repositories
          </Link>
        </div>
      </div>
    );
  }

  return <>{children}</>;
};
