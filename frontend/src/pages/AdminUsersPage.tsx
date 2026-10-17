import React, { useState } from "react";
import { Link } from "react-router-dom";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { apiFetch } from "../api/client";
import { ApiError } from "../api/types";
import type { User, UserRole, CreateUserRequest, PatchUserRequest } from "../api/types";
import { useDocumentTitle } from "../lib/useDocumentTitle";

export const AdminUsersPage: React.FC = () => {
  useDocumentTitle("User Administration");
  const queryClient = useQueryClient();

  // 1. Fetch Users List from GET /api/admin/users (no hardcoding)
  const {
    data: users,
    isLoading,
    isError,
    error,
    refetch,
  } = useQuery<User[]>({
    queryKey: ["admin-users"],
    queryFn: () => apiFetch<User[]>("/api/admin/users"),
  });

  // Modal & Dialog states
  const [isCreateOpen, setIsCreateOpen] = useState(false);
  const [resetPasswordTarget, setResetPasswordTarget] = useState<User | null>(null);

  // Form states for Create User
  const [newEmail, setNewEmail] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [newRole, setNewRole] = useState<UserRole>("viewer");
  const [isCreating, setIsCreating] = useState(false);
  const [createError, setCreateError] = useState<string | null>(null);

  // Form states for Reset Password
  const [resetPasswordValue, setResetPasswordValue] = useState("");
  const [isResetting, setIsResetting] = useState(false);
  const [resetError, setResetError] = useState<string | null>(null);

  // Global action error/success banners (e.g. 409 last admin protection)
  const [actionError, setActionError] = useState<string | null>(null);
  const [actionSuccess, setActionSuccess] = useState<string | null>(null);
  const [processingUserId, setProcessingUserId] = useState<string | null>(null);

  // ── Create User Submit ──────────────────────────────────────────
  const handleCreateUser = async (e: React.FormEvent) => {
    e.preventDefault();
    setCreateError(null);

    const emailTrimmed = newEmail.trim();
    if (!emailTrimmed) {
      setCreateError("Email is required.");
      return;
    }

    if (newPassword.length < 10) {
      setCreateError("Password must be at least 10 characters long.");
      return;
    }

    setIsCreating(true);
    try {
      const payload: CreateUserRequest = {
        email: emailTrimmed,
        password: newPassword,
        role: newRole,
      };

      await apiFetch<User>("/api/admin/users", {
        method: "POST",
        body: JSON.stringify(payload),
      });

      setIsCreateOpen(false);
      setNewEmail("");
      setNewPassword("");
      setNewRole("viewer");
      setActionSuccess(`User ${emailTrimmed} created successfully.`);
      queryClient.invalidateQueries({ queryKey: ["admin-users"] });
    } catch (err: unknown) {
      if (err instanceof ApiError) {
        if (err.statusCode === 409) {
          setCreateError(err.message || "A user with this email already exists.");
        } else {
          setCreateError(err.message || `Failed to create user (${err.statusCode}).`);
        }
      } else if (err instanceof Error) {
        setCreateError(err.message);
      } else {
        setCreateError("An unexpected error occurred while creating user.");
      }
    } finally {
      setIsCreating(false);
    }
  };

  // ── Change Role ────────────────────────────────────────────────
  const handleChangeRole = async (targetUser: User, role: UserRole) => {
    if (targetUser.role === role) return;

    setProcessingUserId(targetUser.id);
    setActionError(null);
    setActionSuccess(null);

    try {
      const payload: PatchUserRequest = { role };
      await apiFetch<User>(`/api/admin/users/${targetUser.id}`, {
        method: "PATCH",
        body: JSON.stringify(payload),
      });

      setActionSuccess(`Role for ${targetUser.email} updated to ${role}.`);
      queryClient.invalidateQueries({ queryKey: ["admin-users"] });
    } catch (err: unknown) {
      if (err instanceof ApiError) {
        // Explicitly display 409 conflict: e.g. "Cannot demote or deactivate the last active admin"
        setActionError(err.message || `Failed to update role (${err.statusCode}).`);
      } else if (err instanceof Error) {
        setActionError(err.message);
      } else {
        setActionError("An unexpected error occurred while updating role.");
      }
    } finally {
      setProcessingUserId(null);
    }
  };

  // ── Toggle Active / Deactivate ─────────────────────────────────
  const handleToggleActive = async (targetUser: User) => {
    const newActive = !targetUser.active;
    const actionName = newActive ? "reactivate" : "deactivate";

    setProcessingUserId(targetUser.id);
    setActionError(null);
    setActionSuccess(null);

    try {
      const payload: PatchUserRequest = { active: newActive };
      await apiFetch<User>(`/api/admin/users/${targetUser.id}`, {
        method: "PATCH",
        body: JSON.stringify(payload),
      });

      setActionSuccess(`User ${targetUser.email} ${newActive ? "reactivated" : "deactivated"} successfully.`);
      queryClient.invalidateQueries({ queryKey: ["admin-users"] });
    } catch (err: unknown) {
      if (err instanceof ApiError) {
        // Explicitly display 409 conflict: "Cannot demote or deactivate the last active admin"
        setActionError(err.message || `Failed to ${actionName} user (${err.statusCode}).`);
      } else if (err instanceof Error) {
        setActionError(err.message);
      } else {
        setActionError(`Failed to ${actionName} user.`);
      }
    } finally {
      setProcessingUserId(null);
    }
  };

  // ── Reset Password Submit ──────────────────────────────────────
  const handleResetPassword = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!resetPasswordTarget) return;
    setResetError(null);

    if (resetPasswordValue.length < 10) {
      setResetError("New password must be at least 10 characters long.");
      return;
    }

    setIsResetting(true);
    try {
      const payload: PatchUserRequest = { password: resetPasswordValue };
      await apiFetch<User>(`/api/admin/users/${resetPasswordTarget.id}`, {
        method: "PATCH",
        body: JSON.stringify(payload),
      });

      setActionSuccess(`Password reset successfully for ${resetPasswordTarget.email}.`);
      setResetPasswordTarget(null);
      setResetPasswordValue("");
      queryClient.invalidateQueries({ queryKey: ["admin-users"] });
    } catch (err: unknown) {
      if (err instanceof ApiError) {
        setResetError(err.message || `Failed to reset password (${err.statusCode}).`);
      } else if (err instanceof Error) {
        setResetError(err.message);
      } else {
        setResetError("An unexpected error occurred while resetting password.");
      }
    } finally {
      setIsResetting(false);
    }
  };

  const formatDate = (dateStr?: string) => {
    if (!dateStr) return "—";
    try {
      const d = new Date(dateStr);
      if (isNaN(d.getTime())) return dateStr;
      return d.toLocaleDateString(undefined, {
        month: "short",
        day: "numeric",
        year: "numeric",
      });
    } catch {
      return dateStr;
    }
  };

  return (
    <div className="min-h-screen bg-bg text-gray-200">
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8 space-y-6">
        {/* Navigation Breadcrumb */}
        <div className="flex items-center gap-2 text-xs font-mono text-gray-400">
          <Link to="/" className="hover:text-accent transition-colors">
            Repositories
          </Link>
          <span>/</span>
          <span className="text-gray-200">Admin Users</span>
        </div>

        {/* Page Header */}
        <div className="flex items-start justify-between flex-wrap gap-4 pb-4 border-b border-border">
          <div>
            <h1 className="text-2xl font-bold font-mono text-white flex items-center gap-2.5">
              <span className="p-1.5 rounded-lg bg-purple-500/15 text-purple-400 border border-purple-500/30">
                <svg className="w-5 h-5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                  <path d="M16 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2" />
                  <circle cx="8.5" cy="7" r="4" />
                  <polyline points="17 11 19 13 23 9" />
                </svg>
              </span>
              User Administration
            </h1>
            <p className="text-xs text-gray-400 mt-1 max-w-2xl leading-relaxed">
              Manage ReachGuard accounts, role assignments, active statuses, and credentials.
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
            <button
              type="button"
              onClick={() => {
                setCreateError(null);
                setIsCreateOpen(true);
              }}
              className="px-3.5 py-1.5 rounded-lg bg-accent hover:bg-accent-hover text-white text-xs font-semibold shadow-md transition-all flex items-center gap-1.5"
            >
              <svg className="w-4 h-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5">
                <line x1="12" y1="5" x2="12" y2="19" />
                <line x1="5" y1="12" x2="19" y2="12" />
              </svg>
              Create User
            </button>
          </div>
        </div>

        {/* Global Action Error Banner (e.g. 409 Last Admin Protection) */}
        {actionError && (
          <div className="p-4 rounded-xl bg-red-500/10 border border-red-500/35 text-xs text-red-300 flex items-start justify-between gap-3 shadow-md animate-fade-in">
            <div className="flex items-start gap-2.5">
              <svg className="w-5 h-5 text-red-400 shrink-0 mt-0.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                <circle cx="12" cy="12" r="10" />
                <line x1="12" y1="8" x2="12" y2="12" />
                <line x1="12" y1="16" x2="12.01" y2="16" />
              </svg>
              <div>
                <p className="font-bold text-red-200 text-sm">Action Rejected (409 Conflict)</p>
                <p className="mt-1 leading-relaxed text-red-300 font-medium">
                  {actionError}
                </p>
              </div>
            </div>
            <button
              type="button"
              onClick={() => setActionError(null)}
              className="text-red-400 hover:text-red-200 p-1"
              title="Dismiss error"
            >
              ✕
            </button>
          </div>
        )}

        {/* Global Action Success Banner */}
        {actionSuccess && (
          <div className="p-3.5 rounded-xl bg-emerald-500/10 border border-emerald-500/30 text-xs text-emerald-300 flex items-center justify-between gap-3 shadow-sm animate-fade-in">
            <div className="flex items-center gap-2">
              <svg className="w-4 h-4 text-emerald-400 shrink-0" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                <polyline points="20 6 9 17 4 12" />
              </svg>
              <span className="font-medium">{actionSuccess}</span>
            </div>
            <button
              type="button"
              onClick={() => setActionSuccess(null)}
              className="text-emerald-400 hover:text-emerald-200 p-1"
            >
              ✕
            </button>
          </div>
        )}

        {/* Users Table Card */}
        <div className="bg-bg-surface border border-border rounded-xl shadow-sm overflow-hidden">
          {/* Loading Table Skeleton */}
          {isLoading && (
            <div className="p-6 space-y-4 animate-pulse">
              <div className="h-6 bg-bg-card rounded w-full" />
              {[1, 2, 3, 4].map((i) => (
                <div key={i} className="flex items-center justify-between gap-4 py-2 border-b border-border/40">
                  <div className="h-4 bg-bg-card rounded w-1/4" />
                  <div className="h-4 bg-bg-card rounded w-16" />
                  <div className="h-4 bg-bg-card rounded w-16" />
                  <div className="h-4 bg-bg-card rounded w-24" />
                  <div className="h-4 bg-bg-card rounded w-28" />
                </div>
              ))}
            </div>
          )}

          {/* Error State with Retry Button */}
          {isError && (
            <div className="p-8 text-center text-red-400 text-xs space-y-3">
              <p className="font-semibold text-sm">Failed to retrieve users</p>
              <p className="text-gray-400">
                {error instanceof Error ? error.message : "Unknown error"}
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

          {!isLoading && !isError && users && (
            <div className="overflow-x-auto">
              <table className="w-full text-left text-xs">
                <thead className="bg-bg-card text-gray-400 uppercase font-mono text-[11px] tracking-wider border-b border-border">
                  <tr>
                    <th className="py-3 px-4 font-semibold">User / Email</th>
                    <th className="py-3 px-4 font-semibold">Role</th>
                    <th className="py-3 px-4 font-semibold">Status</th>
                    <th className="py-3 px-4 font-semibold">Created Date</th>
                    <th className="py-3 px-4 font-semibold text-right">Actions</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-border/60">
                  {users.length === 0 ? (
                    <tr>
                      <td colSpan={5} className="py-8 text-center text-gray-400 italic">
                        No users recorded in the database.
                      </td>
                    </tr>
                  ) : (
                    users.map((u) => {
                      const isProcessing = processingUserId === u.id;
                      const isActive = u.active !== false;

                      return (
                        <tr
                          key={u.id}
                          className="hover:bg-bg-card/40 transition-colors"
                        >
                          {/* Email */}
                          <td className="py-3 px-4">
                            <div className="flex items-center gap-2">
                              <span className="w-7 h-7 rounded-full bg-slate-800 border border-slate-700 flex items-center justify-center font-bold text-xs text-gray-300">
                                {u.email.substring(0, 1).toUpperCase()}
                              </span>
                              <div>
                                <span className="font-medium text-white block">
                                  {u.email}
                                </span>
                                <span className="text-[10px] text-gray-400 font-mono">
                                  {u.id}
                                </span>
                              </div>
                            </div>
                          </td>

                          {/* Role Selection Dropdown */}
                          <td className="py-3 px-4">
                            <select
                              value={u.role}
                              disabled={isProcessing}
                              onChange={(e) =>
                                handleChangeRole(u, e.target.value as UserRole)
                              }
                              className={`px-2 py-1 rounded text-xs font-semibold uppercase tracking-wider outline-none border transition-colors cursor-pointer disabled:opacity-50 ${
                                u.role === "admin"
                                  ? "bg-purple-500/15 text-purple-300 border-purple-500/35 focus:border-purple-400"
                                  : u.role === "analyst"
                                  ? "bg-blue-500/15 text-blue-300 border-blue-500/35 focus:border-blue-400"
                                  : "bg-slate-500/15 text-slate-300 border-slate-500/35 focus:border-slate-400"
                              }`}
                            >
                              <option value="viewer" className="bg-bg-surface text-gray-200">
                                Viewer
                              </option>
                              <option value="analyst" className="bg-bg-surface text-gray-200">
                                Analyst
                              </option>
                              <option value="admin" className="bg-bg-surface text-gray-200">
                                Admin
                              </option>
                            </select>
                          </td>

                          {/* Status Badge */}
                          <td className="py-3 px-4">
                            {isActive ? (
                              <span className="inline-flex items-center gap-1.5 px-2 py-0.5 rounded text-[10px] font-semibold bg-emerald-500/15 text-emerald-300 border border-emerald-500/30 uppercase">
                                <span className="w-1.5 h-1.5 rounded-full bg-emerald-400" />
                                Active
                              </span>
                            ) : (
                              <span className="inline-flex items-center gap-1.5 px-2 py-0.5 rounded text-[10px] font-semibold bg-red-500/15 text-red-300 border border-red-500/30 uppercase">
                                <span className="w-1.5 h-1.5 rounded-full bg-red-400" />
                                Deactivated
                              </span>
                            )}
                          </td>

                          {/* Created Date */}
                          <td className="py-3 px-4 font-mono text-gray-400 text-xs">
                            {formatDate(u.created_at)}
                          </td>

                          {/* Actions */}
                          <td className="py-3 px-4 text-right">
                            <div className="flex items-center justify-end gap-2">
                              {/* Reset Password Button */}
                              <button
                                type="button"
                                disabled={isProcessing}
                                onClick={() => {
                                  setResetError(null);
                                  setResetPasswordValue("");
                                  setResetPasswordTarget(u);
                                }}
                                className="px-2.5 py-1 text-xs rounded border border-border bg-bg-card hover:bg-slate-700 text-gray-300 hover:text-white transition-colors disabled:opacity-50"
                                title="Reset user password"
                              >
                                Reset Password
                              </button>

                              {/* Deactivate / Reactivate Button */}
                              <button
                                type="button"
                                disabled={isProcessing}
                                onClick={() => handleToggleActive(u)}
                                className={`px-2.5 py-1 text-xs rounded font-medium border transition-colors disabled:opacity-50 ${
                                  isActive
                                    ? "bg-red-500/10 hover:bg-red-500/20 text-red-300 border-red-500/30"
                                    : "bg-emerald-500/10 hover:bg-emerald-500/20 text-emerald-300 border-emerald-500/30"
                                }`}
                              >
                                {isActive ? "Deactivate" : "Reactivate"}
                              </button>
                            </div>
                          </td>
                        </tr>
                      );
                    })
                  )}
                </tbody>
              </table>
            </div>
          )}
        </div>

        {/* ── Create User Modal ── */}
        {isCreateOpen && (
          <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/75 backdrop-blur-sm animate-fade-in">
            <div className="w-full max-w-md bg-bg-surface border border-border rounded-xl shadow-2xl p-6 space-y-4">
              <div className="flex items-center justify-between pb-3 border-b border-border">
                <h3 className="text-base font-bold text-white flex items-center gap-2">
                  <span className="p-1.5 rounded-lg bg-accent/15 text-accent">
                    <svg className="w-4 h-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                      <path d="M16 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2" />
                      <circle cx="8.5" cy="7" r="4" />
                    </svg>
                  </span>
                  Create New User
                </h3>
                <button
                  type="button"
                  onClick={() => setIsCreateOpen(false)}
                  className="text-gray-400 hover:text-white"
                >
                  ✕
                </button>
              </div>

              {createError && (
                <div className="p-3 rounded-lg bg-red-500/10 border border-red-500/30 text-xs text-red-300">
                  {createError}
                </div>
              )}

              <form onSubmit={handleCreateUser} className="space-y-4 text-xs">
                <div>
                  <label className="block text-gray-300 font-medium mb-1">
                    Email Address <span className="text-red-400">*</span>
                  </label>
                  <input
                    type="email"
                    required
                    value={newEmail}
                    onChange={(e) => setNewEmail(e.target.value)}
                    placeholder="you@company.com"
                    className="w-full px-3 py-2 rounded-lg bg-bg-card border border-border text-white placeholder-gray-500 outline-none focus:border-accent"
                  />
                </div>

                <div>
                  <label className="block text-gray-300 font-medium mb-1">
                    Initial Password (min 10 characters) <span className="text-red-400">*</span>
                  </label>
                  <input
                    type="password"
                    required
                    minLength={10}
                    value={newPassword}
                    onChange={(e) => setNewPassword(e.target.value)}
                    placeholder="••••••••••"
                    className="w-full px-3 py-2 rounded-lg bg-bg-card border border-border text-white placeholder-gray-500 outline-none focus:border-accent"
                  />
                  <span className="text-[10px] text-gray-400 mt-0.5 block">
                    Must be at least 10 characters long.
                  </span>
                </div>

                <div>
                  <label className="block text-gray-300 font-medium mb-1">
                    System Role <span className="text-red-400">*</span>
                  </label>
                  <select
                    value={newRole}
                    onChange={(e) => setNewRole(e.target.value as UserRole)}
                    className="w-full px-3 py-2 rounded-lg bg-bg-card border border-border text-white outline-none focus:border-accent"
                  >
                    <option value="viewer">Viewer (Read-only findings & graphs)</option>
                    <option value="analyst">Analyst (What-if simulations, decisions, chat saves)</option>
                    <option value="admin">Admin (Full administrative & user management permissions)</option>
                  </select>
                </div>

                <div className="flex items-center justify-end gap-2 pt-2 border-t border-border">
                  <button
                    type="button"
                    onClick={() => setIsCreateOpen(false)}
                    className="px-3 py-1.5 rounded-lg border border-border bg-bg-card text-gray-300 hover:text-white"
                  >
                    Cancel
                  </button>
                  <button
                    type="submit"
                    disabled={isCreating}
                    className="px-4 py-1.5 rounded-lg bg-accent hover:bg-accent-hover disabled:opacity-50 text-white font-semibold flex items-center gap-1.5"
                  >
                    {isCreating ? "Creating..." : "Create User"}
                  </button>
                </div>
              </form>
            </div>
          </div>
        )}

        {/* ── Reset Password Modal ── */}
        {resetPasswordTarget && (
          <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/75 backdrop-blur-sm animate-fade-in">
            <div className="w-full max-w-md bg-bg-surface border border-border rounded-xl shadow-2xl p-6 space-y-4">
              <div className="flex items-center justify-between pb-3 border-b border-border">
                <h3 className="text-base font-bold text-white flex items-center gap-2">
                  <span className="p-1.5 rounded-lg bg-amber-500/15 text-amber-400">
                    <svg className="w-4 h-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                      <rect x="3" y="11" width="18" height="11" rx="2" ry="2" />
                      <path d="M7 11V7a5 5 0 0 1 10 0v4" />
                    </svg>
                  </span>
                  Reset Password
                </h3>
                <button
                  type="button"
                  onClick={() => setResetPasswordTarget(null)}
                  className="text-gray-400 hover:text-white"
                >
                  ✕
                </button>
              </div>

              <p className="text-xs text-gray-300">
                Setting new password for{" "}
                <strong className="text-white font-mono">{resetPasswordTarget.email}</strong>:
              </p>

              {resetError && (
                <div className="p-3 rounded-lg bg-red-500/10 border border-red-500/30 text-xs text-red-300">
                  {resetError}
                </div>
              )}

              <form onSubmit={handleResetPassword} className="space-y-4 text-xs">
                <div>
                  <label className="block text-gray-300 font-medium mb-1">
                    New Password (min 10 characters) <span className="text-red-400">*</span>
                  </label>
                  <input
                    type="password"
                    required
                    minLength={10}
                    value={resetPasswordValue}
                    onChange={(e) => setResetPasswordValue(e.target.value)}
                    placeholder="••••••••••"
                    className="w-full px-3 py-2 rounded-lg bg-bg-card border border-border text-white placeholder-gray-500 outline-none focus:border-accent"
                  />
                  <span className="text-[10px] text-gray-400 mt-0.5 block">
                    Must be at least 10 characters long.
                  </span>
                </div>

                <div className="flex items-center justify-end gap-2 pt-2 border-t border-border">
                  <button
                    type="button"
                    onClick={() => setResetPasswordTarget(null)}
                    className="px-3 py-1.5 rounded-lg border border-border bg-bg-card text-gray-300 hover:text-white"
                  >
                    Cancel
                  </button>
                  <button
                    type="submit"
                    disabled={isResetting}
                    className="px-4 py-1.5 rounded-lg bg-accent hover:bg-accent-hover disabled:opacity-50 text-white font-semibold flex items-center gap-1.5"
                  >
                    {isResetting ? "Saving..." : "Set Password"}
                  </button>
                </div>
              </form>
            </div>
          </div>
        )}
      </div>
    </div>
  );
};
