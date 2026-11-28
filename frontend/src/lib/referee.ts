import type { ModelFamily } from "@/lib/api";
import type { TreeNode } from "@/lib/types";

/**
 * Who combines answers when the person names no one: the first of the
 * backend's `referee_models` (GET /models) from a provider that wrote none
 * of them and has a key, else the first answering model. A model that also
 * answered reads its own text among the others', and models favour text
 * they recognise as their own.
 *
 * The backend's copy is services/referee.default_synthesizer (the checklist
 * dialog and every CLI/MCP synthesis go through it); both test the same cases.
 */
export function defaultSynthesizer(
  answering: string[],
  families: (Pick<ModelFamily, "key" | "available"> & { models: { id: string }[] })[],
  referees: string[],
): string | null {
  const familyOf = (id: string) => families.find((f) => f.models.some((m) => m.id === id));
  const answered = new Set(answering.map((m) => familyOf(m)?.key).filter(Boolean));
  const outsider = referees.find((m) => {
    const family = familyOf(m);
    return !!family && family.available && !answered.has(family.key);
  });
  return outsider ?? answering[0] ?? null;
}

/** The models that wrote the answers at these tree nodes, in that order. */
export function answeringModels(ids: string[], nodes: TreeNode[]): string[] {
  return ids
    .map((id) => nodes.find((n) => n.id === id)?.metadata?.active_peer)
    .filter((m): m is string => !!m);
}
