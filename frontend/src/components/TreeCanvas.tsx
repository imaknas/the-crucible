"use client";

import React, { useCallback, useEffect, useRef } from "react";
import { useTheme } from "@mui/material";
import ReactFlow, {
  Background,
  Controls,
  MiniMap,
  useNodesState,
  useEdgesState,
  Node,
  Edge,
  MarkerType,
  useReactFlow,
  ReactFlowProvider,
  useStore,
  ControlButton,
  Position,
} from "reactflow";
import CustomTreeNode from "./CustomTreeNode";
import SynthesisTreeNode from "./SynthesisTreeNode";
import { Target, Wand2, GitBranch } from "lucide-react";
import type { DebateLane } from "@/lib/types";
import dagre from "dagre";
import "reactflow/dist/style.css";

export interface CustomNode extends Node {
  metadata?: {
    role?: string;
    active_peer?: string;
    model_name?: string;
    thesis_preview?: string;
    has_thoughts?: boolean;
    pending?: boolean;
    lane_index?: number;
    round_num?: number;
    model_color?: string;
  };
}

interface TreeCanvasProps {
  nodes: CustomNode[];
  edges: Edge[];
  onNodeClick?: (nodeId: string) => void;
  onNodeDragStop?: (nodeId: string, position: { x: number; y: number }) => void;
  onLayoutPositions?: (
    updates: { node_id: string; x: number; y: number }[],
  ) => void;
  activeNodeId?: string;
  onDeleteNode?: (nodeId: string) => void;
  // Debate mode
  debateMode?: boolean;
  lanes?: DebateLane[];
  /** Convergence score per round, keyed by round number as a string. */
  roundScores?: Record<string, number>;
  maxRound?: number;
}

const selector = (s: any) => ({
  width: s.width,
  height: s.height,
  transform: s.transform,
  // fitView reads React Flow's own store, not our props, so it is a silent
  // no-op until the store holds this node set AND has measured it.
  storeNodeCount: s.nodeInternals.size,
  storeNodesMeasured: [...s.nodeInternals.values()].every(
    (n: any) => n.width != null && n.height != null,
  ),
});

const nodeTypes = {
  custom: CustomTreeNode,
  synthesis: SynthesisTreeNode,
};
const edgeTypes = {};

const nodeWidth = 240;
const nodeHeight = 120;

const getLayoutedElements = (
  nodes: Node[],
  edges: Edge[],
  direction = "TB",
) => {
  const isHorizontal = direction === "LR";
  // A fresh graph per call. A module-level singleton kept every node from
  // every thread ever laid out, and dagre spreads disconnected components
  // side by side — so the layout drifted further off with each thread visited.
  const dagreGraph = new dagre.graphlib.Graph();
  dagreGraph.setDefaultEdgeLabel(() => ({}));
  dagreGraph.setGraph({ rankdir: direction });

  nodes.forEach((node) => {
    dagreGraph.setNode(node.id, { width: nodeWidth, height: nodeHeight });
  });

  edges.forEach((edge) => {
    dagreGraph.setEdge(edge.source, edge.target);
  });

  dagre.layout(dagreGraph);

  return {
    nodes: nodes.map((node) => {
      const nodeWithPosition = dagreGraph.node(node.id);
      return {
        ...node,
        targetPosition: isHorizontal ? Position.Left : Position.Top,
        sourcePosition: isHorizontal ? Position.Right : Position.Bottom,
        // We are shifting the dagre node position (which is center-based) to top-left
        position: {
          x: nodeWithPosition.x - nodeWidth / 2,
          y: nodeWithPosition.y - nodeHeight / 2,
        },
      };
    }),
    edges,
  };
};

function withAlpha(hex: string, alpha: string) {
  return `${hex}${alpha}`;
}

function getNodeColors(
  role: string,
  model: string | undefined,
  isDark: boolean,
  modelColor?: string,
) {
  // The backend already resolves each model to its family colour; prefer it so
  // lane headers, minimap dots and node bodies cannot drift apart.
  if (modelColor && role !== "user") {
    return {
      bg: withAlpha(modelColor, isDark ? "14" : "0f"),
      border: withAlpha(modelColor, isDark ? "40" : "33"),
      text: modelColor,
    };
  }

  // User or system
  if (role === "user") {
    return isDark
      ? {
          bg: "rgba(59, 130, 246, 0.1)",
          border: "rgba(59, 130, 246, 0.25)",
          text: "#93c5fd",
        }
      : {
          bg: "rgba(59, 130, 246, 0.06)",
          border: "rgba(59, 130, 246, 0.2)",
          text: "#2563eb",
        };
  }

  const m = (model || "").toLowerCase();
  if (m.includes("gpt")) {
    return isDark
      ? {
          bg: "rgba(16, 185, 129, 0.08)",
          border: "rgba(16, 185, 129, 0.25)",
          text: "#6ee7b7",
        }
      : {
          bg: "rgba(16, 185, 129, 0.06)",
          border: "rgba(16, 185, 129, 0.2)",
          text: "#059669",
        };
  }
  if (m.includes("claude")) {
    return isDark
      ? {
          bg: "rgba(245, 158, 11, 0.08)",
          border: "rgba(245, 158, 11, 0.25)",
          text: "#fbbf24",
        }
      : {
          bg: "rgba(245, 158, 11, 0.06)",
          border: "rgba(245, 158, 11, 0.2)",
          text: "#d97706",
        };
  }
  if (m.includes("gemini")) {
    return isDark
      ? {
          bg: "rgba(139, 92, 246, 0.08)",
          border: "rgba(139, 92, 246, 0.25)",
          text: "#a78bfa",
        }
      : {
          bg: "rgba(139, 92, 246, 0.06)",
          border: "rgba(139, 92, 246, 0.2)",
          text: "#7c3aed",
        };
  }
  if (role === "ai") {
    return isDark
      ? {
          bg: "rgba(168, 85, 247, 0.1)",
          border: "rgba(168, 85, 247, 0.25)",
          text: "#c084fc",
        }
      : {
          bg: "rgba(168, 85, 247, 0.06)",
          border: "rgba(168, 85, 247, 0.2)",
          text: "#9333ea",
        };
  }
  return isDark
    ? {
        bg: "rgba(30, 41, 59, 0.5)",
        border: "rgba(255, 255, 255, 0.06)",
        text: "#e2e8f0",
      }
    : {
        bg: "rgba(255, 255, 255, 0.9)",
        border: "rgba(0, 0, 0, 0.06)",
        text: "#1e293b",
      };
}

// Mirrored from backend/app/services/tree.py.
const LANE_WIDTH = 300;
const ROUND_HEIGHT = 160;
// Matches the width CustomTreeNode actually renders at.
const NODE_RENDER_WIDTH = 220;

function DebateLaneHeaders({
  lanes,
  transform,
}: {
  lanes: DebateLane[];
  transform: number[];
}) {
  const isDark = useTheme().palette.mode === "dark";
  const [panX, , zoom] = transform;
  return (
    <div
      style={{
        position: "absolute",
        top: 8,
        left: 0,
        width: "100%",
        // Every pill is absolutely positioned, so the row would collapse to
        // zero height and `overflow: hidden` would clip them all away.
        height: 24,
        pointerEvents: "none",
        zIndex: 10,
        overflowX: "hidden",
      }}
    >
      {lanes.map((lane) => {
        const centerX =
          lane.lane_index * LANE_WIDTH * zoom + panX + NODE_RENDER_WIDTH / 2 * zoom;
        return (
          <div
            key={lane.model_id}
            style={{
              position: "absolute",
              left: centerX,
              transform: "translateX(-50%)",
              padding: "3px 10px",
              borderRadius: 20,
              background: isDark ? "rgba(15,23,42,0.8)" : "rgba(255,255,255,0.85)",
              border: `1px solid ${lane.color}44`,
              backdropFilter: "blur(8px)",
              display: "flex",
              alignItems: "center",
              gap: 6,
            }}
          >
            <div
              style={{
                width: 8,
                height: 8,
                borderRadius: "50%",
                background: lane.color,
                flexShrink: 0,
              }}
            />
            <span
              title={lane.model_id}
              style={{
                fontSize: 11,
                fontWeight: 700,
                color: lane.color,
                letterSpacing: "0.06em",
                whiteSpace: "nowrap",
              }}
            >
              {lane.label || lane.model_id}
            </span>
          </div>
        );
      })}
    </div>
  );
}

/**
 * Horizontal band per debate round, with its convergence score when one was
 * recorded. Without these the rounds are only distinguishable by y-position.
 *
 * Drawn in canvas space (it consumes the same transform React Flow applies to
 * the viewport) so the bands pan and zoom with the nodes they label.
 */
function DebateRoundBands({
  maxRound,
  roundScores,
  transform,
  laneCount,
}: {
  maxRound: number;
  roundScores: Record<string, number>;
  transform: number[];
  laneCount: number;
}) {
  const isDark = useTheme().palette.mode === "dark";
  const [, panY, zoom] = transform;
  const rows = [];

  for (let r = 0; r <= maxRound; r++) {
    const y = r * ROUND_HEIGHT * zoom + panY;
    const score = roundScores[String(r)];
    rows.push(
      <div
        key={r}
        style={{
          position: "absolute",
          top: y - 14 * zoom,
          left: 0,
          right: 0,
          height: ROUND_HEIGHT * zoom,
          borderTop: `1px dashed ${
            isDark ? "rgba(148,163,184,0.16)" : "rgba(100,116,139,0.16)"
          }`,
          display: "flex",
          alignItems: "flex-start",
          paddingLeft: 10,
          paddingTop: 3,
          gap: 8,
        }}
      >
        <span
          style={{
            fontSize: 10,
            fontWeight: 800,
            letterSpacing: "0.14em",
            textTransform: "uppercase",
            color: isDark ? "#64748b" : "#94a3b8",
            whiteSpace: "nowrap",
          }}
        >
          Round {r + 1}
        </span>
        {score != null && (
          <span
            title="Cosine similarity against the previous round"
            style={{
              fontSize: 10,
              fontWeight: 700,
              padding: "1px 6px",
              borderRadius: 10,
              whiteSpace: "nowrap",
              color: score >= 0.9 ? "#10b981" : score >= 0.75 ? "#f59e0b" : "#64748b",
              background:
                score >= 0.9
                  ? "rgba(16,185,129,0.12)"
                  : score >= 0.75
                    ? "rgba(245,158,11,0.12)"
                    : isDark
                      ? "rgba(148,163,184,0.1)"
                      : "rgba(100,116,139,0.08)",
            }}
          >
            {(score * 100).toFixed(0)}% converged
          </span>
        )}
      </div>,
    );
  }

  return (
    <div
      style={{
        position: "absolute",
        inset: 0,
        pointerEvents: "none",
        overflow: "hidden",
        zIndex: 1,
      }}
      aria-hidden
      data-lane-count={laneCount}
    >
      {rows}
    </div>
  );
}

function TreeViewInner({
  nodes: externalNodes,
  edges: externalEdges,
  onNodeClick,
  onNodeDragStop,
  onLayoutPositions,
  activeNodeId,
  onDeleteNode,
  debateMode = false,
  lanes = [],
  roundScores = {},
  maxRound = 0,
}: TreeCanvasProps) {
  const isDark = useTheme().palette.mode === "dark";
  const [nodes, setNodes, onNodesChange] = useNodesState<CustomNode>([]);
  const [edges, setEdges, onEdgesChange] = useEdgesState<Edge>([]);

  const { fitView, setViewport } = useReactFlow();
  const { width, height, transform, storeNodeCount, storeNodesMeasured } =
    useStore(selector);

  const prevIdsJson = useRef("");
  const prevActiveNodeId = useRef<string | undefined>(undefined);

  const isDimensionValid = width > 50 && height > 50;
  const isTransformValid =
    transform && transform.every((v: number) => isFinite(v));
  const isViewportValid = isDimensionValid && isTransformValid;

  useEffect(() => {
    if (transform && transform.some((v: number) => !isFinite(v))) {
      setViewport({ x: 0, y: 0, zoom: 0.5 });
    }
  }, [transform, setViewport]);

  const processedNodes = React.useMemo(() => {
    return externalNodes.map((n) => {
      const role = n.metadata?.role || "system";
      const model = n.metadata?.active_peer || "";
      const isActive = n.id === activeNodeId;
      const isPending = n.metadata?.pending;

      // Synthesis nodes use their own component — pass through with type override
      if (role === "synthesis" || n.type === "synthesis") {
        return {
          ...n,
          type: "synthesis",
          position: {
            x: isFinite(n.position.x) ? n.position.x : 0,
            y: isFinite(n.position.y) ? n.position.y : 0,
          },
          data: { ...n.data, metadata: n.metadata },
          selected: isActive,
        };
      }

      const colors = getNodeColors(role, model, isDark, n.metadata?.model_color);
      return {
        ...n,
        type: "custom",
        position: {
          x: isFinite(n.position.x) ? n.position.x : 0,
          y: isFinite(n.position.y) ? n.position.y : 0,
        },
        data: {
          ...n.data,
          onDelete: onDeleteNode,
          metadata: n.metadata,
          styling: {
            background: isActive ? (isDark ? "#2563eb" : "#3b82f6") : colors.bg,
            border: `1px solid ${isActive ? (isDark ? "#60a5fa" : "#2563eb") : colors.border}`,
            color: isActive ? "#fff" : colors.text,
            width: 220,
            borderRadius: "14px",
            padding: "14px",
            fontSize: "12px",
            lineHeight: "1.4",
            boxShadow: isActive
              ? `0 0 20px ${isDark ? "rgba(37, 99, 235, 0.3)" : "rgba(59, 130, 246, 0.2)"}`
              : "0 4px 20px -8px rgba(0, 0, 0, 0.15)",
            animation: isPending ? "pulse 1.5s ease-in-out infinite" : undefined,
            opacity: isPending ? 0.7 : 1,
          },
        },
        selected: isActive,
      };
    });
  }, [externalNodes, activeNodeId, isDark, onDeleteNode]);

  const processedEdges = React.useMemo(() => {
    return externalEdges.map((e) => {
      if (e.type === "synthesis_edge") {
        return {
          ...e,
          animated: true,
          style: { stroke: "#8b5cf6", strokeWidth: 2, strokeDasharray: "5,3" },
          markerEnd: {
            type: MarkerType.ArrowClosed,
            color: "#8b5cf6",
            width: 14,
            height: 14,
          },
        };
      }
      return {
        ...e,
        animated: true,
        style: {
          stroke: isDark ? "rgba(255,255,255,0.08)" : "rgba(0,0,0,0.08)",
          strokeWidth: 1.5,
        },
        markerEnd: {
          type: MarkerType.ArrowClosed,
          color: isDark ? "rgba(255,255,255,0.12)" : "rgba(0,0,0,0.12)",
          width: 14,
          height: 14,
        },
      };
    });
  }, [externalEdges, isDark]);

  const onLayout = useCallback(() => {
    const { nodes: layoutedNodes, edges: layoutedEdges } = getLayoutedElements(
      nodes,
      edges,
    );

    setNodes([...layoutedNodes]);
    setEdges([...layoutedEdges]);

    // Persist new positions to backend in one request rather than one per node
    if (onLayoutPositions) {
      onLayoutPositions(
        layoutedNodes.map((node) => ({
          node_id: node.id,
          x: node.position.x,
          y: node.position.y,
        })),
      );
    } else if (onNodeDragStop) {
      layoutedNodes.forEach((node) => {
        onNodeDragStop(node.id, node.position);
      });
    }

    // After layout, give React Flow a moment to update and then fit view
    setTimeout(() => {
      fitView({ duration: 600, padding: 0.3 });
    }, 50);
  }, [nodes, edges, setNodes, setEdges, fitView, onNodeDragStop, onLayoutPositions]);

  // Sync internal state with external props.
  //
  // The set of node IDs decides whether this is a structural change (thread
  // switch, new checkpoint) or an in-place restyle. Restyles must still be
  // applied — theme swaps and label updates produce new `processedNodes` with
  // an identical ID set, and skipping them left the tree painted in the old
  // theme until something structural happened. On a restyle the node's live
  // `position` is preserved so an in-flight drag is never reverted.
  useEffect(() => {
    const structuralHash = externalNodes.map((n) => n.id).join(",");

    if (structuralHash !== prevIdsJson.current) {
      setNodes(processedNodes);
      setEdges(processedEdges);
      prevIdsJson.current = structuralHash;
      prevActiveNodeId.current = activeNodeId;
    } else {
      prevActiveNodeId.current = activeNodeId;
      setNodes((current) => {
        const live = new Map(current.map((n) => [n.id, n.position]));
        return processedNodes.map((n) => ({
          ...n,
          position: live.get(n.id) ?? n.position,
        }));
      });
      setEdges(processedEdges);
    }
  }, [
    processedNodes,
    processedEdges,
    externalNodes,
    setNodes,
    setEdges,
    activeNodeId,
  ]);

  // Fit the viewport once per structural change.
  //
  // Two things have to be true before fitView can do anything: the pane must be
  // measured, and React Flow's internal store must already hold the measured
  // nodes. Firing on a timer (as this did before) raced the store, so the tree
  // routinely loaded off-screen and only a manual Recenter brought it back.
  // Gating on the store's own count + measured state gives that signal, so this
  // fires once per thread load / new checkpoint and never fights the user.
  const fittedKey = useRef<string | null>(null);

  useEffect(() => {
    if (!isDimensionValid || externalNodes.length === 0) return;
    // Wait until React Flow has ingested and measured this node set, otherwise
    // fitView targets an empty/unmeasured store and does nothing.
    if (storeNodeCount !== externalNodes.length || !storeNodesMeasured) return;

    const key = externalNodes.map((n) => n.id).join(",");
    if (fittedKey.current === key) return;

    try {
      const target =
        activeNodeId && externalNodes.some((n) => n.id === activeNodeId)
          ? { nodes: [{ id: activeNodeId }], maxZoom: 0.85, minZoom: 0.2 }
          : {};
      fitView({ duration: 500, padding: 0.35, ...target });
      fittedKey.current = key;
    } catch (e) {
      console.error("[TREE] fitView failure:", e);
    }
  }, [
    externalNodes,
    isDimensionValid,
    storeNodeCount,
    storeNodesMeasured,
    fitView,
    activeNodeId,
  ]);

  const handleRecenter = useCallback(() => {
    if (activeNodeId) {
      fitView({
        duration: 400,
        padding: 0.7,
        nodes: [{ id: activeNodeId }],
        maxZoom: 1.2,
      });
    } else {
      fitView({ duration: 400, padding: 0.3 });
    }
  }, [fitView, activeNodeId]);

  const handleNodeClick = useCallback(
    (_: any, node: Node) => onNodeClick?.(node.id),
    [onNodeClick],
  );
  const handleNodeDragStop = useCallback(
    (_: any, node: Node) => onNodeDragStop?.(node.id, node.position),
    [onNodeDragStop],
  );

  return (
    <div className="w-full h-full relative min-h-[400px] bg-transparent">
      {debateMode && lanes.length > 0 && isViewportValid && (
        <DebateRoundBands
          maxRound={maxRound}
          roundScores={roundScores}
          transform={transform}
          laneCount={lanes.length}
        />
      )}
      {debateMode && lanes.length > 0 && (
        <DebateLaneHeaders lanes={lanes} transform={transform} />
      )}
      {/* An empty canvas used to render as a blank void with no explanation. */}
      {externalNodes.length === 0 && (
        <div
          style={{
            position: "absolute",
            inset: 0,
            display: "flex",
            flexDirection: "column",
            alignItems: "center",
            justifyContent: "center",
            gap: 8,
            pointerEvents: "none",
            zIndex: 5,
            color: isDark ? "#64748b" : "#94a3b8",
          }}
        >
          <GitBranch size={28} strokeWidth={1.5} />
          <div style={{ fontSize: 13, fontWeight: 600 }}>
            {debateMode ? "No debate rounds recorded yet" : "No checkpoints yet"}
          </div>
          <div style={{ fontSize: 11, opacity: 0.8 }}>
            {debateMode
              ? "Rounds appear here as each model responds."
              : "Send a message to start building the tree."}
          </div>
        </div>
      )}
      <ReactFlow
        nodes={nodes}
        edges={edges}
        onNodesChange={onNodesChange}
        onEdgesChange={onEdgesChange}
        onNodeClick={handleNodeClick}
        onNodeDragStop={handleNodeDragStop}
        nodeTypes={nodeTypes}
        edgeTypes={edgeTypes}
        minZoom={0.01}
        maxZoom={4}
      >
        {isViewportValid && (
          <>
            <Background
              color={isDark ? "#1e293b" : "#e2e8f0"}
              gap={20}
              size={1}
            />
            <Controls
              style={{
                backgroundColor: isDark ? "#0f172a" : "#ffffff",
                border: `1px solid ${isDark ? "rgba(255,255,255,0.06)" : "rgba(0,0,0,0.06)"}`,
                borderRadius: "12px",
                overflow: "hidden",
              }}
            >
              {!debateMode && (
                <ControlButton
                  onClick={onLayout}
                  title="Tidy Layout (Auto-arrange)"
                >
                  <Wand2 size={14} />
                </ControlButton>
              )}
              <ControlButton
                onClick={handleRecenter}
                title="Recenter on Active Node"
              >
                <Target size={14} />
              </ControlButton>
            </Controls>
            <MiniMap
              style={{
                background: isDark ? "#0f172a" : "#ffffff",
                border: `1px solid ${isDark ? "rgba(255,255,255,0.06)" : "rgba(0,0,0,0.06)"}`,
                borderRadius: "12px",
              }}
              maskColor={isDark ? "rgba(0,0,0,0.5)" : "rgba(255,255,255,0.5)"}
              nodeColor={(node) => {
                const meta = (node as CustomNode).metadata;
                if (meta?.model_color) return meta.model_color;
                const model = meta?.active_peer || "";
                if (model.includes("gpt")) return "#10b981";
                if (model.includes("claude")) return "#f59e0b";
                if (model.includes("gemini")) return "#8b5cf6";
                return isDark ? "#475569" : "#94a3b8";
              }}
            />
          </>
        )}
      </ReactFlow>

      <style jsx global>{`
        @keyframes pulse {
          0%,
          100% {
            opacity: 0.45;
          }
          50% {
            opacity: 0.9;
          }
        }
        .react-flow__controls button {
          background-color: ${isDark ? "#1e293b" : "#ffffff"} !important;
          border-bottom: 1px solid
            ${isDark ? "rgba(255,255,255,0.04)" : "rgba(0,0,0,0.04)"} !important;
          fill: ${isDark ? "#94a3b8" : "#475569"} !important;
        }
        .react-flow__controls button:hover {
          background-color: ${isDark ? "#334155" : "#f1f5f9"} !important;
        }
      `}</style>
    </div>
  );
}

const TreeCanvasRaw = (props: TreeCanvasProps) => {
  return (
    <ReactFlowProvider>
      <TreeViewInner {...props} />
    </ReactFlowProvider>
  );
};

const TreeCanvas = React.memo(TreeCanvasRaw);

export default TreeCanvas;
