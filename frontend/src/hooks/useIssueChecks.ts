import { useCallback, useEffect, useMemo, useState } from "react";
import * as api from "@/lib/api";
import type { IssueCheck } from "@/lib/types";
import { errorMessage } from "@/lib/errors";

type PushToast = (message: string, kind: "error" | "success" | "info", title?: string) => void;

/**
 * Checks of the open thread's issue lists: loaded with it, run on request
 * (one model call per checker), shown under the list they check.
 */
export function useIssueChecks(threadId: string | null, pushToast: PushToast) {
  const [checks, setChecks] = useState<{ thread: string | null; list: IssueCheck[] }>({ thread: null, list: [] });
  const [running, setRunning] = useState<string | null>(null);

  useEffect(() => {
    if (!threadId) return;
    let live = true;
    api
      .listIssueChecks(threadId)
      .then((list) => live && setChecks({ thread: threadId, list }))
      // A thread with no checks answers an empty list; a failure here only
      // means none are shown.
      .catch(() => live && setChecks({ thread: threadId, list: [] }));
    return () => {
      live = false;
    };
  }, [threadId]);

  const run = useCallback(
    async (checkpointId: string) => {
      if (!threadId || running) return;
      setRunning(checkpointId);
      try {
        const check = await api.runIssueCheck(threadId, checkpointId);
        setChecks((prev) => ({
          thread: threadId,
          list: [check, ...(prev.thread === threadId ? prev.list : []).filter((c) => c.checkpoint_id !== check.checkpoint_id)],
        }));
      } catch (e) {
        pushToast(errorMessage(e, "Couldn't check the problems"), "error");
      } finally {
        setRunning(null);
      }
    },
    [threadId, running, pushToast],
  );

  const list = useMemo(() => (checks.thread === threadId ? checks.list : []), [checks, threadId]);
  const checkFor = useCallback((id: string) => list.find((c) => c.checkpoint_id === id) ?? null, [list]);
  const isRunning = useCallback((id: string) => running === id, [running]);
  const busy = running !== null;
  return useMemo(() => ({ checkFor, isRunning, run, busy }), [checkFor, isRunning, run, busy]);
}

export type IssueChecks = ReturnType<typeof useIssueChecks>;
