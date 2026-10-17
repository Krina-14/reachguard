import React, { useState } from "react";
import { apiFetch } from "../api/client";
import { ApiError } from "../api/types";
import type { ChangePasswordRequest } from "../api/types";

interface ChangePasswordModalProps {
  isOpen: boolean;
  onClose: () => void;
}

export const ChangePasswordModal: React.FC<ChangePasswordModalProps> = ({
  isOpen,
  onClose,
}) => {
  const [currentPassword, setCurrentPassword] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [successMessage, setSuccessMessage] = useState<string | null>(null);

  if (!isOpen) return null;

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setErrorMessage(null);
    setSuccessMessage(null);

    if (!currentPassword) {
      setErrorMessage("Current password is required.");
      return;
    }

    if (newPassword.length < 10) {
      setErrorMessage("New password must be at least 10 characters long.");
      return;
    }

    if (newPassword !== confirmPassword) {
      setErrorMessage("New passwords do not match.");
      return;
    }

    setIsSubmitting(true);
    try {
      const payload: ChangePasswordRequest = {
        current_password: currentPassword,
        old_password: currentPassword,
        new_password: newPassword,
      };

      await apiFetch<{ message: string }>("/api/auth/change-password", {
        method: "POST",
        body: JSON.stringify(payload),
      });

      setSuccessMessage("Password changed successfully.");
      setCurrentPassword("");
      setNewPassword("");
      setConfirmPassword("");

      // Automatically close after a short delay
      setTimeout(() => {
        onClose();
        setSuccessMessage(null);
      }, 1500);
    } catch (err: unknown) {
      if (err instanceof ApiError) {
        if (err.statusCode === 401) {
          setErrorMessage("Current password is incorrect.");
        } else {
          setErrorMessage(err.message || `Failed to change password (${err.statusCode}).`);
        }
      } else if (err instanceof Error) {
        setErrorMessage(err.message);
      } else {
        setErrorMessage("An unexpected error occurred while changing password.");
      }
    } finally {
      setIsSubmitting(false);
    }
  };

  const handleClose = () => {
    if (isSubmitting) return;
    setErrorMessage(null);
    setSuccessMessage(null);
    setCurrentPassword("");
    setNewPassword("");
    setConfirmPassword("");
    onClose();
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/75 backdrop-blur-sm animate-fade-in">
      <div className="w-full max-w-md bg-bg-surface border border-border rounded-xl shadow-2xl p-6 space-y-4">
        {/* Modal Header */}
        <div className="flex items-center justify-between pb-3 border-b border-border">
          <h3 className="text-base font-bold text-white flex items-center gap-2">
            <span className="p-1.5 rounded-lg bg-accent/15 text-accent">
              <svg className="w-4 h-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                <rect x="3" y="11" width="18" height="11" rx="2" ry="2" />
                <path d="M7 11V7a5 5 0 0 1 10 0v4" />
              </svg>
            </span>
            Change Password
          </h3>
          <button
            type="button"
            disabled={isSubmitting}
            onClick={handleClose}
            aria-label="Close dialog"
            className="text-gray-400 hover:text-white disabled:opacity-50"
          >
            ✕
          </button>
        </div>

        {/* Error Feedback */}
        {errorMessage && (
          <div className="p-3 rounded-lg bg-red-500/10 border border-red-500/30 text-xs text-red-300">
            {errorMessage}
          </div>
        )}

        {/* Success Feedback */}
        {successMessage && (
          <div className="p-3 rounded-lg bg-emerald-500/10 border border-emerald-500/30 text-xs text-emerald-300 flex items-center gap-2">
            <svg className="w-4 h-4 text-emerald-400 shrink-0" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <polyline points="20 6 9 17 4 12" />
            </svg>
            <span>{successMessage}</span>
          </div>
        )}

        {/* Form */}
        <form onSubmit={handleSubmit} className="space-y-4 text-xs">
          <div>
            <label className="block text-gray-300 font-medium mb-1">
              Current Password <span className="text-red-400">*</span>
            </label>
            <input
              type="password"
              required
              value={currentPassword}
              onChange={(e) => setCurrentPassword(e.target.value)}
              placeholder="••••••••••"
              className="w-full px-3 py-2 rounded-lg bg-bg-card border border-border text-white placeholder-gray-500 outline-none focus:border-accent"
            />
          </div>

          <div>
            <label className="block text-gray-300 font-medium mb-1">
              New Password (min 10 characters) <span className="text-red-400">*</span>
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
              Confirm New Password <span className="text-red-400">*</span>
            </label>
            <input
              type="password"
              required
              minLength={10}
              value={confirmPassword}
              onChange={(e) => setConfirmPassword(e.target.value)}
              placeholder="••••••••••"
              className="w-full px-3 py-2 rounded-lg bg-bg-card border border-border text-white placeholder-gray-500 outline-none focus:border-accent"
            />
          </div>

          <div className="flex items-center justify-end gap-2 pt-2 border-t border-border">
            <button
              type="button"
              disabled={isSubmitting}
              onClick={handleClose}
              className="px-3 py-1.5 rounded-lg border border-border bg-bg-card text-gray-300 hover:text-white"
            >
              Cancel
            </button>
            <button
              type="submit"
              disabled={isSubmitting}
              className="px-4 py-1.5 rounded-lg bg-accent hover:bg-accent-hover disabled:opacity-50 text-white font-semibold flex items-center gap-1.5"
            >
              {isSubmitting ? "Changing..." : "Update Password"}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
};
