import React from "react";
import type { Verdict } from "../api/types";

export interface VerdictVisual {
  label: string;
  badgeClass: string;
  dotClass: string;
  iconName: "path" | "question" | "dash";
  icon: React.ReactNode;
  note?: string;
}

export const VERDICT_CONFIG: Record<Verdict, VerdictVisual> = {
  reachable_in_model: {
    label: "Reachable in model",
    badgeClass: "bg-red-500/15 text-red-400 border border-red-500/30",
    dotClass: "bg-red-500",
    iconName: "path",
    icon: (
      <svg
        className="w-3.5 h-3.5"
        viewBox="0 0 24 24"
        fill="none"
        stroke="currentColor"
        strokeWidth="2.2"
        strokeLinecap="round"
        strokeLinejoin="round"
        aria-label="path"
      >
        {/* Path icon showing connection between entrypoint and destination */}
        <circle cx="5" cy="6" r="3" />
        <circle cx="19" cy="18" r="3" />
        <path d="M5 9v3a6 6 0 0 0 6 6h5" />
      </svg>
    ),
  },
  unknown: {
    label: "Unknown",
    badgeClass: "bg-amber-500/15 text-amber-400 border border-amber-500/30",
    dotClass: "bg-amber-500",
    iconName: "question",
    icon: (
      <svg
        className="w-3.5 h-3.5"
        viewBox="0 0 24 24"
        fill="none"
        stroke="currentColor"
        strokeWidth="2.2"
        strokeLinecap="round"
        strokeLinejoin="round"
        aria-label="question"
      >
        {/* Question mark icon representing blind spots */}
        <circle cx="12" cy="12" r="10" />
        <path d="M9.09 9a3 3 0 0 1 5.83 1c0 2-3 3-3 3" />
        <line x1="12" y1="17" x2="12.01" y2="17" />
      </svg>
    ),
  },
  no_path_found: {
    label: "No path found in model",
    badgeClass: "bg-slate-500/15 text-slate-400 border border-slate-500/30",
    dotClass: "bg-slate-500",
    iconName: "dash",
    icon: (
      <svg
        className="w-3.5 h-3.5"
        viewBox="0 0 24 24"
        fill="none"
        stroke="currentColor"
        strokeWidth="2.5"
        strokeLinecap="round"
        strokeLinejoin="round"
        aria-label="dash"
      >
        {/* Dash icon */}
        <line x1="5" y1="12" x2="19" y2="12" />
      </svg>
    ),
    note: "This is not proof of safety.",
  },
};
