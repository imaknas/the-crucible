import type { ModelFamily } from "@/lib/api";
import { modelFamilyColor } from "@/lib/colors";

/**
 * Limits the backend enforces, from GET /models (`limits`). These values are
 * only the fallback until the catalogue has loaded.
 */
export interface Limits {
  max_system_prompt_chars: number;
  max_debate_rounds: number;
  max_prompt_chars: number;
}

export const FALLBACK_LIMITS: Limits = {
  max_system_prompt_chars: 8000,
  max_debate_rounds: 10,
  max_prompt_chars: 100_000,
};

/** The backend's limits over the fallbacks; a missing or invalid value keeps the fallback. */
export function resolveLimits(limits: Partial<Limits> | null | undefined): Limits {
  const out = { ...FALLBACK_LIMITS };
  for (const key of Object.keys(out) as (keyof Limits)[]) {
    const v = limits?.[key];
    if (typeof v === "number" && v > 0) out[key] = v;
  }
  return out;
}

/** A model's family colour from the catalogue, else guessed from its id. */
export function catalogColor(modelId: string, families: ModelFamily[]): string {
  return families.find((f) => f.models.some((m) => m.id === modelId))?.color ?? modelFamilyColor(modelId);
}

/** Which API key a family needs: the catalogue's `env_key`, else the convention. */
export function familyEnvKey(family: Pick<ModelFamily, "key" | "env_key">): string {
  return family.env_key || `${family.key.toUpperCase()}_API_KEY`;
}
