import { useCallback, useMemo } from "react";
import type { DebateDefaults } from "@/lib/types";
import { useStoredValue, writeStoredValue } from "@/hooks/useStoredValue";
import { FALLBACK_LIMITS } from "@/lib/catalog";

const STORAGE_KEY = "crucible_debate_defaults";

/** Before GET /models answers: the backend's own limit (`limits.max_debate_rounds`) replaces it. */
export const MAX_DEBATE_ROUNDS = FALLBACK_LIMITS.max_debate_rounds;

/** Before GET /models answers: the backend's `limits.default_debate_rounds` replaces it. */
export const DEFAULT_DEBATE_ROUNDS = FALLBACK_LIMITS.default_debate_rounds;

export function clampRounds(value: number, max: number = MAX_DEBATE_ROUNDS): number {
  return Math.max(1, Math.min(max, Math.trunc(value) || DEFAULT_DEBATE_ROUNDS));
}

export const DEFAULT_DEBATE_DEFAULTS: DebateDefaults = {
  max_rounds: DEFAULT_DEBATE_ROUNDS,
  convergence_threshold: null,
  llm_judge: null,
  mode: "all",
  auto_synthesize: false,
  synthesizer_model: null,
  peer_labels: "anonymous",
};

/**
 * Debate defaults from the Control Panel, persisted in localStorage. The stored
 * copy is the source of truth, read through useSyncExternalStore rather than
 * hydrated with a mount effect.
 */
export function useDebateDefaults(maxRounds: number = MAX_DEBATE_ROUNDS, defaultRounds: number = DEFAULT_DEBATE_ROUNDS) {
  const stored = useStoredValue(STORAGE_KEY);
  const debateDefaults = useMemo<DebateDefaults>(() => {
    // The backend's recommended count, until the person saves their own.
    const base = { ...DEFAULT_DEBATE_DEFAULTS, max_rounds: clampRounds(defaultRounds, maxRounds) };
    if (!stored) return base;
    try {
      const merged = { ...base, ...(JSON.parse(stored) as Partial<DebateDefaults>) };
      // A value saved while the limit was higher would be refused at start.
      return { ...merged, max_rounds: clampRounds(merged.max_rounds, maxRounds) };
    } catch {
      return base;
    }
  }, [stored, maxRounds, defaultRounds]);

  const setDebateDefaults = useCallback(
    (next: DebateDefaults | ((prev: DebateDefaults) => DebateDefaults)) => {
      const value = typeof next === "function" ? next(debateDefaults) : next;
      writeStoredValue(STORAGE_KEY, JSON.stringify(value));
    },
    [debateDefaults],
  );

  return { debateDefaults, setDebateDefaults };
}
