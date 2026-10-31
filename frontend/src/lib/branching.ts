import type { TreeNode } from "@/lib/types";

/**
 * Which checkpoint the next message branches from, as the composer shows it.
 *
 * Branching used to be invisible: whatever node you last clicked silently
 * became the parent of the next message. The composer now names it, and
 * offers a way back to the latest turn when you are replying from elsewhere.
 *
 * "Latest" is not a node: it is the absence of a choice. The backend then
 * continues every model from its own reply in the latest turn (and a model
 * that has none there from the latest answer), so a three-model turn
 * followed by Send is three parallel conversations. The chip shows the
 * thread's head (`headId`, the answered head GET /history reports) to say
 * where the conversation stands.
 */
export interface BranchPoint {
  /** The node shown on the chip: the chosen node, else the thread's head. */
  node: TreeNode;
  /** Short text for the chip. */
  preview: string;
  /** Nothing was chosen: the next message continues the latest turn. */
  isLatest: boolean;
}

const PREVIEW_CHARS = 60;

function isMessageNode(n: TreeNode) {
  return n.metadata?.role === "user" || n.metadata?.role === "ai";
}

export function branchPoint(nodes: TreeNode[], chosenId: string | null, headId: string | null): BranchPoint | null {
  const id = chosenId ?? headId;
  if (!id) return null;
  const node = nodes.find((n) => n.id === id);
  if (!node || !isMessageNode(node)) return null;
  const text = (node.metadata?.preview || node.data.label || "").replace(/\s+/g, " ").trim();
  return {
    node,
    preview: text.length > PREVIEW_CHARS ? `${text.slice(0, PREVIEW_CHARS - 1)}…` : text || "Start",
    isLatest: chosenId === null,
  };
}
