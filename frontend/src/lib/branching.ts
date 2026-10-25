import type { TreeNode } from "@/lib/types";

/**
 * Which checkpoint the next message branches from, as the composer shows it.
 *
 * Branching used to be invisible: whatever node you last clicked silently
 * became the parent of the next message. The composer now names it, and
 * offers a way back to the newest node when you are replying from elsewhere.
 */
export interface BranchPoint {
  /** The node the next message will be sent from. */
  node: TreeNode;
  /** Short text for the chip. */
  preview: string;
  /** The newest message node; reset target. */
  latestId: string;
  isLatest: boolean;
}

const PREVIEW_CHARS = 60;

function isMessageNode(n: TreeNode) {
  return n.metadata?.role === "user" || n.metadata?.role === "ai";
}

export function branchPoint(nodes: TreeNode[], activeId: string | null): BranchPoint | null {
  const messages = nodes.filter(isMessageNode);
  if (!activeId || messages.length === 0) return null;
  const node = nodes.find((n) => n.id === activeId);
  if (!node) return null;
  // Checkpoint ids are time-ordered, so the greatest is the newest.
  const latestId = messages.reduce((a, b) => (b.id > a.id ? b : a)).id;
  const text = (node.metadata?.preview || node.data.label || "").replace(/\s+/g, " ").trim();
  return {
    node,
    preview: text.length > PREVIEW_CHARS ? `${text.slice(0, PREVIEW_CHARS - 1)}…` : text || "Start",
    latestId,
    isLatest: node.id === latestId,
  };
}
