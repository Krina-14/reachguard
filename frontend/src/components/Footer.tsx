import React from "react";

export const Footer: React.FC = () => {
  return (
    <footer className="mt-auto border-t border-border bg-bg-surface/80 backdrop-blur-sm py-4 px-6 text-xs">
      <div className="max-w-7xl mx-auto flex flex-col md:flex-row items-center justify-between gap-3 text-gray-400">
        <div className="flex items-center gap-2">
          <div className="w-5 h-5 rounded bg-accent/15 border border-accent/30 text-accent flex items-center justify-center">
            <svg
              className="w-3 h-3"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth="2.2"
            >
              <path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z" />
            </svg>
          </div>
          <span className="font-semibold text-gray-200">ReachGuard</span>
          <span className="text-gray-600">|</span>
          <span className="text-[11px] text-gray-400">
            Reachability-driven vulnerability intelligence
          </span>
        </div>

        {/* Honest Limits Notice */}
        <p className="text-[11px] text-gray-400 text-center md:text-right max-w-2xl leading-relaxed">
          <span className="text-gray-300 font-medium">Notice:</span> Python only. Module-level analysis. Heuristic auth detection. Results show reachability in the analyzed model, not proof of exploitability.
        </p>
      </div>
    </footer>
  );
};
