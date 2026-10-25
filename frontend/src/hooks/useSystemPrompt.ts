import { useCallback } from "react";
import { useStoredValue, writeStoredValue } from "@/hooks/useStoredValue";

const STORAGE_KEY = "crucible_system_prompt";
/** Mirrors MAX_SYSTEM_PROMPT_CHARS in backend/app/services/context.py. */
export const MAX_SYSTEM_PROMPT_CHARS = 8000;

/**
 * The person's own system prompt, edited in the Control Panel and persisted.
 * `text` is what the field shows; `systemPrompt` is what requests carry:
 * the text, or null while it is blank (models then get no system prompt).
 */
export function useSystemPrompt() {
  const text = useStoredValue(STORAGE_KEY) ?? "";
  const setText = useCallback((value: string) => writeStoredValue(STORAGE_KEY, value || null), []);
  return { text, systemPrompt: text.trim() ? text : null, setText };
}
