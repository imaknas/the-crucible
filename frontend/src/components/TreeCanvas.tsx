"use client";

import React, { useCallback, useEffect, useRef, useState } from "react";
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
  getNodesBounds,
} from "reactflow";
import CustomTreeNode, { LOD_THRESHOLD, type CustomNodeData } from "./CustomTreeNode";
import SelectionBar from "./tree/SelectionBar";
import { NodeMenu, RenameDialog, TreeNavBar, type NodeNoteActions } from "./tree/TreeNavigation";
import { bookmarks, descendants, neighbor, treeShape, visibleTree, type TreeKey } from "@/lib/treeView";
import type { SynthesisRequest } from "@/lib/synthesis";
import { shouldFitWholeTree } from "@/lib/treeFit";
import SynthesisTreeNode from "./SynthesisTreeNode";
import { DebateLaneHeaders, DebateRoundBands } from "./tree/DebateOverlays";
import { Target, Wand2, GitBranch, Loader2 } from "lucide-react";
import type { DebateLane } from "@/lib/types";
import { FAMILY_COLORS, NEUTRAL_COLOR, modelFamilyColor, modelPalette } from "@/lib/colors";
import dagre from "dagre";
import "reactflow/dist/style.css";
import { RADIUS } from "@/theme";

export interface CustomNode extends Node {
  metadata?: {
    role?: string;
    active_peer?: string;
    model_name?: string;
    has_thoughts?: boolean;
    pending?: boolean;
    lane_index?: number;
    round_num?: number;
    model_color?: string;
    name?: string | null;
    bookmarked?: boolean;
    subtree_summary?: { text: string; model: string | null; nodes: number | null } | null;
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
  /** Chat trees: "Branch from here" on node hover. */
  onBranchNode?: (nodeId: string) => void;
  /** Debate trees: open a reply in full. Not offered on a pending node. */
  onReadNode?: (nodeId: string) => void;
  // Debate mode
  debateMode?: boolean;
  lanes?: DebateLane[];
  /** Stability per round (each model vs its own previous answer), keyed by round number as a string. */
  roundScores?: Record<string, number>;
  maxRound?: number;
  /** Models are answering: the tree gets their nodes once they finish, so say so meanwhile. */
  answering?: boolean;
  /** The tree is being fetched: an empty canvas is "not loaded yet", not "no messages". */
  loading?: boolean;
  /** Chat trees: combine answers picked anywhere on the tree (Shift/Cmd-click or a node's Pick). */
  onSynthesizeSelection?: (ids: string[], request: SynthesisRequest) => void;
  /** Chat trees: folded subtrees and the one shown alone (useTreeView). */
  collapsed?: ReadonlySet<string>;
  hoisted?: string | null;
  onSetCollapsed?: (id: string, folded: boolean) => void;
  onHoist?: (id: string | null) => void;
  /** Open whatever hides a node, before jumping to it (a bookmark). */
  onReveal?: (id: string) => void;
  /** Chat trees: names, bookmarks and subtree summaries (useNodeNotes). */
  notes?: NodeNoteActions;
}

const NO_COLLAPSED: ReadonlySet<string> = new Set();
const TREE_KEYS = new Set(["ArrowUp", "ArrowDown", "ArrowLeft", "ArrowRight", "Home"]);

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

// Room around a fitted tree: node badges overhang the top edge by ~10px.
const FIT_PADDING = 0.2;

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

function getNodeColors(role: string, model: string | undefined, isDark: boolean, modelColor?: string) {
  // User messages are the app's blue; every reply uses its family colour (the
  // backend's model_color, guessed from the id only before it arrives), so
  // lane headers, minimap dots and node bodies share one palette.
  if (role === "user") {
    return isDark
      ? { bg: "rgba(59, 130, 246, 0.1)", border: "rgba(59, 130, 246, 0.25)", text: "#93c5fd" }
      : { bg: "rgba(59, 130, 246, 0.06)", border: "rgba(59, 130, 246, 0.2)", text: "#1d4ed8" };
  }
  const color = modelColor || (model ? modelFamilyColor(model) : role === "ai" ? FAMILY_COLORS.synthesis : null);
  if (color) {
    const p = modelPalette(color, isDark);
    return { bg: p.bg, border: p.border, text: p.text };
  }
  return isDark
    ? { bg: "rgba(30, 41, 59, 0.5)", border: "rgba(255, 255, 255, 0.06)", text: "#e2e8f0" }
    : { bg: "rgba(255, 255, 255, 0.9)", border: "rgba(0, 0, 0, 0.06)", text: "#1e293b" };
}

/** A node's dot on the minimap: the same colour as its body. */
function miniMapColor(node: Node, isDark: boolean): string {
  const meta = (node as CustomNode).metadata;
  if (node.type === "synthesis") return FAMILY_COLORS.synthesis;
  if (meta?.model_color) return meta.model_color;
  if (meta?.active_peer) return modelFamilyColor(meta.active_peer);
  return isDark ? "#475569" : NEUTRAL_COLOR;
}

function TreeViewInner({
  nodes: allNodes,
  edges: allEdges,
  onNodeClick,
  onNodeDragStop,
  onLayoutPositions,
  activeNodeId,
  onDeleteNode,
  onBranchNode,
  onReadNode,
  debateMode = false,
  lanes = [],
  roundScores = {},
  maxRound = 0,
  answering = false,
  loading = false,
  onSynthesizeSelection,
  collapsed = NO_COLLAPSED,
  hoisted = null,
  onSetCollapsed,
  onHoist,
  onReveal,
  notes,
}: TreeCanvasProps) {
  const isDark = useTheme().palette.mode === "dark";
  // What is drawn: a hoisted subtree alone, collapsed subtrees folded into
  // their top node (lib/treeView). Positions stay where they are.
  const view = React.useMemo(
    () => visibleTree(allNodes, allEdges, collapsed, hoisted),
    [allNodes, allEdges, collapsed, hoisted],
  );
  const externalNodes = view.nodes;
  const externalEdges = view.edges;
  const shape = React.useMemo(() => treeShape(allEdges), [allEdges]);
  // The keyboard's place in the tree: arrows move it, Enter makes it the
  // branch point. Moving it alone never changes what the next message
  // continues or who answers (only a click or Enter does).
  const [focusedId, setFocusedId] = useState<string | null>(null);
  const [menu, setMenu] = useState<{ id: string; anchor: HTMLElement } | null>(null);
  const [renaming, setRenaming] = useState<{ id: string; name: string } | null>(null);
  const openMenu = useCallback((id: string, anchor: HTMLElement) => setMenu({ id, anchor }), []);
  const expand = useCallback((id: string) => onSetCollapsed?.(id, false), [onSetCollapsed]);
  // Answers picked to combine. Separate from the active node: picking never
  // moves the branch point or changes who answers next.
  const [picked, setPicked] = useState<string[]>([]);
  const pickable = !debateMode && !!onSynthesizeSelection;
  const togglePick = useCallback(
    (id: string) => setPicked((p) => (p.includes(id) ? p.filter((x) => x !== id) : [...p, id])),
    [],
  );
  const [nodes, setNodes, onNodesChange] = useNodesState<CustomNode>([]);
  const [edges, setEdges, onEdgesChange] = useEdgesState<Edge>([]);

  const { fitView, setViewport, getNodes, setCenter } = useReactFlow();
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
          data: {
            ...n.data,
            metadata: n.metadata,
            onDelete: onDeleteNode,
            onBranch: onBranchNode,
            onRead: isPending ? undefined : onReadNode,
          },
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
          // Only message nodes can be replied from; the empty root can't.
          onBranch: role === "user" || role === "ai" ? onBranchNode : undefined,
          onRead: role === "ai" && !isPending ? onReadNode : undefined,
          onPick: pickable && role === "ai" && !isPending ? togglePick : undefined,
          picked: picked.includes(n.id),
          onMenu: notes && !debateMode && (role === "user" || role === "ai") ? openMenu : undefined,
          hiddenCount: view.hidden.get(n.id),
          onExpand: expand,
          focused: n.id === focusedId,
          summarizing: !!notes?.summarizing.includes(n.id),
          metadata: n.metadata,
          styling: {
            background: isActive ? (isDark ? "#2563eb" : "#3b82f6") : colors.bg,
            border: `1px solid ${isActive ? (isDark ? "#60a5fa" : "#2563eb") : colors.border}`,
            color: isActive ? "#fff" : colors.text,
            width: 220,
            borderRadius: `${RADIUS.lg}px`,
            padding: "14px",
            fontSize: "12px",
            lineHeight: "1.4",
            boxShadow: picked.includes(n.id)
              ? "0 0 0 3px #7c3aed"
              : isActive
                ? `0 0 20px ${isDark ? "rgba(37, 99, 235, 0.3)" : "rgba(59, 130, 246, 0.2)"}`
                : "0 4px 20px -8px rgba(0, 0, 0, 0.15)",
            animation: isPending ? "pulse 1.5s ease-in-out infinite" : undefined,
            opacity: isPending ? 0.7 : 1,
          },
        },
        selected: isActive,
      };
    });
  }, [externalNodes, activeNodeId, isDark, onDeleteNode, onBranchNode, onReadNode, pickable, picked, togglePick,
      notes, debateMode, openMenu, view.hidden, expand, focusedId]);

  const processedEdges = React.useMemo(() => {
    return externalEdges.map((e) => {
      if (e.type === "synthesis_edge") {
        // The backend's kind of edge, drawn as a styled default edge: React
        // Flow has no "synthesis_edge" type and warned on every render.
        return {
          ...e,
          type: "default",
          data: { ...(e.data ?? {}), kind: "synthesis" },
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
      // The whole tree when it fits readably (its top must not end up off the
      // canvas, under the header); otherwise the active node.
      const hasActive = !!activeNodeId && externalNodes.some((n) => n.id === activeNodeId);
      const whole =
        !hasActive ||
        shouldFitWholeTree(getNodesBounds(getNodes()), { width, height }, FIT_PADDING, LOD_THRESHOLD);
      fitView(
        whole
          ? { duration: 500, padding: FIT_PADDING, maxZoom: 0.85 }
          : { duration: 500, padding: 0.35, nodes: [{ id: activeNodeId! }], maxZoom: 0.85, minZoom: 0.2 },
      );
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
    getNodes,
    width,
    height,
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

  // Picks of nodes that left the tree (a deleted branch) drop out.
  const livePicks = picked.filter((id) => externalNodes.some((n) => n.id === id));

  const handleNodeClick = useCallback(
    (event: React.MouseEvent, node: Node) => {
      // A modified click picks an answer to combine; only a plain click
      // chooses where the next message goes.
      if (pickable && (event.shiftKey || event.metaKey || event.ctrlKey)) {
        if ((node.data as CustomNodeData)?.onPick) togglePick(node.id);
        return;
      }
      onNodeClick?.(node.id);
    },
    [onNodeClick, pickable, togglePick],
  );
  // Arrow keys walk the tree before React Flow sees them: with a node
  // focused it would otherwise nudge that node's position.
  const handleKeyDownCapture = useCallback(
    (e: React.KeyboardEvent) => {
      const target = e.target as HTMLElement;
      if (target.closest("input, textarea, button, [role=menu], [role=dialog]")) return;
      if (!externalNodes.length) return;
      const visible = (id: string | null | undefined) => !!id && externalNodes.some((n) => n.id === id);
      const current = visible(focusedId) ? focusedId! : visible(activeNodeId) ? activeNodeId! : externalNodes[0].id;
      if (e.key === "Escape" && focusedId) {
        setFocusedId(null);
        return;
      }
      if (e.key === "Enter" && visible(focusedId)) {
        e.preventDefault();
        e.stopPropagation();
        onNodeClick?.(focusedId!);
        return;
      }
      if (!TREE_KEYS.has(e.key)) return;
      e.preventDefault();
      e.stopPropagation();
      const next = visible(focusedId) ? neighbor(externalNodes, externalEdges, current, e.key as TreeKey) : current;
      setFocusedId(next);
      const node = getNodes().find((n) => n.id === next);
      if (node) {
        setCenter(node.position.x + (node.width ?? 220) / 2, node.position.y + (node.height ?? 80) / 2, {
          zoom: transform[2],
          duration: 200,
        });
      }
    },
    [externalNodes, externalEdges, focusedId, activeNodeId, onNodeClick, getNodes, setCenter, transform],
  );

  const jumpTo = useCallback(
    (id: string) => {
      onReveal?.(id);
      setFocusedId(id);
      onNodeClick?.(id);
    },
    [onReveal, onNodeClick],
  );
  const marks = React.useMemo(() => (notes && !debateMode ? bookmarks(allNodes) : []), [notes, debateMode, allNodes]);
  const hoistedNode = hoisted ? allNodes.find((n) => n.id === hoisted) : undefined;
  const menuNode = menu ? allNodes.find((n) => n.id === menu.id) : undefined;

  const handleNodeDragStop = useCallback(
    (_: any, node: Node) => onNodeDragStop?.(node.id, node.position),
    [onNodeDragStop],
  );

  return (
    <div
      className="w-full h-full relative min-h-[400px] bg-transparent"
      tabIndex={0}
      aria-label="Conversation tree. Arrow keys move between messages; Enter continues from the one marked."
      onKeyDownCapture={handleKeyDownCapture}
      data-testid="tree-canvas"
    >
      {notes && !debateMode && (
        <TreeNavBar
          hoistedLabel={hoistedNode ? (hoistedNode.metadata?.name || hoistedNode.data.label || "Message") : null}
          onUnhoist={() => onHoist?.(null)}
          marks={marks}
          onJump={jumpTo}
        />
      )}
      {notes && menu && menuNode && (
        <NodeMenu
          anchor={menu.anchor}
          onClose={() => setMenu(null)}
          name={menuNode.metadata?.name ?? null}
          bookmarked={!!menuNode.metadata?.bookmarked}
          hasSummary={!!menuNode.metadata?.subtree_summary}
          below={descendants(shape, menuNode.id).length}
          collapsed={collapsed.has(menuNode.id)}
          hoisted={hoisted === menuNode.id}
          summarizing={notes.summarizing.includes(menuNode.id)}
          onRename={() => setRenaming({ id: menuNode.id, name: menuNode.metadata?.name ?? "" })}
          onBookmark={(b) => notes.setBookmark(menuNode.id, b)}
          onCollapse={(c) => onSetCollapsed?.(menuNode.id, c)}
          onHoist={(h) => onHoist?.(h ? menuNode.id : null)}
          onSummarize={() => notes.summarize(menuNode.id)}
          onClearSummary={() => notes.clearSummary(menuNode.id)}
        />
      )}
      {notes && renaming && (
        <RenameDialog
          initial={renaming.name}
          onSave={(name) => notes.rename(renaming.id, name)}
          onClose={() => setRenaming(null)}
        />
      )}
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
      {/* An empty canvas used to render as a blank void with no explanation,
          and while the tree was still loading it said "No messages yet". */}
      {externalNodes.length === 0 && loading && (
        <div
          role="status"
          style={{
            position: "absolute",
            inset: 0,
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            gap: 8,
            pointerEvents: "none",
            zIndex: 5,
            fontSize: 13,
            fontWeight: 600,
            color: isDark ? "#94a3b8" : "#64748b",
          }}
        >
          <Loader2 size={18} strokeWidth={2} className="animate-spin" aria-hidden />
          {debateMode ? "Loading the debate…" : "Loading the conversation…"}
        </div>
      )}
      {externalNodes.length === 0 && !loading && (
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
            {debateMode ? "No debate rounds recorded yet" : "No messages yet"}
          </div>
          <div style={{ fontSize: 11, opacity: 0.8 }}>
            {debateMode
              ? "Rounds appear here as each model responds."
              : "Switch to Arena (top right) and send a message to start the tree."}
          </div>
        </div>
      )}
      {answering && !debateMode && (
        <div
          role="status"
          style={{
            position: "absolute",
            top: 12,
            left: "50%",
            transform: "translateX(-50%)",
            zIndex: 6,
            display: "flex",
            alignItems: "center",
            gap: 8,
            padding: "6px 12px",
            borderRadius: 999,
            fontSize: 12,
            fontWeight: 600,
            background: isDark ? "#1e293b" : "#ffffff",
            color: isDark ? "#cbd5e1" : "#334155",
            border: `1px solid ${isDark ? "rgba(255,255,255,0.1)" : "rgba(0,0,0,0.1)"}`,
            boxShadow: "0 4px 16px rgba(0,0,0,0.12)",
          }}
        >
          Models answering… their replies join the tree when they finish.
        </div>
      )}
      {pickable && livePicks.length > 0 && (
        <SelectionBar
          count={livePicks.length}
          onClear={() => setPicked([])}
          onRun={(request) => {
            onSynthesizeSelection?.(livePicks, request);
            setPicked([]);
          }}
        />
      )}
      <ReactFlow
        nodes={nodes}
        edges={edges}
        onNodesChange={onNodesChange}
        onEdgesChange={onEdgesChange}
        onNodeClick={handleNodeClick}
        onNodeDragStop={handleNodeDragStop}
        // Modified clicks are ours (picking answers), not React Flow's own multi-select.
        multiSelectionKeyCode={null}
        selectionKeyCode={null}
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
                borderRadius: `${RADIUS.md}px`,
                overflow: "hidden",
              }}
            >
              {!debateMode && (
                <ControlButton
                  onClick={onLayout}
                  title="Tidy layout (auto-arrange)"
                  aria-label="Tidy layout"
                >
                  <Wand2 size={14} />
                </ControlButton>
              )}
              <ControlButton
                onClick={handleRecenter}
                title="Recenter on the active node"
                aria-label="Recenter on the active node"
              >
                <Target size={14} />
              </ControlButton>
            </Controls>
            {/* On a phone-sized canvas the minimap would cover a third of it. */}
            {width >= 600 && (
              <MiniMap
                style={{
                  background: isDark ? "#0f172a" : "#ffffff",
                  border: `1px solid ${isDark ? "rgba(255,255,255,0.06)" : "rgba(0,0,0,0.06)"}`,
                  borderRadius: `${RADIUS.md}px`,
                }}
                maskColor={isDark ? "rgba(0,0,0,0.5)" : "rgba(255,255,255,0.5)"}
                nodeColor={(node) => miniMapColor(node, isDark)}
              />
            )}
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
