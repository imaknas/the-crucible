import { useCallback, useMemo, useState } from "react";
import * as api from "@/lib/api";
import { errorMessage } from "@/lib/errors";
import type { PushToast } from "@/hooks/useToasts";

interface Options {
  threadId: string | null;
  /** Reload the tree after a change (it carries the notes). */
  refresh: () => void;
  pushToast: PushToast;
  /** The Control Panel's summarizer choice; null = the backend's default. */
  summarizer?: string | null;
  /** Collapse a node once its subtree is summarized: the summary stands in for it. */
  collapse: (id: string, folded: boolean) => void;
}

/** What a person writes on tree nodes: branch names, bookmarks, subtree summaries. */
export function useNodeNotes({ threadId, refresh, pushToast, summarizer, collapse }: Options) {
  /** Nodes whose subtree is being summarized now. */
  const [summarizing, setSummarizing] = useState<string[]>([]);

  const rename = useCallback(
    async (id: string, name: string) => {
      if (!threadId) return;
      try {
        await api.labelNode(threadId, id, { name });
        refresh();
      } catch (e) {
        pushToast(errorMessage(e, "Couldn't rename the branch"), "error");
      }
    },
    [threadId, refresh, pushToast],
  );

  const setBookmark = useCallback(
    async (id: string, bookmarked: boolean) => {
      if (!threadId) return;
      try {
        await api.labelNode(threadId, id, { bookmarked });
        refresh();
      } catch (e) {
        pushToast(errorMessage(e, "Couldn't change the bookmark"), "error");
      }
    },
    [threadId, refresh, pushToast],
  );

  const summarize = useCallback(
    async (id: string) => {
      if (!threadId) return;
      setSummarizing((s) => [...s, id]);
      try {
        await api.summarizeSubtree(threadId, id, summarizer);
        collapse(id, true);
        refresh();
      } catch (e) {
        pushToast(errorMessage(e, "Couldn't summarize the branch"), "error");
      } finally {
        setSummarizing((s) => s.filter((x) => x !== id));
      }
    },
    [threadId, summarizer, collapse, refresh, pushToast],
  );

  const clearSummary = useCallback(
    async (id: string) => {
      if (!threadId) return;
      try {
        await api.clearSubtreeSummary(threadId, id);
        refresh();
      } catch (e) {
        pushToast(errorMessage(e, "Couldn't remove the summary"), "error");
      }
    },
    [threadId, refresh, pushToast],
  );

  // Stable while nothing changes: the canvas rebuilds its nodes when this does.
  return useMemo(
    () => ({ rename, setBookmark, summarize, clearSummary, summarizing }),
    [rename, setBookmark, summarize, clearSummary, summarizing],
  );
}
