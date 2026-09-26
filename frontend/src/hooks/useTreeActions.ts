import { useCallback, useMemo } from "react";
import * as api from "@/lib/api";
import type { TreeEdge, TreeNode } from "@/lib/types";

interface Options {
  threadId: string | null;
  nodes: TreeNode[];
  edges: TreeEdge[];
  setNodes: React.Dispatch<React.SetStateAction<TreeNode[]>>;
  activeCheckpoint: string | null;
  setActiveCheckpoint: (id: string | null) => void;
  fetchHistory: (threadId: string, checkpointId?: string) => void;
  fetchThreads: () => void;
  clearChatMessages: () => void;
  setInput: (text: string) => void;
  setShowTree: (tree: boolean) => void;
  confirm: (title: string, message: string) => Promise<boolean>;
  pushToast: (message: string) => void;
}

/** What the conversation tree lets you do to its checkpoints. */
export function useTreeActions({
  threadId,
  nodes,
  edges,
  setNodes,
  activeCheckpoint,
  setActiveCheckpoint,
  fetchHistory,
  fetchThreads,
  clearChatMessages,
  setInput,
  setShowTree,
  confirm,
  pushToast,
}: Options) {
  const activeCheckpointNode = useMemo(
    () => nodes.find((n) => n.id === activeCheckpoint),
    [nodes, activeCheckpoint],
  );

  const parentOf = useCallback(
    (id: string) => edges.find((e) => e.target === id)?.source ?? null,
    [edges],
  );

  /** Open a checkpoint: it becomes the branch point for the next message. */
  const selectCheckpoint = useCallback(
    (id: string) => {
      setActiveCheckpoint(id);
      if (threadId) fetchHistory(threadId, id);
    },
    [threadId, fetchHistory, setActiveCheckpoint],
  );

  const deleteNode = useCallback(
    async (nodeId?: string) => {
      const targetId = nodeId || activeCheckpoint;
      if (!targetId || !threadId) return;
      const ok = await confirm(
        "Delete Node",
        "This will remove this checkpoint and all its descendants. This action cannot be undone.",
      );
      if (!ok) return;
      try {
        await api.deleteCheckpoint(threadId, targetId);
        if (activeCheckpoint === targetId) {
          // The open checkpoint is gone: fall back to its parent.
          const parentId = parentOf(targetId);
          clearChatMessages();
          setActiveCheckpoint(parentId);
          fetchHistory(threadId, parentId || undefined);
        } else {
          fetchHistory(threadId, activeCheckpoint || undefined);
        }
        fetchThreads();
      } catch (error) {
        console.error("Node deletion failed:", error);
        pushToast("Couldn't delete the node.");
      }
    },
    [activeCheckpoint, threadId, confirm, parentOf, clearChatMessages, setActiveCheckpoint, fetchHistory, fetchThreads, pushToast],
  );

  /**
   * Re-ask a user message differently: branch from its parent with the text
   * in the composer. The one action that switches the view on purpose.
   */
  const editAndRebranch = useCallback(() => {
    if (!activeCheckpointNode || !threadId) return;
    const parentId = parentOf(activeCheckpointNode.id);
    setActiveCheckpoint(parentId);
    fetchHistory(threadId, parentId || undefined);
    setInput(activeCheckpointNode.data.label.replace("...", ""));
    setShowTree(false);
  }, [activeCheckpointNode, threadId, parentOf, setActiveCheckpoint, fetchHistory, setInput, setShowTree]);

  const moveNode = useCallback(
    (nodeId: string, position: { x: number; y: number }) => {
      if (!threadId) return;
      // Update locally first so the node doesn't snap back on re-render.
      setNodes((prev) => prev.map((n) => (n.id === nodeId ? { ...n, position: { ...position } } : n)));
      api
        .saveNodePositions(threadId, [{ node_id: nodeId, x: position.x, y: position.y }])
        .catch(() => pushToast("Couldn't save the node position."));
    },
    [threadId, setNodes, pushToast],
  );

  // "Tidy Layout" moves every node at once — one request, not one per node.
  const applyLayout = useCallback(
    (updates: { node_id: string; x: number; y: number }[]) => {
      if (!threadId || updates.length === 0) return;
      const byId = new Map(updates.map((u) => [u.node_id, u]));
      setNodes((prev) =>
        prev.map((n) => {
          const u = byId.get(n.id);
          return u ? { ...n, position: { x: u.x, y: u.y } } : n;
        }),
      );
      api.saveNodePositions(threadId, updates).catch(() => pushToast("Couldn't save the new layout."));
    },
    [threadId, setNodes, pushToast],
  );

  return { activeCheckpointNode, selectCheckpoint, deleteNode, editAndRebranch, moveNode, applyLayout };
}
