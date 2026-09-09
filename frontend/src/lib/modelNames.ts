import type { ModelFamily } from "./api";

/**
 * Human-facing label for a model ID, resolved from the catalogue that
 * `GET /models` returns.
 *
 * The backend already labels every node it builds; this covers the frontend's
 * own optimistic nodes, which are created before the tree is refetched.
 */
export function modelDisplayName(
  modelId: string,
  families: ModelFamily[] | undefined,
): string {
  if (!families) return modelId;
  for (const family of families) {
    for (const model of family.models) {
      if (model.id === modelId) return model.name;
    }
  }
  return modelId;
}
