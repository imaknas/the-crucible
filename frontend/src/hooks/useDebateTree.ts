import { useState, useCallback, useRef, useMemo, useEffect } from "react";
import { fetchDebateTree } from "@/lib/api";
import type {
  TreeNode,
  TreeEdge,
  DebateLane,
  DebateTreeResponse,
} from "@/lib/types";

// Kept in sync with backend/app/services/tree.py so an optimistic pending node
// lands exactly where its real node will appear once the round is persisted.
export const LANE_WIDTH = 300;
export const ROUND_HEIGHT = 160;

const TERMINAL_STATUSES = new Set(["completed", "failed", "interrupted"]);

const pendingId = (modelId: string, roundNum: number) =>
  `${modelId}::pending-r${roundNum}`;

export function useDebateTree() {
  const [serverNodes, setServerNodes] = useState<TreeNode[]>([]);
  const [edges, setEdges] = useState<TreeEdge[]>([]);
  const [lanes, setLanes] = useState<DebateLane[]>([]);
  const [sessionMeta, setSessionMeta] =
    useState<DebateTreeResponse["session_metadata"] | null>(null);
  const [loading, setLoading] = useState(false);
  const [pendingNodes, setPendingNodes] = useState<TreeNode[]>([]);

  const pollIntervalRef = useRef<ReturnType<typeof setInterval> | null>(null);
  // The interval closure cannot read `sessionMeta` — it would capture the value
  // from the render that created it (always null), which is why polling used to
  // run forever. A ref is always current.
  const statusRef = useRef<string | null>(null);
  // The session the canvas is showing. A response for any other session (a
  // poll or refetch still in flight from the one we just left) is dropped.
  const sessionRef = useRef<string | null>(null);

  const stopPolling = useCallback(() => {
    if (pollIntervalRef.current) {
      clearInterval(pollIntervalRef.current);
      pollIntervalRef.current = null;
    }
  }, []);

  const loadTree = useCallback(async (sessionId: string) => {
    try {
      setLoading(true);
      const data = await fetchDebateTree(sessionId);
      if (sessionRef.current !== sessionId) return;
      // Only the server-owned slice is replaced; pending nodes live separately
      // so a poll landing mid-round can no longer wipe the "Thinking…" markers.
      setServerNodes(data.nodes);
      setEdges(data.edges);
      setLanes(data.lanes);
      setSessionMeta(data.session_metadata);
      statusRef.current = data.session_metadata?.status ?? null;
    } catch (e) {
      console.error("[useDebateTree] fetch failed:", e);
    } finally {
      setLoading(false);
    }
  }, []);

  // An explicit fetch selects the session; polls only refresh the current one.
  const fetchTree = useCallback(
    async (sessionId: string) => {
      if (sessionRef.current !== sessionId) {
        sessionRef.current = sessionId;
        setPendingNodes([]);
      }
      await loadTree(sessionId);
    },
    [loadTree],
  );

  const clearTree = useCallback(() => {
    setServerNodes([]);
    setEdges([]);
    setLanes([]);
    setSessionMeta(null);
    setPendingNodes([]);
    statusRef.current = null;
    sessionRef.current = null;
    stopPolling();
  }, [stopPolling]);

  // Polls until the session reports a terminal status.
  const startPolling = useCallback(
    (sessionId: string, intervalMs = 3000) => {
      stopPolling();
      sessionRef.current = sessionId;
      pollIntervalRef.current = setInterval(async () => {
        if (sessionRef.current !== sessionId) {
          stopPolling();
          return;
        }
        await loadTree(sessionId);
        if (statusRef.current && TERMINAL_STATUSES.has(statusRef.current)) {
          stopPolling();
        }
      }, intervalMs);
    },
    [loadTree, stopPolling],
  );

  // Never leave an interval running past unmount.
  useEffect(() => stopPolling, [stopPolling]);

  // Optimistic: show a placeholder while a model streams its round.
  const addPendingNode = useCallback(
    (
      modelId: string,
      roundNum: number,
      laneIndex: number,
      color: string,
      modelName?: string,
    ) => {
      const pendingNode: TreeNode = {
        id: pendingId(modelId, roundNum),
        data: { label: "Thinking…" },
        position: { x: laneIndex * LANE_WIDTH, y: roundNum * ROUND_HEIGHT },
        metadata: {
          role: "ai",
          active_peer: modelId,
          model_name: modelName || modelId,
          lane_index: laneIndex,
          round_num: roundNum,
          model_color: color,
          pending: true,
        },
      };
      setPendingNodes((prev) => [
        ...prev.filter((n) => n.metadata?.active_peer !== modelId),
        pendingNode,
      ]);
    },
    [],
  );

  // Removes exactly one round's placeholder. Filtering by model alone raced
  // the next round: its fresh pending node, added while this fetch was in
  // flight, was deleted along with the old one.
  const resolvePendingNode = useCallback(
    async (modelId: string, sessionId: string, roundNum: number) => {
      await fetchTree(sessionId);
      const id = pendingId(modelId, roundNum);
      setPendingNodes((prev) => prev.filter((n) => n.id !== id));
    },
    [fetchTree],
  );

  const clearPendingNodes = useCallback(() => setPendingNodes([]), []);

  // A pending node is dropped as soon as the server has a real node for the
  // same model and round, so the two never render on top of each other.
  const nodes = useMemo(() => {
    if (pendingNodes.length === 0) return serverNodes;
    const taken = new Set(
      serverNodes.map(
        (n) => `${n.metadata?.active_peer}::${n.metadata?.round_num}`,
      ),
    );
    return [
      ...serverNodes,
      ...pendingNodes.filter(
        (p) =>
          !taken.has(`${p.metadata?.active_peer}::${p.metadata?.round_num}`),
      ),
    ];
  }, [serverNodes, pendingNodes]);

  // Hang each pending node off its lane's previous round so it is not orphaned.
  const allEdges = useMemo(() => {
    const extra: TreeEdge[] = [];
    for (const p of pendingNodes) {
      const round = p.metadata?.round_num ?? 0;
      if (round === 0) continue;
      const parent = serverNodes.find(
        (n) =>
          n.metadata?.active_peer === p.metadata?.active_peer &&
          n.metadata?.round_num === round - 1,
      );
      if (parent) {
        extra.push({ id: `e-${parent.id}-${p.id}`, source: parent.id, target: p.id });
      }
    }
    return extra.length ? [...edges, ...extra] : edges;
  }, [edges, serverNodes, pendingNodes]);

  const pendingModels = useMemo(
    () =>
      new Set(
        pendingNodes
          .map((n) => n.metadata?.active_peer)
          .filter((m): m is string => !!m),
      ),
    [pendingNodes],
  );

  return {
    nodes,
    edges: allEdges,
    lanes,
    sessionMeta,
    loading,
    pendingModels,
    fetchTree,
    clearTree,
    startPolling,
    stopPolling,
    addPendingNode,
    resolvePendingNode,
    clearPendingNodes,
  };
}
