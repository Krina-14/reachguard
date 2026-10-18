import React, { useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { apiFetch } from "../../api/client";
import { ApiError } from "../../api/types";
import type { User, UserRole, CreateUserRequest, PatchUserRequest } from "../../api/types";

export const CompactUsersPanel: React.FC = () => {
  const queryClient = useQueryClient();

  // 1. Fetch Users List: GET /api/admin/users
  const {
    data: users = [],
    isLoading,
    isError,
    error,
    refetch,
  } = useQuery<User[]>({
    queryKey: ["admin-users"],
    queryFn: () => apiFetch<User[]>("/api/admin/users"),
  });

  // Modal & Form states for Create User
  const [isCreateOpen, setIsCreateOpen] = useState(false);
  const [newEmail, setNewEmail] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [newRole, setNewRole] = useState<UserRole>("viewer");
  const [isCreating, setIsCreating] = useState(false);
  const [createError, setCreateError] = useState<string | null>(null);

  // Row action states
  const [actionError, setActionError] = useState<string | null>(null);
  const [actionSuccess, setActionSuccess] = useState<string | null>(null);
  const [processingUserId, setProcessingUserId] = useState<string | null>(null);

  // Create User Submit
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
      queryClient.invalidateQueries({ queryKey: ["admin-audit"] });
    } catch (err: unknown) {
      if (err instanceof ApiError) {
        setCreateError(err.message || "Failed to create user.");
      } else if (err instanceof Error) {
        setCreateError(err.message);
      } else {
        setCreateError("An unexpected error occurred while creating user.");
      }
    } finally {
      setIsCreating(false);
    }
  };

  // Change Role
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

      setActionSuccess(`Role for ${targetUser.email} changed to ${role}.`);
      queryClient.invalidateQueries({ queryKey: ["admin-users"] });
      queryClient.invalidateQueries({ queryKey: ["admin-audit"] });
    } catch (err: unknown) {
      if (err instanceof ApiError) {
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

  // Toggle Active / Deactivate
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

      setActionSuccess(
        `User ${targetUser.email} ${newActive ? "reactivated" : "deactivated"} successfully.`
      );
      queryClient.invalidateQueries({ queryKey: ["admin-users"] });
      queryClient.invalidateQueries({ queryKey: ["admin-audit"] });
    } catch (err: unknown) {
      if (err instanceof ApiError) {
        setActionError(err.message || `Failed to ${actionName} user.`);
      } else if (err instanceof Error) {
        setActionError(err.message);
      } else {
        setActionError(`Failed to ${actionName} user.`);
      }
    } finally {
      setProcessingUserId(null);
    }
  };

  return (
    <div className="bg-bg-surface border border-border rounded-xl p-5 shadow-sm space-y-4">
      {/* Header */}
      <div className="flex items-center justify-between pb-3 border-b border-border/70 flex-wrap gap-2">
        <div className="flex items-center gap-2.5">
          <div className="w-8 h-8 rounded-lg bg-sky-500/15 border border-sky-500/30 text-sky-400 flex items-center justify-center">
            <svg
              className="w-4 h-4"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth="2"
            >
              <path d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2" />
              <circle cx="9" cy="7" r="4" />
              <path d="M22 21v-2a4 4 0 0 0-3-3.87" />
              <path d="M16 3.13a4 4 0 0 1 0 7.75" />
            </svg>
          </div>
          <div>
            <h2 className="text-base font-bold text-white flex items-center gap-2">
              User Management
              <span className="px-2 py-0.2 rounded-full text-xs font-mono font-bold bg-sky-500/20 text-sky-300 border border-sky-500/35">
                {users.length} Users
              </span>
            </h2>
            <p className="text-xs text-gray-400">
              Manage accounts, assign roles, and toggle user active states
            </p>
          </div>
        </div>

        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={() => refetch()}
            title="Refresh users list"
            className="px-2.5 py-1.5 rounded-lg bg-bg-card hover:bg-bg-subtle text-gray-300 border border-border text-xs transition-colors cursor-pointer"
          >
            Refresh
          </button>
          <button
            type="button"
            onClick={() => setIsCreateOpen(true)}
            className="inline-flex items-center gap-1.5 px-3 py-1.5 bg-accent hover:bg-accent-hover text-white text-xs font-semibold rounded-lg shadow-sm transition-colors cursor-pointer"
          >
            <svg className="w-3.5 h-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <path d="M12 5v14M5 12h14" />
            </svg>
            <span>Create User</span>
          </button>
        </div>
      </div>

      {actionError && (
        <div className="p-3 rounded-lg bg-red-500/15 border border-red-500/30 text-red-400 text-xs">
          {actionError}
        </div>
      )}

      {actionSuccess && (
        <div className="p-3 rounded-lg bg-emerald-500/15 border border-emerald-500/30 text-emerald-400 text-xs">
          {actionSuccess}
        </div>
      )}

      {/* Loading State */}
      {isLoading && (
        <div className="space-y-2 animate-pulse">
          {[1, 2, 3, 4].map((i) => (
            <div key={i} className="h-12 bg-bg-card/70 border border-border rounded-lg" />
          ))}
        </div>
      )}

      {/* Error State */}
      {isError && !isLoading && (
        <div className="p-6 rounded-lg border border-red-500/30 bg-red-500/5 text-center space-y-2">
          <p className="text-red-400 text-xs font-medium">Failed to load user accounts.</p>
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
      {!isLoading && !isError && users.length === 0 && (
        <div className="p-8 rounded-lg border border-border/80 bg-bg-card/30 text-center space-y-2">
          <p className="text-sm font-semibold text-white">No Users Found</p>
          <p className="text-xs text-gray-400">Click &quot;Create User&quot; to provision a new account.</p>
        </div>
      )}

      {/* Compact Users Table */}
      {!isLoading && !isError && users.length > 0 && (
        <div className="border border-border/70 rounded-xl overflow-x-auto">
          <table className="w-full text-left text-xs">
            <thead className="bg-bg-card text-gray-400 border-b border-border/70 text-[11px]">
              <tr>
                <th className="py-2.5 px-3 font-medium">User</th>
                <th className="py-2.5 px-3 font-medium">Role</th>
                <th className="py-2.5 px-3 font-medium">Status</th>
                <th className="py-2.5 px-3 font-medium">Created</th>
                <th className="py-2.5 px-3 font-medium text-right">Actions</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-border/50 font-mono text-[11px]">
              {users.map((u) => {
                const isProcessing = processingUserId === u.id;
                const isActive = u.active !== false;

                return (
                  <tr key={u.id} className="hover:bg-bg-card/40 transition-colors">
                    <td className="py-2.5 px-3 font-semibold text-white font-sans">
                      <div className="flex items-center gap-2">
                        <span
                          className={`w-2 h-2 rounded-full ${
                            isActive ? "bg-emerald-400" : "bg-gray-600"
                          }`}
                        />
                        <span>{u.email}</span>
                      </div>
                    </td>
                    <td className="py-2.5 px-3">
                      <select
                        value={u.role}
                        disabled={isProcessing}
                        onChange={(e) =>
                          handleChangeRole(u, e.target.value as UserRole)
                        }
                        className="bg-bg-card border border-border rounded px-2 py-1 text-xs text-gray-200 focus:outline-none focus:ring-1 focus:ring-accent cursor-pointer"
                      >
                        <option value="viewer">Viewer</option>
                        <option value="analyst">Analyst</option>
                        <option value="admin">Admin</option>
                      </select>
                    </td>
                    <td className="py-2.5 px-3">
                      <span
                        className={`px-2 py-0.5 rounded text-[10px] font-bold uppercase tracking-wider border ${
                          isActive
                            ? "bg-emerald-500/15 text-emerald-400 border-emerald-500/30"
                            : "bg-red-500/15 text-red-400 border-red-500/30"
                        }`}
                      >
                        {isActive ? "Active" : "Deactivated"}
                      </span>
                    </td>
                    <td className="py-2.5 px-3 text-gray-400">
                      {u.created_at
                        ? new Date(u.created_at).toLocaleDateString()
                        : "—"}
                    </td>
                    <td className="py-2.5 px-3 text-right">
                      <button
                        type="button"
                        disabled={isProcessing}
                        onClick={() => handleToggleActive(u)}
                        className={`px-2.5 py-1 rounded text-xs font-semibold transition-colors cursor-pointer ${
                          isActive
                            ? "bg-red-500/15 hover:bg-red-500/25 text-red-300 border border-red-500/30"
                            : "bg-emerald-500/15 hover:bg-emerald-500/25 text-emerald-300 border border-emerald-500/30"
                        }`}
                      >
                        {isProcessing
                          ? "Saving..."
                          : isActive
                          ? "Deactivate"
                          : "Reactivate"}
                      </button>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}

      {/* ════════════════════════════════════════════════════════════════
          CREATE USER MODAL
          ════════════════════════════════════════════════════════════════ */}
      {isCreateOpen && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/70 backdrop-blur-sm animate-fadeIn">
          <div className="bg-bg-surface border border-border rounded-2xl p-6 max-w-md w-full shadow-2xl space-y-4">
            <div className="flex items-center justify-between pb-3 border-b border-border">
              <h3 className="text-base font-bold text-white flex items-center gap-2">
                <svg className="w-4 h-4 text-accent" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                  <path d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2" />
                  <circle cx="9" cy="7" r="4" />
                  <line x1="19" y1="8" x2="19" y2="14" />
                  <line x1="22" y1="11" x2="16" y2="11" />
                </svg>
                Create ReachGuard User
              </h3>
              <button
                type="button"
                onClick={() => setIsCreateOpen(false)}
                className="text-gray-400 hover:text-white text-xs px-2 py-1 rounded"
              >
                ✕
              </button>
            </div>

            <form onSubmit={handleCreateUser} className="space-y-4">
              <div>
                <label className="block text-xs font-medium text-gray-300 mb-1">
                  Email Address
                </label>
                <input
                  type="email"
                  required
                  value={newEmail}
                  onChange={(e) => setNewEmail(e.target.value)}
                  placeholder="analyst@example.com"
                  className="w-full bg-bg-card border border-border rounded-lg px-3 py-2 text-sm text-gray-200 placeholder-gray-500 focus:outline-none focus:ring-1 focus:ring-accent"
                />
              </div>

              <div>
                <label className="block text-xs font-medium text-gray-300 mb-1">
                  Password (min 10 characters)
                </label>
                <input
                  type="password"
                  required
                  value={newPassword}
                  onChange={(e) => setNewPassword(e.target.value)}
                  placeholder="••••••••••••"
                  className="w-full bg-bg-card border border-border rounded-lg px-3 py-2 text-sm text-gray-200 placeholder-gray-500 focus:outline-none focus:ring-1 focus:ring-accent"
                />
              </div>

              <div>
                <label className="block text-xs font-medium text-gray-300 mb-1">
                  Account Role
                </label>
                <select
                  value={newRole}
                  onChange={(e) => setNewRole(e.target.value as UserRole)}
                  className="w-full bg-bg-card border border-border rounded-lg px-3 py-2 text-sm text-gray-200 focus:outline-none focus:ring-1 focus:ring-accent"
                >
                  <option value="viewer">Viewer (Read-only catalog & graphs)</option>
                  <option value="analyst">Analyst (Triage, decisions, ingest)</option>
                  <option value="admin">Admin (Full policy, user & system control)</option>
                </select>
              </div>

              {createError && (
                <div className="p-3 rounded-lg bg-red-500/15 border border-red-500/30 text-red-400 text-xs">
                  {createError}
                </div>
              )}

              <div className="flex items-center justify-end gap-2 pt-2">
                <button
                  type="button"
                  onClick={() => setIsCreateOpen(false)}
                  className="px-3.5 py-2 rounded-lg bg-bg-card hover:bg-bg-subtle text-gray-300 text-xs font-medium border border-border transition-colors cursor-pointer"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  disabled={isCreating}
                  className="px-4 py-2 bg-accent hover:bg-accent-hover disabled:bg-gray-700 text-white text-xs font-semibold rounded-lg shadow-sm transition-colors cursor-pointer"
                >
                  {isCreating ? "Creating..." : "Create User"}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  );
};
