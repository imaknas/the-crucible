/** The Arena compare cards: the other models' replies to the same message. */

interface SiblingNode {
  id: string;
  type?: string;
  data?: { label?: string };
  metadata?: {
    role?: string;
    active_peer?: string | null;
    preview?: string | null;
    turn_id?: string | null;
    kind?: string | null;
  };
}

interface Edge {
  source: string;
  target: string;
}

/** A synthesis is a resolution of the answers, not one more competitor. */
export function isSynthesisNode(node: SiblingNode | undefined): boolean {
  return node?.type === "synthesis" || node?.metadata?.kind === "synthesis";
}

/**
 * The replies sent together with the one shown, for the compare cards.
 *
 * Every model now continues from its own previous reply, so the replies to
 * one message sit on different branches: they are found by their shared
 * `turn_id`. Threads written before turns were recorded have none; their
 * replies to one message share a parent, as before.
 */
export function turnSiblings<T extends SiblingNode>(nodes: T[], edges: Edge[], activeId: string | null): T[] {
  const active = nodes.find((n) => n.id === activeId);
  if (!active || active.metadata?.role !== "ai") return [];
  const turn = active.metadata?.turn_id;
  if (turn) {
    return nodes.filter((n) => n.metadata?.turn_id === turn && n.metadata?.role === "ai" && !isSynthesisNode(n));
  }
  const parentId = edges.find((e) => e.target === active.id)?.source;
  if (!parentId) return [];
  const children = new Set(edges.filter((e) => e.source === parentId).map((e) => e.target));
  return nodes.filter((n) => children.has(n.id) && !isSynthesisNode(n));
}

/**
 * Cards in the order the models are selected (the order they were asked
 * in); models no longer selected follow, oldest answer first. They used to
 * come in checkpoint order, which is roughly the order the answers
 * finished in: fastest model first, the reverse of the selection.
 */
export function orderSiblings<T extends SiblingNode>(siblings: T[], selectedModels: string[]): T[] {
  const rank = (node: T) => {
    const i = selectedModels.indexOf(node.metadata?.active_peer ?? "");
    return i < 0 ? selectedModels.length : i;
  };
  return [...siblings].sort((a, b) => rank(a) - rank(b) || a.id.localeCompare(b.id));
}

/**
 * What a card shows of its answer: the node's longer excerpt (about 400
 * characters, ending in "..." when cut). The 40-character tree label cut
 * answers mid-word, and a ">50 characters" check meant to add the ellipsis
 * could never be true of it.
 */
export function cardExcerpt(node: SiblingNode): string {
  return node.metadata?.preview || node.data?.label || "";
}
