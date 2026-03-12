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
import { Target, Wand2 } from "lucide-react";
import dagre from "dagre";
import "reactflow/dist/style.css";

export interface CustomNode extends Node {
  metadata?: {
    role?: string;
    active_peer?: string;
    thesis_preview?: string;
    has_thoughts?: boolean;
  };
}

interface TreeCanvasProps {
  nodes: CustomNode[];
  edges: Edge[];
  onNodeClick?: (nodeId: string) => void;
  onNodeDragStop?: (nodeId: string, position: { x: number; y: number }) => void;
  activeNodeId?: string;
  onDeleteNode?: (nodeId: string) => void;
}

const selector = (s: any) => ({
  width: s.width,
  height: s.height,
  transform: s.transform,
});

const nodeTypes = {
  custom: CustomTreeNode,
};
const edgeTypes = {};

const dagreGraph = new dagre.graphlib.Graph();
dagreGraph.setDefaultEdgeLabel(() => ({}));

const nodeWidth = 240;
const nodeHeight = 120;

const getLayoutedElements = (
  nodes: Node[],
  edges: Edge[],
  direction = "TB",
) => {
  const isHorizontal = direction === "LR";
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

function getNodeColors(
  role: string,
  model: string | undefined,
  isDark: boolean,
) {
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

function TreeViewInner({
  nodes: externalNodes,
  edges: externalEdges,
  onNodeClick,
  onNodeDragStop,
  activeNodeId,
  onDeleteNode,
}: TreeCanvasProps) {
  const isDark = useTheme().palette.mode === "dark";
  const [nodes, setNodes, onNodesChange] = useNodesState<CustomNode>([]);
  const [edges, setEdges, onEdgesChange] = useEdgesState<Edge>([]);

  const { fitView, setViewport } = useReactFlow();
  const { width, height, transform } = useStore(selector);

  const prevIdsJson = useRef("");
  const prevActiveNodeId = useRef<string | undefined>(undefined);
  const autoLayoutDone = useRef(false);
  const mountTime = useRef<number | null>(null);
  if (mountTime.current === null) {
    // eslint-disable-next-line react-hooks/purity
    mountTime.current = Date.now();
  }

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
      const colors = getNodeColors(role, model, isDark);

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
          metadata: n.metadata, // Explicitly pass metadata
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
          },
        },
        selected: isActive,
      };
    });
  }, [externalNodes, activeNodeId, isDark, onDeleteNode]);

  const processedEdges = React.useMemo(() => {
    return externalEdges.map((e) => ({
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
    }));
  }, [externalEdges, isDark]);

  const onLayout = useCallback(() => {
    const { nodes: layoutedNodes, edges: layoutedEdges } = getLayoutedElements(
      nodes,
      edges,
    );

    setNodes([...layoutedNodes]);
    setEdges([...layoutedEdges]);

    // Persist new positions to backend
    if (onNodeDragStop) {
      layoutedNodes.forEach((node) => {
        onNodeDragStop(node.id, node.position);
      });
    }

    // After layout, give React Flow a moment to update and then fit view
    setTimeout(() => {
      fitView({ duration: 600, padding: 0.3 });
    }, 50);
  }, [nodes, edges, setNodes, setEdges, fitView, onNodeDragStop]);

  // Sync internal state with external props
  useEffect(() => {
    // Fast structural check: compare count and a simple aggregate of IDs
    // This is much faster than JSON.stringify for large node sets
    const structuralHash = externalNodes.map((n) => n.id).join(",");

    // 1. Structural change (new nodes/edges or thread switch)
    if (structuralHash !== prevIdsJson.current) {
      setNodes(processedNodes);
      setEdges(processedEdges);
      prevIdsJson.current = structuralHash;
      prevActiveNodeId.current = activeNodeId;

      if (
        !autoLayoutDone.current &&
        externalNodes.length > 0 &&
        externalNodes.every((n) => n.position.x === 0 && n.position.y === 0)
      ) {
        autoLayoutDone.current = true;
        setTimeout(onLayout, 100);
      }
    }
    // 2. Selection change (activeNodeId) - Only if IDs haven't changed
    else if (activeNodeId !== prevActiveNodeId.current) {
      prevActiveNodeId.current = activeNodeId;
      // Use the already memoized processedNodes which contains the correct isActive styling
      setNodes(processedNodes);
    }
  }, [
    processedNodes,
    processedEdges,
    externalNodes,
    setNodes,
    setEdges,
    onLayout,
    activeNodeId,
  ]);

  // Reset auto-layout flag if the thread changes (new root IDs)
  useEffect(() => {
    // Heuristic: if the list of nodes is completely different or empty, reset
    if (externalNodes.length === 0) {
      autoLayoutDone.current = false;
    }
  }, [externalNodes.length]);
  const fitViewAttempts = useRef(0);
  const maxFitViewAttempts = 5;

  useEffect(() => {
    if (
      externalNodes.length > 0 &&
      isDimensionValid &&
      fitViewAttempts.current < maxFitViewAttempts
    ) {
      const timeSinceMount = Date.now() - (mountTime.current || 0);
      const delay = Math.max(
        0,
        300 + fitViewAttempts.current * 400 - timeSinceMount,
      );

      const timer = setTimeout(() => {
        // Use requestAnimationFrame to ensure fitView runs when the browser is ready for paint
        requestAnimationFrame(() => {
          try {
            // Verify if active node exists in the actual internal nodes state
            const nodeExists = activeNodeId
              ? nodes.some((n) => n.id === activeNodeId)
              : true;

            if (!nodeExists) {
              fitViewAttempts.current += 0.5;
              return;
            }

            let success = false;
            if (activeNodeId) {
              success = fitView({
                duration: 800,
                padding: 0.4,
                nodes: [{ id: activeNodeId }],
                minZoom: 0.2,
                maxZoom: 0.5,
              });
            } else {
              success = fitView({ duration: 800, padding: 0.3 });
            }

            if (success) {
              fitViewAttempts.current = maxFitViewAttempts;
            } else {
              fitViewAttempts.current += 1;
            }
          } catch (e) {
            console.error("[TREE] fitView failure:", e);
            fitViewAttempts.current += 1;
          }
        });
      }, delay);
      return () => clearTimeout(timer);
    }
  }, [externalNodes, nodes, isDimensionValid, fitView, activeNodeId]);

  // Reset attempts if the number of nodes changes significantly (e.g. new thread)
  useEffect(() => {
    fitViewAttempts.current = 0;
  }, [externalNodes.length]);

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
              <ControlButton
                onClick={onLayout}
                title="Tidy Layout (Auto-arrange)"
              >
                <Wand2 size={14} />
              </ControlButton>
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
                const model = (node as CustomNode).metadata?.active_peer || "";
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
