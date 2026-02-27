import { useState, useCallback } from "react";
import * as api from "@/lib/api";

export function useHistoryTree(onMessagesLoaded: (messages: any[]) => void) {
  const [nodes, setNodes] = useState<any[]>([]);
  const [edges, setEdges] = useState<any[]>([]);
  const [activeCheckpoint, setActiveCheckpoint] = useState<string | null>(null);
  const [showTree, setShowTree] = useState(true);

  const fetchHistory = useCallback(
    async (tid: string, cpId?: string, skipMessages: boolean = false) => {
      if (!tid) return;
      // If we are switching threads or loading a new root, clear old state to prevent "ghosting"
      if (!cpId) {
        setNodes([]);
        setEdges([]);
      }
      try {
        const data = await api.fetchHistory(tid, cpId);

        setNodes(data.nodes || []);
        setEdges(data.edges || []);

        if (!skipMessages) {
          onMessagesLoaded(data.messages || []);
        }

        if (data.current_checkpoint) {
          setActiveCheckpoint(data.current_checkpoint);
        }
      } catch (error) {
        console.error("Error fetching history:", error);
      }
    },
    [onMessagesLoaded],
  );

  const clearTree = useCallback(() => {
    setNodes([]);
    setEdges([]);
    setActiveCheckpoint(null);
    setShowTree(false);
  }, []);

  return {
    nodes,
    setNodes,
    edges,
    setEdges,
    activeCheckpoint,
    setActiveCheckpoint,
    showTree,
    setShowTree,
    fetchHistory,
    clearTree,
  };
}
