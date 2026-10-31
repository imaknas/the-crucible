import { useCallback, useMemo } from "react";
import * as api from "@/lib/api";
import { errorMessage } from "@/lib/errors";
import type { TreeEdge, TreeNode } from "@/lib/types";
import { branchPoint } from "@/lib/branching";
import { lastUserText } from "@/lib/messages";
import type { Confirm } from "@/hooks/useConfirm";
import type { PushToast } from "@/hooks/useToasts";

interface Options {
  threadId: string | null;
  nodes: TreeNode[];
  edges: TreeEdge[];
  setNodes: React.Dispatch<React.SetStateAction<TreeNode[]>>;
  /** The node the person chose to continue from; null = the latest turn (useHistoryTree). */
  chosen: string | null;
  setChosen: (id: string | null) => void;
  /** Where the thread stands (the answered head). */
  head: string | null;
  /** The path the transcript shows. */
  shown: string | null;
  fetchHistory: (threadId: string, checkpointId?: string) => void;
  fetchThreads: () => void;
  clearChatMessages: () => void;
  setInput: (text: string) => void;
  setShowTree: (tree: boolean) => void;
  confirm: Confirm;
  pushToast: PushToast;
  /** A node was clicked: it decides who answers next (useReplyTarget). */
  continueFrom: (node: TreeNode | undefined) => void;
}

/** What the conversation tree lets you do to its checkpoints. */
export function useTreeActions({
  threadId,
  nodes,
  edges,
  setNodes,
  chosen,
  setChosen,
  head,
  shown,
  fetchHistory,
  fetchThreads,
  clearChatMessages,
  setInput,
  setShowTree,
  confirm,
  pushToast,
  continueFrom,
}: Options) {
  /** The node the next message continues from: the chosen one, else the head. */
  const anchorNode = useMemo(() => nodes.find((n) => n.id === (chosen ?? head)), [nodes, chosen, head]);
  /** The node whose path is on screen. */
  const shownNode = useMemo(() => nodes.find((n) => n.id === shown), [nodes, shown]);

  const parentOf = useCallback((id: string) => edges.find((e) => e.target === id)?.source ?? null, [edges]);

  /**
   * Open a checkpoint: it becomes the branch point for the next message, and
   * a model's reply is continued with that model; any other node goes back
   * to the selected models. Only an explicit click does this — the refresh
   * after every turn and opening a thread used to collapse a multi-model
   * selection to whichever model wrote the newest node.
   */
  const selectCheckpoint = useCallback(
    (id: string) => {
      continueFrom(nodes.find((n) => n.id === id));
      setChosen(id);
      if (threadId) fetchHistory(threadId, id);
    },
    [nodes, continueFrom, setChosen, threadId, fetchHistory],
  );

  /**
   * Show a checkpoint's path without changing what the next message
   * continues or who answers it: reading another model's reply is not a
   * decision to continue it.
   */
  const viewCheckpoint = useCallback(
    (id: string) => {
      if (threadId) fetchHistory(threadId, id);
    },
    [threadId, fetchHistory],
  );

  /** What the composer's "Replying to" chip shows. */
  const branch = useMemo(() => branchPoint(nodes, chosen, head), [nodes, chosen, head]);

  /**
   * Back to the latest turn: every model continues its own reply there. Not
   * a node click: who answers stays as it is.
   */
  const resetToLatest = useCallback(() => {
    setChosen(null);
    if (threadId) fetchHistory(threadId);
  }, [setChosen, threadId, fetchHistory]);

  /**
   * "Branch from here" on a tree node: it becomes the parent of the next
   * message, and the composer comes up. Like editAndRebranch, moving to the
   * composer is the point of the action.
   */
  const branchFrom = useCallback(
    (id: string) => {
      selectCheckpoint(id);
      setShowTree(false);
    },
    [selectCheckpoint, setShowTree],
  );

  const deleteNode = useCallback(
    async (nodeId: string) => {
      if (!threadId) return;
      const ok = await confirm(
        "Delete message",
        "This removes this message and everything that branches from it. This can't be undone.",
        { confirmLabel: "Delete" },
      );
      if (!ok) return;
      try {
        await api.deleteCheckpoint(threadId, nodeId);
        if (chosen === nodeId) {
          // The chosen checkpoint is gone: continue from its parent.
          const parentId = parentOf(nodeId);
          clearChatMessages();
          setChosen(parentId);
          fetchHistory(threadId, parentId ?? undefined);
        } else {
          fetchHistory(threadId, chosen ?? undefined);
        }
        fetchThreads();
      } catch (error) {
        pushToast(errorMessage(error, "Couldn't delete the message"), "error");
      }
    },
    [chosen, threadId, confirm, parentOf, clearChatMessages, setChosen, fetchHistory, fetchThreads, pushToast],
  );

  /**
   * Re-ask one of your messages differently: branch from its parent with the
   * message's full text in the composer (the tree label is a clipped,
   * markdown-stripped preview). The one action that switches the view on
   * purpose.
   */
  const editAndRebranch = useCallback(async () => {
    const node = shownNode;
    if (!node || !threadId) return;
    let text: string | null = null;
    try {
      text = lastUserText((await api.fetchHistory(threadId, node.id)).messages ?? []);
    } catch (error) {
      pushToast(errorMessage(error, "Couldn't load the message"), "error");
      return;
    }
    const parentId = parentOf(node.id);
    setChosen(parentId);
    fetchHistory(threadId, parentId ?? undefined);
    setInput(text ?? node.data.label);
    setShowTree(false);
  }, [shownNode, threadId, parentOf, setChosen, fetchHistory, setInput, setShowTree, pushToast]);

  const moveNode = useCallback(
    (nodeId: string, position: { x: number; y: number }) => {
      if (!threadId) return;
      // Update locally first so the node doesn't snap back on re-render.
      setNodes((prev) => prev.map((n) => (n.id === nodeId ? { ...n, position: { ...position } } : n)));
      api
        .saveNodePositions(threadId, [{ node_id: nodeId, x: position.x, y: position.y }])
        .catch((e) => pushToast(errorMessage(e, "Couldn't save the node position"), "error"));
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
      api
        .saveNodePositions(threadId, updates)
        .catch((e) => pushToast(errorMessage(e, "Couldn't save the new layout"), "error"));
    },
    [threadId, setNodes, pushToast],
  );

  return {
    anchorNode,
    shownNode,
    selectCheckpoint,
    viewCheckpoint,
    deleteNode,
    editAndRebranch,
    moveNode,
    applyLayout,
    branch,
    resetToLatest,
    branchFrom,
  };
}
