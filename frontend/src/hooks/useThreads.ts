import { useState, useCallback, useEffect } from "react";
import * as api from "@/lib/api";

export function useThreads(
  onThreadClear: (deleted?: boolean) => void,
  onThreadSwitch: (id: string) => void,
  showConfirm: (title: string, message: string) => Promise<boolean>,
) {
  const [threadId, setThreadId] = useState<string | null>(null);
  const [threads, setThreads] = useState<any[]>([]);

  const fetchThreads = useCallback(async () => {
    try {
      const data = await api.listThreads();
      setThreads(data.threads || []);
    } catch (error) {
      console.error("[LIBRARY] Connection error:", error);
    }
  }, []);

  const startNewExperiment = useCallback(() => {
    const newId = `thread_${Math.random().toString(36).slice(2, 9)}`;
    setThreadId(newId);
    localStorage.setItem("crucible_thread_id", newId);
    onThreadClear();
    fetchThreads();
  }, [fetchThreads, onThreadClear]);

  const switchThread = useCallback(
    (id: string) => {
      setThreadId(id);
      localStorage.setItem("crucible_thread_id", id);
      onThreadSwitch(id);
    },
    [onThreadSwitch],
  );

  const deleteThread = async (e: React.MouseEvent, id: string) => {
    e.stopPropagation();
    if (
      !(await showConfirm(
        "Delete Experiment",
        "This will permanently remove this experiment and all its branches. This action cannot be undone.",
      ))
    )
      return;
    try {
      await api.deleteThread(id);
      if (id === threadId) {
        setThreadId(null);
        localStorage.removeItem("crucible_thread_id");
        onThreadClear(true);
      }
      fetchThreads();
    } catch (err) {
      console.error("Delete failed:", err);
    }
  };

  const renameThread = async (id: string, newTitle: string) => {
    try {
      await api.renameThread(id, newTitle);
      fetchThreads();
    } catch (err) {
      console.error("Rename failed:", err);
    }
  };

  useEffect(() => {
    // Force clear the thread on initial mount to ensure LandingView is displayed
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setThreadId(null);
    fetchThreads();
  }, [fetchThreads]);

  return {
    threadId,
    threads,
    fetchThreads,
    startNewExperiment,
    switchThread,
    deleteThread,
    renameThread,
  };
}
