import { useState, useCallback, useRef } from "react";
import * as api from "@/lib/api";
import { errorMessage } from "@/lib/errors";
import type { Message, TreeEdge, TreeNode } from "@/lib/types";
import { useStoredValue, writeStoredValue } from "@/hooks/useStoredValue";
import type { PushToast } from "@/hooks/useToasts";

const VIEW_KEY = "crucible_view";

/**
 * A thread's conversation tree and the three checkpoints that matter in it.
 *
 * - `chosen`: the node the person picked to continue from (a click, Branch
 *   from here, Edit & fork), or null for "the latest turn". It is what the
 *   next message's `parent_checkpoint_id` carries, and only an explicit
 *   action sets it: it used to be overwritten by whichever request finished
 *   last (the first reply of a turn, then the history refresh).
 * - `head`: where the thread stands, as GET /history reports it with no
 *   checkpoint (the answered head).
 * - `shown`: the path the transcript is showing. Reading another model's
 *   reply moves it without changing what the next message continues.
 *
 * Responses arrive in any order; only the newest request's is applied, so a
 * slow fetch for the previous thread or checkpoint can't replace this one.
 */
export function useHistoryTree(onMessagesLoaded: (messages: Message[]) => void, pushToast?: PushToast) {
  const [nodes, setNodes] = useState<TreeNode[]>([]);
  const [edges, setEdges] = useState<TreeEdge[]>([]);
  const [chosen, setChosen] = useState<string | null>(null);
  const [head, setHead] = useState<string | null>(null);
  const [shown, setShown] = useState<string | null>(null);
  const [isHistoryLoading, setIsHistoryLoading] = useState(false);
  const requestRef = useRef(0);
  const threadRef = useRef<string | null>(null);

  // Tree or transcript, as the person last left it: a restored session and a
  // new one open the same view, and nothing switches it behind their back.
  const showTree = useStoredValue(VIEW_KEY) === "tree";
  const setShowTree = useCallback((tree: boolean) => writeStoredValue(VIEW_KEY, tree ? "tree" : "arena"), []);

  const fetchHistory = useCallback(
    async (tid: string, cpId?: string, skipMessages: boolean = false) => {
      if (!tid) return;
      const request = ++requestRef.current;
      if (threadRef.current !== tid) {
        // Another thread: nothing of the previous one may carry over, least
        // of all the checkpoint the next message would branch from.
        threadRef.current = tid;
        setNodes([]);
        setEdges([]);
        setChosen(null);
        setHead(null);
        setShown(null);
      }
      setIsHistoryLoading(true);
      try {
        const data = await api.fetchHistory(tid, cpId);
        if (request !== requestRef.current) return;
        setNodes(data.nodes || []);
        setEdges(data.edges || []);
        const current = data.current_checkpoint ?? null;
        setShown(current);
        if (!cpId) setHead(current);
        if (!skipMessages) onMessagesLoaded(data.messages || []);
      } catch (error) {
        if (request !== requestRef.current) return;
        pushToast?.(errorMessage(error, "Couldn't load the conversation"), "error");
      } finally {
        if (request === requestRef.current) setIsHistoryLoading(false);
      }
    },
    [onMessagesLoaded, pushToast],
  );

  const clearTree = useCallback(() => {
    requestRef.current++;
    threadRef.current = null;
    setNodes([]);
    setEdges([]);
    setChosen(null);
    setHead(null);
    setShown(null);
    setIsHistoryLoading(false);
  }, []);

  return {
    nodes,
    setNodes,
    edges,
    setEdges,
    chosen,
    setChosen,
    head,
    shown,
    showTree,
    setShowTree,
    isHistoryLoading,
    fetchHistory,
    clearTree,
  };
}
