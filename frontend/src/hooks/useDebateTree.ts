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

const pendingId = (modelId: string, roundNum: number) =>
  `${modelId}::pending-r${roundNum}`;

/** The backend's excerpt (utils.helpers.get_preview_text): reasoning and
 * markdown stripped, one line, cut at a word with an ellipsis. */
export function excerpt(text: string, max: number): string {
  const flat = text
    .replace(/<think>[\s\S]*?<\/think>/gi, "")
    .replace(/<think>[\s\S]*$/i, "")
    .replace(/[#*`_~[\]()]/g, "")
    .split(/\s+/)
    .filter(Boolean)
    .join(" ");
  if (flat.length <= max) return flat;
  const cut = flat.slice(0, max);
  return `${cut.includes(" ") ? cut.slice(0, cut.lastIndexOf(" ")) : cut}...`;
}

export function useDebateTree() {
  const [serverNodes, setServerNodes] = useState<TreeNode[]>([]);
  const [edges, setEdges] = useState<TreeEdge[]>([]);
  const [lanes, setLanes] = useState<DebateLane[]>([]);
  const [sessionMeta, setSessionMeta] =
    useState<DebateTreeResponse["session_metadata"] | null>(null);
  const [loading, setLoading] = useState(false);
  const [pendingNodes, setPendingNodes] = useState<TreeNode[]>([]);

  // The session the canvas is showing. A response for any other session (a
  // refetch still in flight from the one we just left) is dropped.
  const sessionRef = useRef<string | null>(null);
  // One coalesced refetch for the replies that finish close together: each
  // stream_end used to fetch the whole tree on its own, on top of a 3-second
  // poll the socket's events made redundant.
  const soonRef = useRef<{ timer: ReturnType<typeof setTimeout>; done: Promise<void> } | null>(null);

  const loadTree = useCallback(async (sessionId: string) => {
    try {
      setLoading(true);
      const data = await fetchDebateTree(sessionId);
      if (sessionRef.current !== sessionId) return;
      // Only the server-owned slice is replaced; pending nodes live separately
      // so a refetch landing mid-round can't wipe the "Thinking…" markers.
      setServerNodes(data.nodes);
      setEdges(data.edges);
      setLanes(data.lanes);
      setSessionMeta(data.session_metadata);
    } catch (e) {
      console.error("[useDebateTree] fetch failed:", e);
    } finally {
      setLoading(false);
    }
  }, []);

  // An explicit fetch selects the session; refetches only refresh the current one.
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

  const cancelSoon = useCallback(() => {
    if (soonRef.current) clearTimeout(soonRef.current.timer);
    soonRef.current = null;
  }, []);

  const clearTree = useCallback(() => {
    setServerNodes([]);
    setEdges([]);
    setLanes([]);
    setSessionMeta(null);
    setPendingNodes([]);
    sessionRef.current = null;
    cancelSoon();
  }, [cancelSoon]);

  /** Refetch shortly, once for every caller within the window. */
  const refreshSoon = useCallback(
    (sessionId: string, delayMs = 400): Promise<void> => {
      if (soonRef.current) return soonRef.current.done;
      let timer: ReturnType<typeof setTimeout> = setTimeout(() => {}, 0);
      const done = new Promise<void>((resolve) => {
        timer = setTimeout(() => {
          soonRef.current = null;
          loadTree(sessionId).then(resolve);
        }, delayMs);
      });
      soonRef.current = { timer, done };
      return done;
    },
    [loadTree],
  );

  // Never leave a timer running past unmount.
  useEffect(() => cancelSoon, [cancelSoon]);

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
      // A settled node of an earlier round stays until the server's copy lands.
      setPendingNodes((prev) => [
        ...prev.filter((n) => n.metadata?.active_peer !== modelId || !n.metadata?.pending),
        pendingNode,
      ]);
    },
    [],
  );

  /**
   * A reply that finished: its placeholder becomes the node the server will
   * draw, under the same id (`{model}::{checkpoint}`, the stream_end's
   * checkpoint), so it reads and selects at once, and the refetch that
   * follows replaces it without remounting it or dropping a selection.
   */
  const settlePendingNode = useCallback(
    (modelId: string, roundNum: number, checkpointId: string, content: string) => {
      const id = pendingId(modelId, roundNum);
      setPendingNodes((prev) =>
        prev.map((n) =>
          n.id !== id
            ? n
            : {
                ...n,
                id: `${modelId}::${checkpointId}`,
                data: { label: excerpt(content, 40) || "…" },
                metadata: { ...n.metadata, pending: false, preview: excerpt(content, 400) },
              },
        ),
      );
    },
    [],
  );

  // Removes exactly one round's placeholder. Filtering by model alone raced
  // the next round: its fresh pending node, added while this fetch was in
  // flight, was deleted along with the old one.
  const resolvePendingNode = useCallback(
    async (modelId: string, sessionId: string, roundNum: number) => {
      await refreshSoon(sessionId);
      setPendingNodes((prev) =>
        prev.filter((n) => n.metadata?.active_peer !== modelId || n.metadata?.round_num !== roundNum),
      );
    },
    [refreshSoon],
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

  // Hang each pending node off its lane's latest earlier round so it is not
  // orphaned (not round - 1: a round the model failed has no node).
  const allEdges = useMemo(() => {
    const extra: TreeEdge[] = [];
    for (const p of pendingNodes) {
      const round = p.metadata?.round_num ?? 0;
      if (round === 0) continue;
      const parent = serverNodes
        .filter(
          (n) =>
            n.metadata?.active_peer === p.metadata?.active_peer &&
            (n.metadata?.round_num ?? 0) < round,
        )
        .sort((a, b) => (b.metadata?.round_num ?? 0) - (a.metadata?.round_num ?? 0))[0];
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
          .filter((n) => n.metadata?.pending)
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
    refreshSoon,
    clearTree,
    addPendingNode,
    settlePendingNode,
    resolvePendingNode,
    clearPendingNodes,
  };
}
