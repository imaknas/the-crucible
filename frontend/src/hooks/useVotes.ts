import { useCallback, useEffect, useMemo, useState } from "react";
import * as api from "@/lib/api";
import { errorMessage } from "@/lib/errors";
import type { AnswerVote } from "@/lib/types";
import type { PushToast } from "@/hooks/useToasts";
import { useStoredValue, writeStoredValue } from "@/hooks/useStoredValue";

const BLIND_KEY = "crucible_blind";
const TASK_KEY = "crucible_vote_task";

export interface VoteInput {
  outcome: AnswerVote["outcome"];
  /** The best answer's checkpoint id. */
  best?: string | null;
  reason?: string | null;
  taskType: string;
  blind: boolean;
}

/**
 * The open thread's votes by turn, and voting. Also the two preferences a
 * vote uses: blind comparison (persisted; on by default is not assumed) and
 * the last task type chosen. Memoised: the compare cards re-render with it.
 */
export function useVotes(threadId: string | null, pushToast: PushToast) {
  const [loaded, setLoaded] = useState<{ threadId: string; votes: AnswerVote[] } | null>(null);
  /** Bumped after each vote, so the win rates elsewhere reload. */
  const [version, setVersion] = useState(0);
  const blind = useStoredValue(BLIND_KEY) === "1";
  const lastTask = useStoredValue(TASK_KEY) || "general";

  useEffect(() => {
    if (!threadId) return;
    let live = true;
    api
      .listVotes(threadId)
      .then((votes) => live && setLoaded({ threadId, votes }))
      .catch((e) => pushToast(errorMessage(e, "Couldn't load the votes"), "error"));
    return () => {
      live = false;
    };
  }, [threadId, pushToast]);

  const votes = useMemo(() => (loaded && loaded.threadId === threadId ? loaded.votes : []), [loaded, threadId]);
  const byTurn = useMemo(() => Object.fromEntries(votes.map((v) => [v.turn_id, v])), [votes]);

  const vote = useCallback(
    async (turnId: string, input: VoteInput): Promise<boolean> => {
      if (!threadId) return false;
      try {
        const stored = await api.voteTurn({
          thread_id: threadId,
          turn: turnId,
          outcome: input.outcome,
          best: input.best ?? null,
          reason: input.reason || null,
          task_type: input.taskType,
          blind: input.blind,
        });
        writeStoredValue(TASK_KEY, input.taskType);
        setLoaded((prev) => ({
          threadId,
          votes: [
            stored,
            ...(prev && prev.threadId === threadId ? prev.votes.filter((v) => v.turn_id !== turnId) : []),
          ],
        }));
        setVersion((n) => n + 1);
        return true;
      } catch (e) {
        pushToast(errorMessage(e, "Couldn't save the vote"), "error");
        return false;
      }
    },
    [threadId, pushToast],
  );

  const setBlind = useCallback((on: boolean) => writeStoredValue(BLIND_KEY, on ? "1" : null), []);

  return useMemo(
    () => ({ byTurn, vote, blind, setBlind, lastTask, version }),
    [byTurn, vote, blind, setBlind, lastTask, version],
  );
}
