import { useEffect, useState } from "react";
import * as api from "@/lib/api";
import type { VoteStats } from "@/lib/types";

/** Win rates for the Control Panel, reloaded after each vote (`version`) and for another task type. */
export function useVoteStats(version: number) {
  const [taskType, setTaskType] = useState("");
  const [loaded, setLoaded] = useState<{ key: string; stats: VoteStats } | null>(null);
  const key = `${version}|${taskType}`;
  useEffect(() => {
    let live = true;
    api
      .fetchVoteStats(taskType || null)
      .then((stats) => live && setLoaded({ key, stats }))
      .catch((e) => console.warn("Couldn't load the win rates:", e));
    return () => {
      live = false;
    };
  }, [key, taskType]);
  // The previous numbers stay until the new ones arrive: no flicker after a vote.
  return { stats: loaded?.stats ?? null, taskType, setTaskType };
}
