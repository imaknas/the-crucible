import { useCallback, useMemo, useRef, useState } from "react";
import * as api from "@/lib/api";
import type { Confirm } from "@/hooks/useConfirm";
import type { CaseSummary, SavedCase } from "@/lib/cases";
import { errorMessage } from "@/lib/errors";
import { formatCost } from "@/lib/metrics";

type PushToast = (message: string, kind: "error" | "success" | "info", title?: string) => void;

/**
 * Saved cases: saving a turn as one, and the Saved cases dialog (the list,
 * the case open in it, replaying it on chosen models). A replay is one
 * request that answers once every model has, so `replaying` holds the
 * dialog's Replay button until then.
 */
export function useSavedCases(pushToast: PushToast, confirm: Confirm) {
  const [open, setOpen] = useState(false);
  const [list, setList] = useState<CaseSummary[]>([]);
  const [loading, setLoading] = useState(false);
  const [current, setCurrent] = useState<SavedCase | null>(null);
  const [replaying, setReplaying] = useState(false);
  // The turn being saved (its reply's node id), so its button can say so.
  const [saving, setSaving] = useState<string | null>(null);
  // Only the newest case request's answer is applied: opening another case
  // while one loads must not show the first.
  const opened = useRef(0);

  const refresh = useCallback(async () => {
    setLoading(true);
    try {
      setList(await api.listCases());
    } catch (e) {
      pushToast(errorMessage(e, "Couldn't load the saved cases"), "error");
    } finally {
      setLoading(false);
    }
  }, [pushToast]);

  const show = useCallback(() => {
    setOpen(true);
    setCurrent(null);
    void refresh();
  }, [refresh]);

  const close = useCallback(() => setOpen(false), []);
  const back = useCallback(() => {
    opened.current++;
    setCurrent(null);
    void refresh();
  }, [refresh]);

  const openCase = useCallback(
    async (caseId: string) => {
      const request = ++opened.current;
      try {
        const loaded = await api.fetchCase(caseId);
        if (request === opened.current) setCurrent(loaded);
      } catch (e) {
        pushToast(errorMessage(e, "Couldn't open the case"), "error");
      }
    },
    [pushToast],
  );

  const save = useCallback(
    async (threadId: string, turn: string) => {
      setSaving(turn);
      try {
        const saved = await api.saveCase(threadId, turn);
        pushToast(
          `Saved "${saved.title}". Replay it on other models from Saved cases in the sidebar.`,
          "success",
          "Case saved",
        );
        setList((prev) => [
          {
            case_id: saved.case_id,
            title: saved.title,
            question: saved.question,
            created_at: saved.created_at,
            source_thread_id: saved.source_thread_id,
            models: saved.answers.map((a) => a.model),
            model_names: saved.answers.map((a) => a.model_name),
            voted: !!saved.vote,
            replay_count: 0,
            last_replayed_at: null,
          },
          ...prev.filter((c) => c.case_id !== saved.case_id),
        ]);
      } catch (e) {
        pushToast(errorMessage(e, "Couldn't save the case"), "error");
      } finally {
        setSaving(null);
      }
    },
    [pushToast],
  );

  const replay = useCallback(
    async (models: string[]) => {
      if (!current || replaying || !models.length) return;
      const caseId = current.case_id;
      setReplaying(true);
      try {
        const result = await api.replayCase(caseId, models);
        const failed = result.results.filter((r) => r.error).length;
        const cost = result.total ? formatCost(result.total.cost_usd) : "price unknown";
        pushToast(
          `${result.results.length - failed} of ${result.results.length} answered · ${cost}`,
          failed ? "error" : "success",
          "Replay finished",
        );
        const request = ++opened.current;
        const reloaded = await api.fetchCase(caseId);
        if (request === opened.current) setCurrent(reloaded);
      } catch (e) {
        pushToast(errorMessage(e, "Couldn't replay the case"), "error");
      } finally {
        setReplaying(false);
      }
    },
    [current, replaying, pushToast],
  );

  const remove = useCallback(
    async (caseId: string, title: string) => {
      const ok = await confirm(
        "Delete this case?",
        `"${title}" and the record of its replays will be deleted. The threads its replays ran in stay.`,
        { confirmLabel: "Delete" },
      );
      if (!ok) return;
      try {
        await api.deleteCase(caseId);
        setList((prev) => prev.filter((c) => c.case_id !== caseId));
        setCurrent((c) => (c?.case_id === caseId ? null : c));
      } catch (e) {
        pushToast(errorMessage(e, "Couldn't delete the case"), "error");
      }
    },
    [confirm, pushToast],
  );

  return useMemo(
    () => ({ open, list, loading, current, replaying, saving, show, close, back, openCase, save, replay, remove }),
    [open, list, loading, current, replaying, saving, show, close, back, openCase, save, replay, remove],
  );
}
