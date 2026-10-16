import React from "react";
import type { Verdict } from "../api/types";
import { VERDICT_CONFIG } from "../lib/verdict";
import { cn } from "../lib/utils";

interface VerdictBadgeProps {
  verdict: Verdict;
  showNote?: boolean;
  className?: string;
}

export const VerdictBadge: React.FC<VerdictBadgeProps> = ({
  verdict,
  showNote = false,
  className,
}) => {
  const config = VERDICT_CONFIG[verdict] || VERDICT_CONFIG.unknown;

  return (
    <div className={cn("inline-flex flex-col gap-1", className)}>
      <span
        className={cn(
          "inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-full text-xs font-medium tracking-wide",
          config.badgeClass
        )}
      >
        <span className="flex-shrink-0">{config.icon}</span>
        <span>{config.label}</span>
      </span>
      {showNote && config.note && (
        <span className="text-[11px] text-gray-400 italic">
          {config.note}
        </span>
      )}
    </div>
  );
};
