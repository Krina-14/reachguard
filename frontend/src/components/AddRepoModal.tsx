import React, { useState, useRef, DragEvent } from "react";
import { useNavigate } from "react-router-dom";
import { apiFetch } from "../api/client";
import { ApiError } from "../api/types";

interface AddRepoModalProps {
  isOpen: boolean;
  onClose: () => void;
}

const GITHUB_URL_REGEX = /^https:\/\/github\.com\/[A-Za-z0-9_.-]+\/[A-Za-z0-9_.-]+\/?$/;
const MAX_FILE_SIZE_BYTES = 50 * 1024 * 1024; // 50 MB

export const AddRepoModal: React.FC<AddRepoModalProps> = ({ isOpen, onClose }) => {
  const navigate = useNavigate();
  const [activeTab, setActiveTab] = useState<"github" | "zip">("github");

  // Tab 1: GitHub URL state
  const [gitUrl, setGitUrl] = useState("");
  const [urlError, setUrlError] = useState<string | null>(null);

  // Tab 2: Zip upload state
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [isDragging, setIsDragging] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);

  // Submission state
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [serverError, setServerError] = useState<string | null>(null);

  if (!isOpen) return null;

  const handleUrlChange = (value: string) => {
    setGitUrl(value);
    setServerError(null);
    if (!value.trim()) {
      setUrlError(null);
      return;
    }
    if (!GITHUB_URL_REGEX.test(value.trim())) {
      setUrlError("URL must match: https://github.com/owner/repo");
    } else {
      setUrlError(null);
    }
  };

  const handleFileSelect = (file: File) => {
    setServerError(null);
    if (!file.name.toLowerCase().endsWith(".zip")) {
      setServerError("Only .zip archives are supported");
      setSelectedFile(null);
      return;
    }
    if (file.size > MAX_FILE_SIZE_BYTES) {
      setServerError(
        `File size (${(file.size / (1024 * 1024)).toFixed(1)} MB) exceeds the maximum limit of 50 MB`
      );
      setSelectedFile(null);
      return;
    }
    setSelectedFile(file);
  };

  const handleDragOver = (e: DragEvent<HTMLDivElement>) => {
    e.preventDefault();
    setIsDragging(true);
  };

  const handleDragLeave = (e: DragEvent<HTMLDivElement>) => {
    e.preventDefault();
    setIsDragging(false);
  };

  const handleDrop = (e: DragEvent<HTMLDivElement>) => {
    e.preventDefault();
    setIsDragging(false);
    if (e.dataTransfer.files && e.dataTransfer.files.length > 0) {
      handleFileSelect(e.dataTransfer.files[0]);
    }
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setServerError(null);

    if (activeTab === "github") {
      const trimmedUrl = gitUrl.trim();
      if (!trimmedUrl) {
        setUrlError("GitHub URL is required");
        return;
      }
      if (!GITHUB_URL_REGEX.test(trimmedUrl)) {
        setUrlError("URL must match: https://github.com/owner/repo");
        return;
      }

      setIsSubmitting(true);
      try {
        const res = await apiFetch<{ repo_id: string; status: string }>(
          "/api/repos",
          {
            method: "POST",
            body: JSON.stringify({ git_url: trimmedUrl }),
          }
        );
        setIsSubmitting(false);
        onClose();
        navigate(`/repos/${res.repo_id}`);
      } catch (err: unknown) {
        setIsSubmitting(false);
        if (err instanceof ApiError) {
          setServerError(err.message || "Failed to enqueue repository analysis");
        } else if (err instanceof Error) {
          setServerError(err.message);
        } else {
          setServerError("Failed to enqueue repository analysis");
        }
      }
    } else {
      // Zip upload tab
      if (!selectedFile) {
        setServerError("Please select a .zip archive to upload");
        return;
      }

      setIsSubmitting(true);
      const formData = new FormData();
      formData.append("file", selectedFile);

      try {
        const res = await apiFetch<{ repo_id: string; status: string }>(
          "/api/repos/upload",
          {
            method: "POST",
            body: formData,
          }
        );
        setIsSubmitting(false);
        onClose();
        navigate(`/repos/${res.repo_id}`);
      } catch (err: unknown) {
        setIsSubmitting(false);
        if (err instanceof ApiError) {
          setServerError(err.message || "Failed to upload zip archive");
        } else if (err instanceof Error) {
          setServerError(err.message);
        } else {
          setServerError("Failed to upload zip archive");
        }
      }
    }
  };

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-labelledby="add-repo-modal-title"
      className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/75 backdrop-blur-sm animate-in fade-in duration-200"
    >
      <div className="bg-bg-surface border border-border rounded-xl max-w-lg w-full p-6 shadow-2xl relative">
        {/* Header */}
        <div className="flex items-center justify-between pb-4 border-b border-border mb-5">
          <div className="flex items-center gap-2.5">
            <div className="w-8 h-8 rounded-lg bg-accent/15 border border-accent/30 text-accent flex items-center justify-center">
              <svg
                className="w-5 h-5"
                viewBox="0 0 24 24"
                fill="none"
                stroke="currentColor"
                strokeWidth="2"
              >
                <path d="M12 5v14M5 12h14" />
              </svg>
            </div>
            <div>
              <h2
                id="add-repo-modal-title"
                className="text-lg font-bold text-white tracking-tight"
              >
                Analyze a Repository
              </h2>
              <p className="text-xs text-gray-400">
                Run AST call-graph extraction & reachability analysis
              </p>
            </div>
          </div>
          <button
            onClick={onClose}
            disabled={isSubmitting}
            className="p-1 rounded-lg text-gray-400 hover:text-white hover:bg-bg-subtle transition-colors disabled:opacity-50"
            aria-label="Close dialog"
          >
            <svg
              className="w-5 h-5"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth="2"
            >
              <line x1="18" y1="6" x2="6" y2="18" />
              <line x1="6" y1="6" x2="18" y2="18" />
            </svg>
          </button>
        </div>

        {/* Tab Switcher */}
        <div className="flex rounded-lg bg-bg-card p-1 border border-border mb-5">
          <button
            type="button"
            onClick={() => {
              setActiveTab("github");
              setServerError(null);
            }}
            className={`flex-1 flex items-center justify-center gap-2 py-2 px-3 rounded-md text-xs font-medium transition-colors ${
              activeTab === "github"
                ? "bg-accent text-white shadow-sm"
                : "text-gray-400 hover:text-white hover:bg-bg-subtle/50"
            }`}
          >
            <svg
              className="w-4 h-4"
              viewBox="0 0 24 24"
              fill="currentColor"
            >
              <path d="M12 0C5.37 0 0 5.37 0 12c0 5.31 3.435 9.795 8.205 11.385.6.105.825-.255.825-.57 0-.285-.015-1.23-.015-2.235-3.015.555-3.795-.735-4.035-1.41-.135-.345-.72-1.41-1.23-1.695-.42-.225-1.02-.78-.015-.795.945-.015 1.62.87 1.845 1.23 1.08 1.815 2.805 1.305 3.495.99.105-.78.42-1.305.765-1.605-2.67-.3-5.46-1.335-5.46-5.925 0-1.305.465-2.385 1.23-3.225-.12-.3-.54-1.53.12-3.18 0 0 1.005-.315 3.3 1.23.96-.27 1.98-.405 3-.405s2.04.135 3 .405c2.295-1.56 3.3-1.23 3.3-1.23.66 1.65.24 2.88.12 3.18.765.84 1.23 1.905 1.23 3.225 0 4.605-2.805 5.625-5.475 5.925.435.375.81 1.095.81 2.22 0 1.605-.015 2.895-.015 3.3 0 .315.225.69.825.57A12.02 12.02 0 0024 12c0-6.63-5.37-12-12-12z" />
            </svg>
            <span>GitHub URL</span>
          </button>
          <button
            type="button"
            onClick={() => {
              setActiveTab("zip");
              setServerError(null);
            }}
            className={`flex-1 flex items-center justify-center gap-2 py-2 px-3 rounded-md text-xs font-medium transition-colors ${
              activeTab === "zip"
                ? "bg-accent text-white shadow-sm"
                : "text-gray-400 hover:text-white hover:bg-bg-subtle/50"
            }`}
          >
            <svg
              className="w-4 h-4"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth="2"
            >
              <polyline points="21 8 21 21 3 21 3 8" />
              <rect x="1" y="3" width="22" height="5" />
              <line x1="10" y1="12" x2="14" y2="12" />
            </svg>
            <span>Upload ZIP</span>
          </button>
        </div>

        {/* Server Validation Error Banner */}
        {serverError && (
          <div
            role="alert"
            className="mb-4 p-3 rounded-lg bg-red-500/10 border border-red-500/30 text-red-400 text-xs flex items-start gap-2.5 animate-in fade-in"
          >
            <svg
              className="w-4 h-4 flex-shrink-0 mt-0.5"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth="2"
            >
              <circle cx="12" cy="12" r="10" />
              <line x1="12" y1="8" x2="12" y2="12" />
              <line x1="12" y1="16" x2="12.01" y2="16" />
            </svg>
            <span className="leading-relaxed">{serverError}</span>
          </div>
        )}

        <form onSubmit={handleSubmit}>
          {activeTab === "github" ? (
            <div className="space-y-3 mb-6">
              <div>
                <label
                  htmlFor="github-url-input"
                  className="block text-xs font-medium text-gray-300 uppercase tracking-wider mb-2"
                >
                  GitHub Repository URL
                </label>
                <div className="relative">
                  <input
                    id="github-url-input"
                    type="url"
                    required
                    disabled={isSubmitting}
                    value={gitUrl}
                    onChange={(e) => handleUrlChange(e.target.value)}
                    placeholder="https://github.com/owner/repository"
                    className={`w-full px-3.5 py-2.5 bg-bg-card border rounded-lg text-white text-sm placeholder-gray-500 focus:outline-none focus:ring-2 focus:ring-accent transition-all disabled:opacity-50 ${
                      urlError
                        ? "border-red-500/60 focus:border-red-500"
                        : "border-border focus:border-accent"
                    }`}
                  />
                </div>
                {urlError ? (
                  <p className="text-red-400 text-xs mt-1.5 flex items-center gap-1.5">
                    <svg
                      className="w-3.5 h-3.5 flex-shrink-0"
                      viewBox="0 0 24 24"
                      fill="none"
                      stroke="currentColor"
                      strokeWidth="2"
                    >
                      <circle cx="12" cy="12" r="10" />
                      <line x1="12" y1="8" x2="12" y2="12" />
                      <line x1="12" y1="16" x2="12.01" y2="16" />
                    </svg>
                    <span>{urlError}</span>
                  </p>
                ) : (
                  <p className="text-gray-400 text-xs mt-1.5 flex items-center gap-1.5">
                    <svg
                      className="w-3.5 h-3.5 text-accent flex-shrink-0"
                      viewBox="0 0 24 24"
                      fill="none"
                      stroke="currentColor"
                      strokeWidth="2"
                    >
                      <circle cx="12" cy="12" r="10" />
                      <line x1="12" y1="16" x2="12" y2="12" />
                      <line x1="12" y1="8" x2="12.01" y2="8" />
                    </svg>
                    <span>
                      Rule: Must be a public repository URL matching{" "}
                      <code className="text-accent font-mono text-[11px]">
                        https://github.com/owner/repo
                      </code>
                    </span>
                  </p>
                )}
              </div>
            </div>
          ) : (
            <div className="space-y-4 mb-6">
              <div
                onDragOver={handleDragOver}
                onDragLeave={handleDragLeave}
                onDrop={handleDrop}
                onClick={() => fileInputRef.current?.click()}
                className={`border-2 border-dashed rounded-xl p-6 text-center cursor-pointer transition-all ${
                  isDragging
                    ? "border-accent bg-accent/10"
                    : "border-border hover:border-gray-500 bg-bg-card/50"
                }`}
              >
                <input
                  type="file"
                  ref={fileInputRef}
                  accept=".zip"
                  className="hidden"
                  onChange={(e) => {
                    if (e.target.files && e.target.files[0]) {
                      handleFileSelect(e.target.files[0]);
                    }
                  }}
                />

                <div className="w-12 h-12 rounded-full bg-accent/15 border border-accent/30 text-accent mx-auto flex items-center justify-center mb-3">
                  <svg
                    className="w-6 h-6"
                    viewBox="0 0 24 24"
                    fill="none"
                    stroke="currentColor"
                    strokeWidth="2"
                  >
                    <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" />
                    <polyline points="17 8 12 3 7 8" />
                    <line x1="12" y1="3" x2="12" y2="15" />
                  </svg>
                </div>

                {selectedFile ? (
                  <div>
                    <p className="text-sm font-semibold text-white truncate max-w-xs mx-auto">
                      {selectedFile.name}
                    </p>
                    <p className="text-xs text-accent mt-0.5">
                      {(selectedFile.size / (1024 * 1024)).toFixed(2)} MB • Click to
                      change
                    </p>
                  </div>
                ) : (
                  <div>
                    <p className="text-sm font-medium text-white">
                      Drag & drop your Python project .zip archive here
                    </p>
                    <p className="text-xs text-gray-400 mt-1">
                      or click to browse your computer
                    </p>
                  </div>
                )}

                <div className="mt-3 inline-flex items-center gap-1.5 px-2.5 py-1 rounded bg-bg-surface border border-border text-[11px] text-gray-400">
                  <svg
                    className="w-3.5 h-3.5 text-amber-400"
                    viewBox="0 0 24 24"
                    fill="none"
                    stroke="currentColor"
                    strokeWidth="2"
                  >
                    <circle cx="12" cy="12" r="10" />
                    <line x1="12" y1="8" x2="12" y2="12" />
                    <line x1="12" y1="16" x2="12.01" y2="16" />
                  </svg>
                  <span>Maximum archive size: 50 MB</span>
                </div>
              </div>
            </div>
          )}

          {/* Dialog Action Buttons */}
          <div className="flex items-center justify-end gap-3 pt-3 border-t border-border">
            <button
              type="button"
              disabled={isSubmitting}
              onClick={onClose}
              className="px-4 py-2 rounded-lg text-sm text-gray-300 hover:text-white bg-bg-card border border-border hover:border-gray-600 transition-colors disabled:opacity-50"
            >
              Cancel
            </button>
            <button
              type="submit"
              disabled={
                isSubmitting ||
                (activeTab === "github" && (!gitUrl || Boolean(urlError))) ||
                (activeTab === "zip" && !selectedFile)
              }
              className="px-5 py-2 rounded-lg text-sm font-semibold text-white bg-accent hover:bg-accent-hover active:bg-accent/90 disabled:opacity-50 disabled:cursor-not-allowed shadow-lg shadow-accent/20 transition-all flex items-center gap-2"
            >
              {isSubmitting ? (
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
                  <span>Queueing Analysis...</span>
                </>
              ) : (
                <span>Start Analysis</span>
              )}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
};
