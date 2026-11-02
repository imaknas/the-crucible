import { useEffect, useState } from "react";
import * as api from "@/lib/api";
import type { NextTurnContext } from "@/lib/context";

/**
 * What the next message would send each answering model from the branch
 * point (GET /history/{thread}/context): refetched when the thread, the
 * branch point, the answering models or the head move. Null until known, and
 * while a new key is loading; a failure leaves it null (the chip then shows
 * no numbers rather than stale ones).
 */
export function useNextTurnContext(
  threadId: string | null,
  checkpoint: string | null,
  head: string | null,
  models: string[],
): NextTurnContext[] | null {
  const key =
    threadId && (checkpoint || head) && models.length
      ? `${threadId}|${checkpoint ?? ""}|${head ?? ""}|${models.join(",")}`
      : null;
  const [loaded, setLoaded] = useState<{
    key: string;
    rows: NextTurnContext[];
  } | null>(null);

  useEffect(() => {
    if (!key || !threadId) return;
    let live = true;
    api
      .fetchNextTurnContext(threadId, checkpoint, models)
      .then((r) => {
        if (live) setLoaded({ key, rows: r.models });
      })
      .catch((e) => console.warn("Couldn't measure the next turn:", e));
    return () => {
      live = false;
    };
    // `key` covers threadId, checkpoint, head and models.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key]);

  return loaded && loaded.key === key ? loaded.rows : null;
}
