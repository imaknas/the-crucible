/**
 * Single source of truth for model family colours on the client.
 *
 * These values mirror FAMILY_META in backend/app/api/models.py. The backend
 * ships the resolved colour on every debate node (`metadata.model_color`), so
 * prefer that when it is available and fall back to this map only before the
 * first tree fetch has landed.
 */
export const FAMILY_COLORS = {
  openai: "#10b981",
  anthropic: "#f59e0b",
  google: "#8b5cf6",
  synthesis: "#8b5cf6",
  unknown: "#6366f1",
} as const;

export function modelFamilyColor(modelId: string | undefined | null): string {
  const m = (modelId || "").toLowerCase();
  if (m.includes("gpt") || m.includes("o1") || m.includes("o3"))
    return FAMILY_COLORS.openai;
  if (m.includes("claude")) return FAMILY_COLORS.anthropic;
  if (m.includes("gemini")) return FAMILY_COLORS.google;
  return FAMILY_COLORS.unknown;
}
