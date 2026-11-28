import { useCallback } from "react";
import { useStoredValue, writeStoredValue } from "@/hooks/useStoredValue";

const STORAGE_KEY = "crucible_reasoning_effort";

/** The persisted reasoning-effort choice ("" = each model's default; lib/effort). */
export function useReasoningEffort() {
  const choice = useStoredValue(STORAGE_KEY) ?? "";
  const setChoice = useCallback((value: string) => writeStoredValue(STORAGE_KEY, value || null), []);
  return { choice, setChoice };
}
