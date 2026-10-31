import { useState, useCallback, useEffect, useRef } from "react";
import * as api from "@/lib/api";
import { errorMessage } from "@/lib/errors";
import type { Confirm } from "@/hooks/useConfirm";
import type { PushToast } from "@/hooks/useToasts";
import { writeStoredValue } from "@/hooks/useStoredValue";

export const THREAD_STORAGE_KEY = "crucible_thread_id";

export interface Thread {
  id: string;
  title: string;
}

interface Options {
  /** The open thread is gone or replaced by a new one: drop its tree, messages and attachments. */
  onThreadClear: (deleted?: boolean) => void;
  /** Another thread was opened: load it. */
  onThreadSwitch: (id: string) => void;
  confirm: Confirm;
  pushToast: PushToast;
  /**
   * Asked before the open thread is left (switch, new session, home). A live
   * run on screen is cancelled by leaving, so the page asks first; false
   * keeps the person where they are.
   */
  beforeLeave?: () => Promise<boolean>;
}

function readStoredThread(): string | null {
  try {
    return localStorage.getItem(THREAD_STORAGE_KEY);
  } catch {
    return null;
  }
}

export function useThreads({ onThreadClear, onThreadSwitch, confirm, pushToast, beforeLeave }: Options) {
  const [threadId, setThreadId] = useState<string | null>(null);
  const [threads, setThreads] = useState<Thread[]>([]);
  // Read at call time: the page builds the guard from state that changes
  // every render, and the actions below are memoised.
  const beforeLeaveRef = useRef(beforeLeave);
  useEffect(() => {
    beforeLeaveRef.current = beforeLeave;
  }, [beforeLeave]);

  const fetchThreads = useCallback(async () => {
    try {
      const data = await api.listThreads();
      setThreads(data.threads || []);
    } catch (error) {
      console.error("[threads] list failed:", error);
    }
  }, []);

  const mayLeave = useCallback(async () => (beforeLeaveRef.current ? beforeLeaveRef.current() : true), []);

  const startNewExperiment = useCallback(async () => {
    if (!(await mayLeave())) return;
    const newId = `thread_${Math.random().toString(36).slice(2, 9)}`;
    setThreadId(newId);
    writeStoredValue(THREAD_STORAGE_KEY, newId);
    onThreadClear();
    fetchThreads();
  }, [fetchThreads, onThreadClear, mayLeave]);

  /** Open a thread; "" goes back to the landing view. */
  const switchThread = useCallback(
    async (id: string) => {
      if (id === threadId) return;
      if (!(await mayLeave())) return;
      setThreadId(id || null);
      writeStoredValue(THREAD_STORAGE_KEY, id || null);
      if (id) onThreadSwitch(id);
      else onThreadClear();
    },
    [threadId, onThreadSwitch, onThreadClear, mayLeave],
  );

  const deleteThread = useCallback(
    async (id: string) => {
      const ok = await confirm(
        "Delete session",
        "This permanently removes this session, all its branches and its debates. This can't be undone.",
        { confirmLabel: "Delete" },
      );
      if (!ok) return;
      try {
        await api.deleteThread(id);
        if (id === threadId) {
          setThreadId(null);
          writeStoredValue(THREAD_STORAGE_KEY, null);
          onThreadClear(true);
        }
        pushToast("Session deleted.", "success");
        fetchThreads();
      } catch (err) {
        pushToast(errorMessage(err, "Couldn't delete the session"), "error");
      }
    },
    [confirm, threadId, onThreadClear, pushToast, fetchThreads],
  );

  /** Rename a thread; resolves true once the new title is saved. */
  const renameThread = useCallback(
    async (id: string, newTitle: string): Promise<boolean> => {
      const title = newTitle.trim();
      if (!title) return false;
      try {
        await api.renameThread(id, title);
        fetchThreads();
        return true;
      } catch (err) {
        pushToast(errorMessage(err, "Couldn't rename the session"), "error");
        return false;
      }
    },
    [fetchThreads, pushToast],
  );

  useEffect(() => {
    // The list is set from the response callback, not synchronously in the
    // effect body (react-hooks/set-state-in-effect).
    api
      .listThreads()
      .then((data) => setThreads(data.threads || []))
      .catch((error) => console.error("[threads] list failed:", error))
      .then(() => {
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
          writeStoredValue(THREAD_STORAGE_KEY, linked);
        }
        const saved = linked ?? readStoredThread();
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
