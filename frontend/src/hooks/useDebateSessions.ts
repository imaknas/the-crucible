import { useCallback, useEffect, useState } from "react";
import * as api from "@/lib/api";
import type { DebateSession } from "@/lib/types";

/**
 * The sidebar's debate list (newest first, as the API returns it).
 *
 * Loaded once and refreshed when something changes it — a debate created,
 * finished, deleted, or another thread opened — rather than on every change
 * of the thread list's identity, which refetched it after each chat turn.
 */
export function useDebateSessions(threadId: string | null) {
  const [sessions, setSessions] = useState<DebateSession[]>([]);

  const refreshSessions = useCallback(() => {
    api
      .listDebateSessions()
      .then(setSessions)
      .catch(() => {});
  }, []);

  useEffect(() => {
    refreshSessions();
  }, [threadId, refreshSessions]);

  /** Drop a deleted session without waiting for a refetch. */
  const forgetSession = useCallback(
    (sessionId: string) => setSessions((prev) => prev.filter((s) => s.session_id !== sessionId)),
    [],
  );

  return { sessions, refreshSessions, forgetSession };
}
