import React from "react";
import type { TracePath } from "../api/types";

interface ProofPathPanelProps {
  paths: TracePath[];
  selectedPathIndex: number;
  onSelectPath: (index: number) => void;
}

const EDGE_LABEL_MAP: Record<string, string> = {
  HANDLED_BY: "handled by",
  IMPORTS: "imports",
  USES: "uses",
  DEPENDS_ON: "depends on",
};

export const ProofPathPanel: React.FC<ProofPathPanelProps> = ({
  paths,
  selectedPathIndex,
  onSelectPath,
}) => {
  if (!paths || paths.length === 0) {
    return null;
  }

  const activePath = paths[selectedPathIndex] || paths[0];

  return (
    <div className="bg-bg-surface border border-border rounded-xl p-4 shadow-sm space-y-3">
      {/* Path selector tabs if multiple paths */}
      <div className="flex items-center justify-between flex-wrap gap-2">
        <div className="flex items-center gap-2">
          <span className="text-xs font-semibold uppercase tracking-wider text-accent flex items-center gap-1.5">
            <svg className="w-4 h-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <circle cx="5" cy="6" r="3" />
              <path d="M5 9v6" />
              <circle cx="5" cy="18" r="3" />
              <path d="M12 12h7a2 2 0 0 1 2 2v4" />
              <circle cx="19" cy="18" r="3" />
            </svg>
            Proof Path
          </span>
          <span className="text-xs text-gray-400">
            ({paths.length} confirmed {paths.length === 1 ? "route" : "routes"} found)
          </span>
        </div>

        {paths.length > 1 && (
          <div className="flex items-center gap-1 bg-bg-card p-1 rounded-lg border border-border">
            {paths.slice(0, 3).map((_, idx) => (
              <button
                key={idx}
                type="button"
                onClick={() => onSelectPath(idx)}
                className={`px-3 py-1 rounded text-xs font-medium transition-all ${
                  selectedPathIndex === idx
                    ? "bg-accent text-white shadow-sm font-semibold"
                    : "text-gray-400 hover:text-gray-200"
                }`}
              >
                Path {idx + 1}
              </button>
            ))}
          </div>
        )}
      </div>

      {/* Breadcrumb with plain language edge tags */}
      <div className="flex items-center flex-wrap gap-1.5 py-1 px-2 bg-bg-card/70 border border-border/70 rounded-lg text-xs font-mono overflow-x-auto">
        {activePath.nodes.map((node, idx) => {
          const edge = activePath.edges[idx];
          const edgeType = edge ? edge.type : null;
          const plainEdgeLabel = edgeType
            ? EDGE_LABEL_MAP[edgeType] || edgeType.toLowerCase().replace(/_/g, " ")
            : null;

          return (
            <React.Fragment key={node.id || idx}>
              {/* Node Pill */}
              <span
                className={`px-2 py-1 rounded border inline-flex items-center gap-1.5 ${
                  node.label === "Entrypoint"
                    ? "bg-sky-500/15 border-sky-500/40 text-sky-300 font-bold"
                    : node.label === "Package"
                    ? "bg-amber-500/15 border-amber-500/40 text-amber-300 font-bold"
                    : "bg-slate-800/80 border-slate-700 text-slate-200"
                }`}
              >
                <span className="text-[10px] text-gray-400 uppercase font-sans">
                  [{node.label}]
                </span>
                <span>{node.name}</span>
              </span>

              {/* Hop Edge with Plain Language Label */}
              {plainEdgeLabel && (
                <div className="flex items-center gap-1 text-gray-400 px-1">
                  <span className="text-[10px] font-sans italic text-accent/90 bg-accent/10 px-1.5 py-0.5 rounded border border-accent/20">
                    {plainEdgeLabel}
                  </span>
                  <span className="text-gray-500">→</span>
                </div>
              )}
            </React.Fragment>
          );
        })}
      </div>
    </div>
  );
};
