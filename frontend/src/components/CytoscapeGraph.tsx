import React, { useEffect, useRef, useState, useCallback } from "react";
import cytoscape, { Core, EventObject } from "cytoscape";
import type { GraphResponse } from "../api/types";

interface CytoscapeGraphProps {
  graphData: GraphResponse;
  highlightedNodeIds?: string[];
  highlightedEdgeIds?: string[];
  height?: string;
  compact?: boolean;
  showLegend?: boolean;
}

export const CytoscapeGraph: React.FC<CytoscapeGraphProps> = ({
  graphData,
  highlightedNodeIds,
  highlightedEdgeIds,
  height,
  compact = false,
  showLegend,
}) => {
  const containerRef = useRef<HTMLDivElement>(null);
  const cyRef = useRef<Core | null>(null);
  const animationFrameRef = useRef<number | null>(null);

  const [selectedNodeProps, setSelectedNodeProps] = useState<{
    id: string;
    label: string;
    name: string;
    props: Record<string, unknown>;
  } | null>(null);

  // Initialize and update Cytoscape graph
  useEffect(() => {
    if (!containerRef.current) return;

    // Destroy existing instance if any
    if (cyRef.current) {
      cyRef.current.destroy();
      cyRef.current = null;
    }

    if (animationFrameRef.current) {
      cancelAnimationFrame(animationFrameRef.current);
      animationFrameRef.current = null;
    }

    // Determine highlight sets
    const activeHighlightNodes = new Set(
      highlightedNodeIds !== undefined
        ? highlightedNodeIds
        : graphData.highlight?.nodes || []
    );
    const activeHighlightEdges = new Set(
      highlightedEdgeIds !== undefined
        ? highlightedEdgeIds
        : graphData.highlight?.edges || []
    );
    const hasHighlight = activeHighlightNodes.size > 0;

    // Filter valid nodes and build node ID set to prevent dangling edge crashes
    const validNodeIds = new Set<string>();
    const cyNodes = graphData.nodes.map((node) => {
      validNodeIds.add(node.id);
      const isHighlighted = activeHighlightNodes.has(node.id);
      return {
        data: {
          id: node.id,
          label: node.label,
          name: node.name || node.id,
          props: node.props || {},
        },
        classes: `${node.label} ${
          isHighlighted ? "highlighted" : hasHighlight ? "dimmed" : ""
        }`,
      };
    });

    // Only include edges whose source and target both exist in validNodeIds
    const cyEdges = graphData.edges
      .filter((edge) => validNodeIds.has(edge.source) && validNodeIds.has(edge.target))
      .map((edge) => {
        const isHighlighted =
          activeHighlightEdges.has(edge.id) ||
          (activeHighlightNodes.has(edge.source) && activeHighlightNodes.has(edge.target));
        return {
          data: {
            id: edge.id,
            source: edge.source,
            target: edge.target,
            type: edge.type || "",
          },
          classes: isHighlighted ? "highlighted" : hasHighlight ? "dimmed" : "",
        };
      });

    // Identify entrypoint nodes as roots for breadthfirst layout
    const entrypointNodeIds = graphData.nodes
      .filter((n) => n.label === "Entrypoint")
      .map((n) => `#${CSS.escape(n.id)}`);

    const cy = cytoscape({
      container: containerRef.current,
      elements: [...cyNodes, ...cyEdges],
      style: [
        {
          selector: "node",
          style: {
            label: "data(name)",
            color: "#f1f5f9",
            "font-size": "11px",
            "font-family": "ui-sans-serif, system-ui, sans-serif",
            "text-valign": "center",
            "text-halign": "center",
            "text-wrap": "wrap",
            "text-max-width": "110px",
            width: "120px",
            height: "44px",
            "background-color": "#1e293b",
            "border-width": 1.5,
            "border-color": "#475569",
            shape: "round-rectangle",
            "transition-property": "opacity, border-color, border-width, line-color",
            "transition-duration": 0.25,
          },
        },
        {
          selector: "node.Entrypoint",
          style: {
            "background-color": "#0369a1",
            "border-color": "#38bdf8",
            "border-width": 2,
            shape: "round-rectangle",
            color: "#ffffff",
            "font-weight": "bold",
          },
        },
        {
          selector: "node.Module",
          style: {
            "background-color": "#1e293b",
            "border-color": "#64748b",
            "border-width": 1.5,
            shape: "round-rectangle",
            color: "#e2e8f0",
          },
        },
        {
          selector: "node.Package",
          style: {
            "background-color": "#78350f",
            "border-color": "#f59e0b",
            "border-width": 2,
            shape: "round-rectangle",
            color: "#fef3c7",
            "font-weight": "bold",
          },
        },
        {
          selector: "node.Vulnerability",
          style: {
            "background-color": "#7f1d1d",
            "border-color": "#ef4444",
            "border-width": 2,
            shape: "diamond",
            color: "#fee2e2",
            "font-weight": "bold",
            width: "130px",
            height: "50px",
          },
        },
        {
          selector: "node.highlighted",
          style: {
            "border-color": "#38bdf8",
            "border-width": 3,
            "border-opacity": 1,
            opacity: 1,
            "font-weight": "bold",
            "z-index": 100,
          },
        },
        {
          selector: "node.highlighted.Vulnerability",
          style: {
            "border-color": "#ef4444",
          },
        },
        {
          selector: "node.dimmed",
          style: {
            opacity: 0.35,
          },
        },
        {
          selector: "edge",
          style: {
            width: 1.5,
            "line-color": "#475569",
            "target-arrow-color": "#475569",
            "target-arrow-shape": "triangle",
            "curve-style": "bezier",
            "arrow-scale": 0.8,
            label: "data(type)",
            "font-size": "9px",
            color: "#94a3b8",
            "text-rotation": "autorotate",
            "text-background-color": "#090d16",
            "text-background-opacity": 0.8,
            "text-background-padding": "2px",
            "transition-property": "opacity, line-color, width",
            "transition-duration": 0.25,
          },
        },
        {
          selector: "edge.highlighted",
          style: {
            width: 3,
            "line-color": "#38bdf8",
            "target-arrow-color": "#38bdf8",
            "arrow-scale": 1.1,
            "line-style": "dashed",
            "line-dash-pattern": [6, 4],
            opacity: 1,
            color: "#38bdf8",
            "font-weight": "bold",
            "z-index": 90,
          },
        },
        {
          selector: "edge.dimmed",
          style: {
            opacity: 0.2,
            width: 1,
          },
        },
      ],
      layout: {
        name: "breadthfirst",
        directed: true,
        roots: entrypointNodeIds.length > 0 ? entrypointNodeIds : undefined,
        padding: compact ? 20 : 40,
        spacingFactor: compact ? 1.15 : 1.4,
        animate: false,
      },
    });

    cyRef.current = cy;

    // Node click handler: show side card with properties
    cy.on("tap", "node", (evt: EventObject) => {
      const node = evt.target;
      setSelectedNodeProps({
        id: node.id(),
        label: node.data("label") || "Unknown",
        name: node.data("name") || node.id(),
        props: node.data("props") || {},
      });
    });

    // Clicking canvas background deselects
    cy.on("tap", (evt: EventObject) => {
      if (evt.target === cy) {
        setSelectedNodeProps(null);
      }
    });

    // Flowing dash animation on highlighted edges
    let dashOffset = 0;
    const animateDashes = () => {
      dashOffset = (dashOffset - 0.75) % 24;
      if (cyRef.current) {
        cyRef.current.edges(".highlighted").style("line-dash-offset", dashOffset);
      }
      animationFrameRef.current = requestAnimationFrame(animateDashes);
    };
    animationFrameRef.current = requestAnimationFrame(animateDashes);

    return () => {
      if (animationFrameRef.current) {
        cancelAnimationFrame(animationFrameRef.current);
      }
      cy.destroy();
      cyRef.current = null;
    };
  }, [graphData, highlightedNodeIds, highlightedEdgeIds, compact]);

  // Controls
  const handleResetView = useCallback(() => {
    if (cyRef.current) {
      cyRef.current.fit(undefined, 30);
      cyRef.current.center();
    }
  }, []);

  const handleZoomIn = useCallback(() => {
    if (cyRef.current) {
      cyRef.current.zoom({
        level: cyRef.current.zoom() * 1.25,
        renderedPosition: {
          x: cyRef.current.width() / 2,
          y: cyRef.current.height() / 2,
        },
      });
    }
  }, []);

  const handleZoomOut = useCallback(() => {
    if (cyRef.current) {
      cyRef.current.zoom({
        level: cyRef.current.zoom() * 0.8,
        renderedPosition: {
          x: cyRef.current.width() / 2,
          y: cyRef.current.height() / 2,
        },
      });
    }
  }, []);

  const shouldShowLegend = showLegend ?? !compact;

  return (
    <div
      style={{ height: height || "520px" }}
      className="relative w-full bg-[#090d16] border border-border rounded-xl overflow-hidden shadow-inner"
    >
      {/* Cytoscape DOM container */}
      <div ref={containerRef} className="w-full h-full cursor-grab active:cursor-grabbing" />

      {/* Floating Toolbar: Zoom & Reset */}
      <div className="absolute top-2.5 right-2.5 flex items-center gap-1 bg-bg-surface/90 backdrop-blur-md p-1 rounded-lg border border-border shadow-lg z-20 text-xs">
        <button
          type="button"
          onClick={handleZoomIn}
          title="Zoom in"
          className="w-6 h-6 flex items-center justify-center rounded bg-bg-card hover:bg-slate-700 text-gray-200 text-xs font-bold border border-border transition-colors"
        >
          +
        </button>
        <button
          type="button"
          onClick={handleZoomOut}
          title="Zoom out"
          className="w-6 h-6 flex items-center justify-center rounded bg-bg-card hover:bg-slate-700 text-gray-200 text-xs font-bold border border-border transition-colors"
        >
          −
        </button>
        <div className="h-3.5 w-[1px] bg-border mx-0.5" />
        <button
          type="button"
          onClick={handleResetView}
          title="Reset graph view"
          className="px-2 h-6 flex items-center gap-1 rounded bg-bg-card hover:bg-slate-700 text-gray-200 text-[11px] font-medium border border-border transition-colors"
        >
          <svg className="w-3 h-3" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
            <path d="M3 12a9 9 0 1 0 9-9 9.75 9.75 0 0 0-6.74 2.74L3 8" />
            <path d="M3 3v5h5" />
          </svg>
          {!compact && <span>Reset view</span>}
        </button>
      </div>

      {/* Node Legend (hidden in compact mode unless explicitly enabled) */}
      {shouldShowLegend && (
        <div className="absolute bottom-3 left-3 flex flex-wrap items-center gap-3 bg-bg-surface/90 backdrop-blur-md px-3 py-1.5 rounded-lg border border-border shadow-lg text-[11px] text-gray-300 z-20">
          <span className="flex items-center gap-1.5">
            <span className="w-2.5 h-2.5 rounded bg-[#0369a1] border border-[#38bdf8]" />
            Entrypoint
          </span>
          <span className="flex items-center gap-1.5">
            <span className="w-2.5 h-2.5 rounded bg-[#1e293b] border border-[#64748b]" />
            Module
          </span>
          <span className="flex items-center gap-1.5">
            <span className="w-2.5 h-2.5 rounded bg-[#78350f] border border-[#f59e0b]" />
            Package
          </span>
          <span className="flex items-center gap-1.5">
            <span className="w-2.5 h-2.5 rounded-sm bg-[#7f1d1d] border border-[#ef4444] rotate-45" />
            Vulnerability
          </span>
          <span className="flex items-center gap-1.5 text-accent font-medium">
            <span className="w-3 h-[2px] bg-accent border-t border-dashed" />
            Active Path
          </span>
        </div>
      )}

      {/* Side Card: Selected Node Properties */}
      {selectedNodeProps && (
        <div className="absolute top-3 left-3 w-72 max-h-[480px] bg-bg-surface/95 backdrop-blur-md border border-border rounded-xl p-4 shadow-2xl z-30 overflow-y-auto">
          <div className="flex items-start justify-between pb-2 border-b border-border">
            <div>
              <span className="text-[10px] font-mono uppercase tracking-wider text-accent font-semibold">
                {selectedNodeProps.label}
              </span>
              <h4 className="text-sm font-semibold text-white truncate max-w-[200px]" title={selectedNodeProps.name}>
                {selectedNodeProps.name}
              </h4>
            </div>
            <button
              type="button"
              onClick={() => setSelectedNodeProps(null)}
              className="text-gray-400 hover:text-white p-1 rounded transition-colors"
            >
              ✕
            </button>
          </div>

          <div className="mt-3 space-y-2 text-xs">
            <div>
              <span className="text-gray-400 block text-[10px] uppercase font-mono">ID</span>
              <span className="text-gray-200 font-mono break-all text-[11px]">
                {selectedNodeProps.id}
              </span>
            </div>

            {Boolean(selectedNodeProps.props.file) && (
              <div>
                <span className="text-gray-400 block text-[10px] uppercase font-mono">File</span>
                <span className="text-gray-200 font-mono break-all">
                  {String(selectedNodeProps.props.file)}
                </span>
              </div>
            )}

            {selectedNodeProps.props.line !== undefined && (
              <div>
                <span className="text-gray-400 block text-[10px] uppercase font-mono">Line</span>
                <span className="text-gray-200 font-mono">
                  {String(selectedNodeProps.props.line)}
                </span>
              </div>
            )}

            {Boolean(selectedNodeProps.props.version) && (
              <div>
                <span className="text-gray-400 block text-[10px] uppercase font-mono">Version</span>
                <span className="text-gray-200 font-mono">
                  {String(selectedNodeProps.props.version)}
                </span>
              </div>
            )}

            {Boolean(selectedNodeProps.props.method) && (
              <div>
                <span className="text-gray-400 block text-[10px] uppercase font-mono">Method</span>
                <span className="text-cyan-400 font-mono font-bold">
                  {String(selectedNodeProps.props.method)}
                </span>
              </div>
            )}

            {/* Other properties */}
            {Object.entries(selectedNodeProps.props)
              .filter(([k]) => !["file", "line", "version", "method", "id", "name"].includes(k))
              .map(([key, val]) => (
                <div key={key}>
                  <span className="text-gray-400 block text-[10px] uppercase font-mono">{key}</span>
                  <span className="text-gray-300 font-mono text-[11px] break-all">
                    {typeof val === "object" ? JSON.stringify(val) : String(val)}
                  </span>
                </div>
              ))}
          </div>
        </div>
      )}
    </div>
  );
};
