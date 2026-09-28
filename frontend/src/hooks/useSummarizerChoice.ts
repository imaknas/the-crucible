import { useCallback, useMemo } from "react";
import type { ModelFamily } from "@/lib/api";
import { useStoredValue, writeStoredValue } from "@/hooks/useStoredValue";

const STORAGE_KEY = "crucible_summarizer";

/** Models that can summarize: offered, not legacy, and from a family with a key. */
export function summarizerOptions(families: ModelFamily[]) {
  return families
    .filter((f) => f.available)
    .flatMap((f) => f.models.filter((m) => m.desc !== "Legacy").map((m) => ({ ...m, family: f })));
}

/**
 * Which model summarizes long history, chosen in the Control Panel and
 * persisted. `choice` is what was picked ("" = automatic, the backend's
 * default); `summarizer` is what requests carry: the choice while that model
 * is still usable, otherwise null, so a key removed later falls back to the
 * default instead of failing every summary.
 */
export function useSummarizerChoice(families: ModelFamily[]) {
  const choice = useStoredValue(STORAGE_KEY) ?? "";
  const summarizer = useMemo(
    () => (choice && summarizerOptions(families).some((m) => m.id === choice) ? choice : null),
    [choice, families],
  );
  const setChoice = useCallback((id: string) => writeStoredValue(STORAGE_KEY, id || null), []);
  return { choice, summarizer, setChoice };
}
