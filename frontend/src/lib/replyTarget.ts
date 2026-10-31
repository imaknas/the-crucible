import type { TreeNode } from "@/lib/types";

/**
 * Who answers the next message.
 *
 * Clicking a model's reply means "continue with that model", but that is a
 * choice about this conversation, not a setting: it used to overwrite the
 * Control Panel's selection, which is persisted, so one click left a
 * three-model arena as a single model on every later visit. The reply's
 * model is now kept beside the selection and only decides the next turns
 * while that reply is what you continue from.
 */

/** The model a clicked node continues with: its author, for a model's reply. */
export function replyModelOf(node: TreeNode | undefined): string | null {
  const meta = node?.metadata;
  if (meta?.role !== "ai" || meta.kind === "debate") return null;
  return meta.active_peer || null;
}

/**
 * The models the next message goes to: the clicked reply's model, unless
 * the person asked every selected model to answer from it.
 */
export function respondingModels(
  selected: string[],
  replyModel: string | null,
  askAll: boolean,
): string[] {
  return replyModel && !askAll ? [replyModel] : selected;
}

/** Whether asking all selected models would change who answers. */
export function canAskAll(
  selected: string[],
  replyModel: string | null,
): boolean {
  return !!replyModel && selected.some((m) => m !== replyModel);
}
