import { useCallback, useMemo } from "react";
import type { DebateDefaults } from "@/lib/types";
import { useStoredValue, writeStoredValue } from "@/hooks/useStoredValue";

const STORAGE_KEY = "crucible_debate_defaults";

/** The backend refuses more rounds than this (services/debate.py MAX_ROUNDS). */
export const MAX_DEBATE_ROUNDS = 10;

export function clampRounds(value: number): number {
  return Math.max(1, Math.min(MAX_DEBATE_ROUNDS, Math.trunc(value) || 3));
}

export const DEFAULT_DEBATE_DEFAULTS: DebateDefaults = {
  max_rounds: 3,
  convergence_threshold: null,
  llm_judge: null,
  mode: "all",
  auto_synthesize: false,
  synthesizer_model: null,
};

/**
 * Debate defaults from the Control Panel, persisted in localStorage. The stored
 * copy is the source of truth, read through useSyncExternalStore rather than
 * hydrated with a mount effect.
 */
export function useDebateDefaults() {
  const stored = useStoredValue(STORAGE_KEY);
  const debateDefaults = useMemo<DebateDefaults>(() => {
    if (!stored) return DEFAULT_DEBATE_DEFAULTS;
    try {
      const merged = { ...DEFAULT_DEBATE_DEFAULTS, ...(JSON.parse(stored) as Partial<DebateDefaults>) };
      // A value saved while the limit was higher would be refused at start.
      return { ...merged, max_rounds: clampRounds(merged.max_rounds) };
    } catch {
      return DEFAULT_DEBATE_DEFAULTS;
    }
  }, [stored]);

  const setDebateDefaults = useCallback(
    (next: DebateDefaults | ((prev: DebateDefaults) => DebateDefaults)) => {
      const value = typeof next === "function" ? next(debateDefaults) : next;
      writeStoredValue(STORAGE_KEY, JSON.stringify(value));
    },
    [debateDefaults],
  );

  return { debateDefaults, setDebateDefaults };
}
