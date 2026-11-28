/**
 * Reasoning effort: how hard the answering models reason. One choice per
 * run (GET /models `reasoning_efforts`, lowest first; "" = each model's
 * default), resolved by the backend per model against the levels that model
 * takes (llm/effort.py). A model without that level answers at its default,
 * and the turn says so.
 */
import type { ReplyEffort } from "@/lib/types";

export const EFFORT_LABELS: Record<string, string> = {
  low: "Low",
  medium: "Medium",
  high: "High",
  max: "Highest",
};

/** What a reply's metrics line says about its effort, or null at the default. */
export function effortLabel(effort: ReplyEffort | null | undefined): string | null {
  if (!effort?.level) return null;
  if (effort.choice === "max") return `highest effort (${effort.level})`;
  return `${effort.choice} effort`;
}

/**
 * Which of `models` won't get `choice`, and why: null efforts = not
 * verified yet, a list without it = the model has no such level.
 */
export function effortGaps(
  choice: string,
  models: { id: string; name: string; reasoning_efforts?: string[] | null }[],
): { unverified: string[]; lacking: string[] } {
  const unverified: string[] = [];
  const lacking: string[] = [];
  if (!choice) return { unverified, lacking };
  for (const m of models) {
    if (m.reasoning_efforts == null) unverified.push(m.name);
    else if (!m.reasoning_efforts.includes(choice)) lacking.push(m.name);
  }
  return { unverified, lacking };
}
