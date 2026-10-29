import { useCallback, useMemo } from "react";
import type { Toggles } from "@/lib/types";
import { useStoredValue, writeStoredValue } from "@/hooks/useStoredValue";

const STORAGE_KEY = "crucible_toggles";

export const DEFAULT_TOGGLES: Toggles = { use_rag: true, use_web_search: false };

/** Stored toggles over the defaults; a missing or malformed value keeps the default. */
export function parseToggles(raw: string | null): Toggles {
  if (!raw) return DEFAULT_TOGGLES;
  try {
    const value = JSON.parse(raw);
    return {
      use_rag: typeof value?.use_rag === "boolean" ? value.use_rag : DEFAULT_TOGGLES.use_rag,
      use_web_search:
        typeof value?.use_web_search === "boolean" ? value.use_web_search : DEFAULT_TOGGLES.use_web_search,
    };
  } catch {
    return DEFAULT_TOGGLES;
  }
}

/** The Control Panel's Parameters (document search, web search), persisted: a reload used to reset them. */
export function useToggles() {
  const raw = useStoredValue(STORAGE_KEY);
  const toggles = useMemo(() => parseToggles(raw), [raw]);
  const setToggles = useCallback(
    (next: Toggles | ((prev: Toggles) => Toggles)) => {
      const current = parseToggles(localStorageValue());
      writeStoredValue(STORAGE_KEY, JSON.stringify(typeof next === "function" ? next(current) : next));
    },
    [],
  );
  return { toggles, setToggles };
}

function localStorageValue(): string | null {
  try {
    return localStorage.getItem(STORAGE_KEY);
  } catch {
    return null;
  }
}
