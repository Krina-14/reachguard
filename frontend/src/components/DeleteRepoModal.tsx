import React, { useState } from "react";
import { apiFetch } from "../api/client";
import { ApiError, type Repo } from "../api/types";

interface DeleteRepoModalProps {
  repo: Repo | null;
  isOpen: boolean;
  onClose: () => void;
  onDeleted: () => void;
}

export const DeleteRepoModal: React.FC<DeleteRepoModalProps> = ({
  repo,
  isOpen,
  onClose,
  onDeleted,
}) => {
  const [isDeleting, setIsDeleting] = useState(false);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);

  if (!isOpen || !repo) return null;

  const handleDelete = async () => {
    setIsDeleting(true);
    setErrorMessage(null);

    try {
      await apiFetch<void>(`/api/repos/${repo.id}`, {
        method: "DELETE",
      });
      setIsDeleting(false);
      onDeleted();
      onClose();
    } catch (err: unknown) {
      setIsDeleting(false);
      if (err instanceof ApiError) {
        setErrorMessage(err.message || "Failed to delete repository");
      } else if (err instanceof Error) {
        setErrorMessage(err.message);
      } else {
        setErrorMessage("An unexpected error occurred while deleting repository");
      }
    }
  };

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-labelledby="delete-repo-title"
      className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/70 backdrop-blur-sm animate-in fade-in duration-200"
    >
      <div className="bg-bg-surface border border-border rounded-xl max-w-md w-full p-6 shadow-2xl relative">
        <div className="w-12 h-12 rounded-full bg-red-500/10 border border-red-500/20 text-red-400 flex items-center justify-center mb-4">
          <svg
            className="w-6 h-6"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            strokeWidth="2"
            strokeLinecap="round"
            strokeLinejoin="round"
          >
            <polyline points="3 6 5 6 21 6" />
            <path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2" />
            <line x1="10" y1="11" x2="10" y2="17" />
            <line x1="14" y1="11" x2="14" y2="17" />
          </svg>
        </div>

        <h3 id="delete-repo-title" className="text-lg font-bold text-white mb-2">
          Delete Repository Graph
        </h3>
        <p className="text-sm text-gray-300 mb-2">
          Are you sure you want to permanently delete:
        </p>
        <div className="p-3 bg-bg-card rounded-lg border border-border font-mono text-xs text-white truncate mb-4">
          {repo.source}
        </div>
        <p className="text-xs text-red-400/90 mb-6">
          This will drop the dedicated FalkorDB repository graph, purge all AST
          call nodes, and delete associated finding records. This action cannot be
          undone.
        </p>

        {errorMessage && (
          <div className="mb-4 p-3 rounded-lg bg-red-500/10 border border-red-500/30 text-red-400 text-xs">
            {errorMessage}
          </div>
        )}

        <div className="flex items-center justify-end gap-3">
          <button
            type="button"
            disabled={isDeleting}
            onClick={onClose}
            className="px-4 py-2 rounded-lg text-sm text-gray-300 hover:text-white bg-bg-card border border-border hover:border-gray-600 transition-colors disabled:opacity-50"
          >
            Cancel
          </button>
          <button
            type="button"
            disabled={isDeleting}
            onClick={handleDelete}
            className="px-4 py-2 rounded-lg text-sm font-semibold text-white bg-red-600 hover:bg-red-500 active:bg-red-700 disabled:opacity-50 transition-colors flex items-center gap-2"
          >
            {isDeleting ? (
              <>
                <svg
                  className="animate-spin h-4 w-4 text-white"
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
                <span>Deleting...</span>
              </>
            ) : (
              <span>Confirm Delete</span>
            )}
          </button>
        </div>
      </div>
    </div>
  );
};
