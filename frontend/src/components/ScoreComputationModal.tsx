import React from "react";

interface ScoreComputationModalProps {
  isOpen: boolean;
  onClose: () => void;
}

export const ScoreComputationModal: React.FC<ScoreComputationModalProps> = ({
  isOpen,
  onClose,
}) => {
  if (!isOpen) return null;

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-labelledby="score-modal-title"
      className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/75 backdrop-blur-sm animate-in fade-in duration-200"
    >
      <div className="bg-bg-surface border border-border rounded-xl max-w-lg w-full p-6 shadow-2xl relative">
        <div className="flex items-center justify-between pb-4 border-b border-border mb-4">
          <div className="flex items-center gap-2.5">
            <div className="w-8 h-8 rounded-lg bg-accent/15 border border-accent/30 text-accent flex items-center justify-center">
              <svg
                className="w-4 h-4"
                viewBox="0 0 24 24"
                fill="none"
                stroke="currentColor"
                strokeWidth="2"
              >
                <circle cx="12" cy="12" r="10" />
                <line x1="12" y1="16" x2="12" y2="12" />
                <line x1="12" y1="8" x2="12.01" y2="8" />
              </svg>
            </div>
            <div>
              <h2
                id="score-modal-title"
                className="text-lg font-bold text-white tracking-tight"
              >
                How Finding Scores Are Computed
              </h2>
              <p className="text-xs text-gray-400">
                Reachability-weighted vulnerability prioritization formula
              </p>
            </div>
          </div>
          <button
            onClick={onClose}
            className="p-1 rounded-lg text-gray-400 hover:text-white hover:bg-bg-subtle transition-colors"
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

        <div className="space-y-4 text-xs text-gray-300">
          {/* Formula Display */}
          <div className="p-3.5 bg-bg-card rounded-lg border border-border text-center font-mono text-sm text-accent">
            Score = round(100 × (0.5 × Reach + 0.3 × Severity + 0.2 × Exposure))
          </div>

          <p className="text-gray-400 leading-relaxed">
            ReachGuard scores each finding from 0 to 100 to prioritize CVEs that can
            actually be triggered from public entrypoints over dormant libraries:
          </p>

          {/* Component Breakdown */}
          <div className="space-y-3">
            {/* Reach */}
            <div className="p-3 bg-bg-card/50 rounded-lg border border-border">
              <div className="flex items-center justify-between font-semibold text-white mb-1">
                <span className="flex items-center gap-1.5">
                  <span className="w-2 h-2 rounded-full bg-red-400" />
                  Reachability Weight: 50%
                </span>
                <span className="font-mono text-accent">w = 0.50</span>
              </div>
              <ul className="text-gray-400 space-y-1 pl-4 list-disc text-[11px]">
                <li>
                  <strong className="text-red-400">Reachable in model</strong>: 1.0
                  (Public/authenticated call path leads directly to package)
                </li>
                <li>
                  <strong className="text-amber-400">Unknown</strong>: 0.5 (Dynamic
                  imports or unparseable files obstruct static reach proof)
                </li>
                <li>
                  <strong className="text-slate-400">No path found</strong>: 0.15
                  (Package present, but no AST call path from public entrypoints)
                </li>
              </ul>
            </div>

            {/* Severity */}
            <div className="p-3 bg-bg-card/50 rounded-lg border border-border">
              <div className="flex items-center justify-between font-semibold text-white mb-1">
                <span className="flex items-center gap-1.5">
                  <span className="w-2 h-2 rounded-full bg-purple-400" />
                  Severity Weight: 30%
                </span>
                <span className="font-mono text-accent">w = 0.30</span>
              </div>
              <p className="text-gray-400 text-[11px]">
                Normalized OSV / CVSS severity score:
                <br />
                <code className="text-gray-300">
                  CRITICAL = 1.0 • HIGH = 0.75 • MODERATE = 0.50 • LOW = 0.25 • UNKNOWN = 0.40
                </code>
              </p>
            </div>

            {/* Exposure */}
            <div className="p-3 bg-bg-card/50 rounded-lg border border-border">
              <div className="flex items-center justify-between font-semibold text-white mb-1">
                <span className="flex items-center gap-1.5">
                  <span className="w-2 h-2 rounded-full bg-blue-400" />
                  Public Exposure Weight: 20%
                </span>
                <span className="font-mono text-accent">w = 0.20</span>
              </div>
              <p className="text-gray-400 text-[11px]">
                Ratio of reaching public entrypoints to total public entrypoints:
                <br />
                <code className="text-gray-300">
                  Exposure = (Reaching Public Entrypoints) / (Total Public Entrypoints)
                </code>
              </p>
            </div>
          </div>

          <div className="p-3 rounded-lg bg-amber-500/10 border border-amber-500/25 text-amber-300/90 text-[11px] leading-relaxed">
            <strong>Important Safety Note:</strong> A lower score or "No path found"
            indicates that our static AST model detected no execution path; it is{" "}
            <strong>not mathematical proof of safety</strong>. Dynamic reflection,
            runtime evals, or unparsed modules can create non-modeled call flows.
          </div>
        </div>

        <div className="flex justify-end pt-4 border-t border-border mt-4">
          <button
            type="button"
            onClick={onClose}
            className="px-4 py-2 rounded-lg text-xs font-semibold text-white bg-accent hover:bg-accent-hover transition-colors"
          >
            Close
          </button>
        </div>
      </div>
    </div>
  );
};
