import type { ModelFamily } from "@/lib/api";

export interface SelectionDefaults {
  default_model?: string | null;
  default_arena_models?: string[] | null;
}

/** Stored selections are a JSON list of model ids; anything else reads as none. */
export function parseStoredSelection(raw: string | null): string[] {
  if (!raw) return [];
  try {
    const value = JSON.parse(raw);
    return Array.isArray(value) ? value.filter((v): v is string => typeof v === "string") : [];
  } catch {
    return [];
  }
}

/**
 * The arena's selection: what was picked last (persisted), keeping only
 * models still offered by a family with a key; when nothing usable is left,
 * the backend's default arena (the same filter), else its default model.
 *
 * It used to start from `default_model` alone on every load, so Arena began
 * with one model and every reload dropped what had been picked.
 */
export function resolveSelection(
  stored: string[],
  families: ModelFamily[],
  defaults: SelectionDefaults,
): string[] {
  const usable = new Set(families.filter((f) => f.available).flatMap((f) => f.models.map((m) => m.id)));
  const kept = [...new Set(stored)].filter((id) => usable.has(id));
  if (kept.length) return kept;
  const arena = (defaults.default_arena_models ?? []).filter((id) => usable.has(id));
  if (arena.length) return arena;
  return defaults.default_model ? [defaults.default_model] : [];
}
