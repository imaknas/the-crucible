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

/** Whom a lone default model is compared with: its family's fast model, else another current one. */
const PARTNER_ORDER = ["Fast", "Balanced", "Flagship"];

function partnerFor(id: string, families: ModelFamily[]): string | null {
  const family = families.find((f) => f.available && f.models.some((m) => m.id === id));
  const others = (family?.models ?? []).filter((m) => m.id !== id && m.desc !== "Legacy");
  const rank = (desc: string | undefined) => {
    const i = PARTNER_ORDER.indexOf(desc ?? "");
    return i < 0 ? PARTNER_ORDER.length : i;
  };
  return [...others].sort((a, b) => rank(a.desc) - rank(b.desc))[0]?.id ?? null;
}

/**
 * The arena's selection: what was picked last (persisted), keeping only
 * models still offered by a family with a key; when nothing usable is left,
 * the backend's default arena (the same filter), else its default model,
 * else the first current model with a key. A default of one model is paired
 * with a second from its family: with one provider's key the app was a
 * single-model chat that never showed a comparison. With no key at all,
 * nothing is selected (the composer says to add one), rather than a model
 * that could only fail.
 *
 * It used to start from `default_model` alone on every load, so Arena began
 * with one model and every reload dropped what had been picked.
 */
export function resolveSelection(
  stored: string[],
  families: ModelFamily[],
  defaults: SelectionDefaults,
): string[] {
  // Before the catalogue loads, there is nothing to filter by.
  if (!families.length) return defaults.default_model ? [defaults.default_model] : [];
  const usable = new Set(families.filter((f) => f.available).flatMap((f) => f.models.map((m) => m.id)));
  if (!usable.size) return [];
  const kept = [...new Set(stored)].filter((id) => usable.has(id));
  if (kept.length) return kept;
  const arena = (defaults.default_arena_models ?? []).filter((id) => usable.has(id));
  if (!arena.length) {
    const first = defaults.default_model && usable.has(defaults.default_model)
      ? defaults.default_model
      : families.filter((f) => f.available).flatMap((f) => f.models).find((m) => m.desc !== "Legacy")?.id;
    if (first) arena.push(first);
  }
  if (arena.length === 1) {
    const partner = partnerFor(arena[0], families);
    if (partner) arena.push(partner);
  }
  return arena;
}
