/**
 * Moving around a big conversation tree, as pure functions over the tree's
 * nodes and edges: which nodes show when subtrees are collapsed or one is
 * hoisted, where an arrow key goes, and what has to open for a node (a
 * bookmark) to be seen. TreeCanvas and useTreeView only wire them up.
 */
import type { TreeEdge, TreeNode } from "@/lib/types";

export interface TreeShape {
  parent: Map<string, string>;
  children: Map<string, string[]>;
}

/** Parent and children by id; children keep the edges' order. */
export function treeShape(edges: Pick<TreeEdge, "source" | "target">[]): TreeShape {
  const parent = new Map<string, string>();
  const children = new Map<string, string[]>();
  for (const e of edges) {
    parent.set(e.target, e.source);
    children.set(e.source, [...(children.get(e.source) ?? []), e.target]);
  }
  return { parent, children };
}

/** Every node below `id` (not `id` itself). */
export function descendants(shape: TreeShape, id: string): string[] {
  const out: string[] = [];
  const stack = [...(shape.children.get(id) ?? [])];
  while (stack.length) {
    const next = stack.pop()!;
    out.push(next);
    stack.push(...(shape.children.get(next) ?? []));
  }
  return out;
}

/** `id`'s ancestors, nearest first. */
export function ancestors(shape: TreeShape, id: string): string[] {
  const out: string[] = [];
  for (let p = shape.parent.get(id); p !== undefined && !out.includes(p); p = shape.parent.get(p)) out.push(p);
  return out;
}

export interface VisibleTree<N, E> {
  nodes: N[];
  edges: E[];
  /** Collapsed node → how many messages it hides. */
  hidden: Map<string, number>;
}

/**
 * What the canvas draws: with `hoisted`, only that node and its subtree;
 * below a collapsed node, nothing (it says how much it hides). Positions are
 * kept, so collapsing never moves the rest of the tree.
 */
export function visibleTree<N extends Pick<TreeNode, "id">, E extends Pick<TreeEdge, "source" | "target">>(
  nodes: N[],
  edges: E[],
  collapsed: ReadonlySet<string>,
  hoisted: string | null,
): VisibleTree<N, E> {
  const shape = treeShape(edges);
  const ids = new Set(nodes.map((n) => n.id));
  const keep = new Set<string>(hoisted && ids.has(hoisted) ? [hoisted, ...descendants(shape, hoisted)] : ids);
  const hidden = new Map<string, number>();
  for (const id of collapsed) {
    if (!keep.has(id)) continue;
    const below = descendants(shape, id).filter((d) => keep.has(d));
    if (!below.length) continue;
    hidden.set(id, below.length);
    for (const d of below) keep.delete(d);
  }
  // A collapsed node inside another collapsed subtree is hidden too.
  for (const id of [...hidden.keys()]) if (!keep.has(id)) hidden.delete(id);
  return {
    nodes: nodes.filter((n) => keep.has(n.id)),
    edges: edges.filter((e) => keep.has(e.source) && keep.has(e.target)),
    hidden,
  };
}

export type TreeKey = "ArrowUp" | "ArrowDown" | "ArrowLeft" | "ArrowRight" | "Home";

/**
 * Where a key moves the focus: up to the parent, down to the first child,
 * left and right to the previous or next sibling (children of the same
 * parent, or of no parent), Home to the root. The same node when there is
 * nowhere to go. `nodes` and `edges` are what is shown.
 */
export function neighbor(
  nodes: Pick<TreeNode, "id">[],
  edges: Pick<TreeEdge, "source" | "target">[],
  current: string,
  key: TreeKey,
): string {
  const shape = treeShape(edges);
  const parent = shape.parent.get(current);
  switch (key) {
    case "ArrowUp":
      return parent ?? current;
    case "ArrowDown":
      return shape.children.get(current)?.[0] ?? current;
    case "Home":
      return [current, ...ancestors(shape, current)].pop() ?? current;
    case "ArrowLeft":
    case "ArrowRight": {
      const row =
        parent !== undefined
          ? (shape.children.get(parent) ?? [])
          : nodes.map((n) => n.id).filter((id) => !shape.parent.has(id));
      const at = row.indexOf(current);
      const next = row[at + (key === "ArrowLeft" ? -1 : 1)];
      return next ?? current;
    }
  }
}

/** What has to change for `id` to show: its collapsed ancestors open, and the hoist dropped unless it is inside. */
export function reveal(
  edges: Pick<TreeEdge, "source" | "target">[],
  collapsed: ReadonlySet<string>,
  hoisted: string | null,
  id: string,
): { collapsed: Set<string>; hoisted: string | null } {
  const above = ancestors(treeShape(edges), id);
  const open = new Set([...collapsed].filter((c) => !above.includes(c)));
  return { collapsed: open, hoisted: hoisted && hoisted !== id && !above.includes(hoisted) ? null : hoisted };
}

/** Bookmarked nodes in tree order, with what to call each. */
export function bookmarks(
  nodes: { id: string; data: { label?: string }; metadata?: { bookmarked?: boolean; name?: string | null } }[],
): { id: string; label: string }[] {
  return nodes
    .filter((n) => n.metadata?.bookmarked)
    .map((n) => ({ id: n.id, label: n.metadata?.name || n.data.label || "Message" }));
}
