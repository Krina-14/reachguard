import React from "react";
import clsx from "clsx";
import type { RepoStatus } from "../api/types";

interface StatusChipProps {
  status: RepoStatus;
  stageDetail?: string | null;
  className?: string;
  showDot?: boolean;
}

export const StatusChip: React.FC<StatusChipProps> = ({
  status,
  stageDetail,
  className,
  showDot = false,
}) => {
  switch (status) {
    case "ready":
      return (
        <span
          className={clsx(
            "inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-full text-xs font-medium bg-emerald-500/15 text-emerald-400 border border-emerald-500/30",
            className
          )}
          title="Analysis complete and call graph ready"
        >
          {showDot ? (
            <span className="w-1.5 h-1.5 rounded-full bg-emerald-400" />
          ) : (
            <svg
              className="w-3.5 h-3.5 flex-shrink-0"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth="2.5"
              strokeLinecap="round"
              strokeLinejoin="round"
            >
              <polyline points="20 6 9 17 4 12" />
            </svg>
          )}
          <span>Ready</span>
        </span>
      );

    case "failed":
      return (
        <span
          className={clsx(
            "inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-full text-xs font-medium bg-red-500/15 text-red-400 border border-red-500/30",
            className
          )}
          title={stageDetail || "Analysis failed"}
        >
          {showDot ? (
            <span className="w-1.5 h-1.5 rounded-full bg-red-400" />
          ) : (
            <svg
              className="w-3.5 h-3.5 flex-shrink-0"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth="2.5"
              strokeLinecap="round"
              strokeLinejoin="round"
            >
              <circle cx="12" cy="12" r="10" />
              <line x1="12" y1="8" x2="12" y2="12" />
              <line x1="12" y1="16" x2="12.01" y2="16" />
            </svg>
          )}
          <span>Failed</span>
        </span>
      );

    case "cloning":
      return (
        <span
          className={clsx(
            "inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-full text-xs font-medium bg-sky-500/15 text-sky-400 border border-sky-500/30 animate-pulse",
            className
          )}
          title={stageDetail || "Cloning repository"}
        >
          <svg
            className="animate-spin w-3 h-3 flex-shrink-0 text-sky-400"
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
          <span>Cloning</span>
        </span>
      );

    case "parsing":
      return (
        <span
          className={clsx(
            "inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-full text-xs font-medium bg-indigo-500/15 text-indigo-400 border border-indigo-500/30 animate-pulse",
            className
          )}
          title={stageDetail || "Parsing AST & build call graph"}
        >
          <svg
            className="animate-spin w-3 h-3 flex-shrink-0 text-indigo-400"
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
          <span>Parsing</span>
        </span>
      );

    case "scanning":
      return (
        <span
          className={clsx(
            "inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-full text-xs font-medium bg-purple-500/15 text-purple-400 border border-purple-500/30 animate-pulse",
            className
          )}
          title={stageDetail || "Scanning dependencies & OSV"}
        >
          <svg
            className="animate-spin w-3 h-3 flex-shrink-0 text-purple-400"
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
          <span>Scanning</span>
        </span>
      );

    case "queued":
    default:
      return (
        <span
          className={clsx(
            "inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-full text-xs font-medium bg-slate-500/15 text-slate-400 border border-slate-500/30",
            className
          )}
          title={stageDetail || "Queued for analysis"}
        >
          <svg
            className="w-3 h-3 flex-shrink-0 text-slate-400"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            strokeWidth="2"
            strokeLinecap="round"
            strokeLinejoin="round"
          >
            <circle cx="12" cy="12" r="10" />
            <polyline points="12 6 12 12 16 14" />
          </svg>
          <span>Queued</span>
        </span>
      );
  }
};
