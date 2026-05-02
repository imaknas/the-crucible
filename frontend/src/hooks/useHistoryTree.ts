import { useState, useCallback } from "react";
import * as api from "@/lib/api";

export function useHistoryTree(
  onMessagesLoaded: (messages: any[]) => void,
  onHistoryLoaded?: (data: any) => void,
) {
  const [nodes, setNodes] = useState<any[]>([]);
  const [edges, setEdges] = useState<any[]>([]);
  const [activeCheckpoint, setActiveCheckpoint] = useState<string | null>(null);
  const [showTree, setShowTree] = useState(true);
  const [isHistoryLoading, setIsHistoryLoading] = useState(false);

  const fetchHistory = useCallback(
    async (tid: string, cpId?: string, skipMessages: boolean = false) => {
      if (!tid) return;
      setIsHistoryLoading(true);
      // When switching threads or loading root, clear tree state.
      // NEVER pre-clear messages to [] — this caused the "flash" bug.
      // The reconciliation in handleMessagesLoaded preserves stable UUIDs.
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

        if (onHistoryLoaded) {
          onHistoryLoaded(data);
        }
      } catch (error) {
        console.error("Error fetching history:", error);
      } finally {
        setIsHistoryLoading(false);
      }
    },
    [onMessagesLoaded, onHistoryLoaded],
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
    isHistoryLoading,
    fetchHistory,
    clearTree,
  };
}
