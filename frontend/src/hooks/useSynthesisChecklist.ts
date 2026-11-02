import { useCallback, useState } from "react";
import type { SynthesisRequest } from "@/lib/synthesis";

type Synthesize = (ids: string[], model?: string | null, request?: SynthesisRequest) => void;

/**
 * A checklist synthesis takes two steps: the answers are split into parts
 * (ChecklistDialog asks the backend), the person ticks the ones to keep, then
 * the merge runs. Every other mode goes straight through.
 */
export function useSynthesisChecklist(synthesize: Synthesize) {
  const [pending, setPending] = useState<{ ids: string[]; model: string | null } | null>(null);

  const request = useCallback<Synthesize>(
    (ids, model = null, req = { mode: "merge" }) => {
      if (req.mode === "checklist" && !req.keep?.length) setPending({ ids, model });
      else synthesize(ids, model, req);
    },
    [synthesize],
  );

  const merge = useCallback(
    (keep: string[]) => {
      if (!pending) return;
      synthesize(pending.ids, pending.model, { mode: "checklist", keep });
      setPending(null);
    },
    [pending, synthesize],
  );

  return { request, checklist: pending, merge, close: useCallback(() => setPending(null), []) };
}
