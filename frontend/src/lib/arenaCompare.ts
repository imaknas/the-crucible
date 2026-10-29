/** The Arena compare cards: sibling answers to one prompt. */

interface SiblingNode {
  id: string;
  data?: { label?: string };
  metadata?: { active_peer?: string | null; preview?: string | null };
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
