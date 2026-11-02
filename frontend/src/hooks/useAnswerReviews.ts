import { useCallback, useEffect, useState } from "react";
import * as api from "@/lib/api";
import type { AnswerReview } from "@/lib/types";
import { errorMessage } from "@/lib/errors";

type PushToast = (message: string, kind: "error" | "success" | "info", title?: string) => void;

/** The same set of answers, whatever order it was named in. */
export function sameAnswers(a: string[], b: string[]): boolean {
  return a.length === b.length && [...a].sort().join("|") === [...b].sort().join("|");
}

/**
 * Peer reviews on the open thread: loaded with it, run on request (one model
 * call per answer's author), shown beside the answers they score.
 */
export function useAnswerReviews(threadId: string | null, pushToast: PushToast) {
  const [reviews, setReviews] = useState<{ thread: string | null; list: AnswerReview[] }>({ thread: null, list: [] });
  const [running, setRunning] = useState<string[] | null>(null);

  useEffect(() => {
    if (!threadId) return;
    let live = true;
    api
      .listAnswerReviews(threadId)
      .then((list) => live && setReviews({ thread: threadId, list }))
      // A thread with no reviews yet answers an empty list; a failure here
      // only means none are shown.
      .catch(() => live && setReviews({ thread: threadId, list: [] }));
    return () => {
      live = false;
    };
  }, [threadId]);

  const run = useCallback(
    async (ids: string[]) => {
      if (!threadId || running) return;
      setRunning(ids);
      try {
        const review = await api.runAnswerReview(threadId, ids);
        setReviews((prev) => ({
          thread: threadId,
          list: [review, ...(prev.thread === threadId ? prev.list : []).filter((r) => r.review_key !== review.review_key)],
        }));
      } catch (e) {
        pushToast(errorMessage(e, "Couldn't run the peer review"), "error");
      } finally {
        setRunning(null);
      }
    },
    [threadId, running, pushToast],
  );

  const list = reviews.thread === threadId ? reviews.list : [];
  const reviewFor = useCallback((ids: string[]) => list.find((r) => sameAnswers(r.checkpoint_ids, ids)) ?? null, [list]);
  const isRunning = useCallback((ids: string[]) => !!running && sameAnswers(running, ids), [running]);
  return { reviewFor, isRunning, run };
}
