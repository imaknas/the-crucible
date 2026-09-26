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
    fetchThreads().then(() => {
      // ?thread=<id> (e.g. from `crucible tree --open`) wins over the last
      // thread opened here, and is then dropped from the URL so a reload
      // doesn't keep forcing it.
      const params = new URLSearchParams(window.location.search);
      const linked = params.get("thread");
      if (linked) {
        params.delete("thread");
        const query = params.toString();
        window.history.replaceState(
          null,
          "",
          `${window.location.pathname}${query ? `?${query}` : ""}${window.location.hash}`,
        );
        localStorage.setItem("crucible_thread_id", linked);
      }
      const saved = linked ?? localStorage.getItem("crucible_thread_id");
      if (saved) {
        setThreadId(saved);
        onThreadSwitch(saved);
      }
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

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
