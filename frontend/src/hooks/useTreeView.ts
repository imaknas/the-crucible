import { useCallback, useMemo, useState } from "react";
import { useStoredValue, writeStoredValue } from "@/hooks/useStoredValue";
import { reveal } from "@/lib/treeView";
import type { TreeEdge } from "@/lib/types";

const EMPTY: string[] = [];

function parse(raw: string | null): string[] {
  try {
    const value = raw ? JSON.parse(raw) : [];
    return Array.isArray(value) ? value.filter((v): v is string => typeof v === "string") : [];
  } catch {
    return [];
  }
}

/**
 * How the tree is folded: which nodes are collapsed (persisted per thread,
 * so a big tree reopens as you left it) and which subtree is hoisted (shown
 * alone; forgotten on another thread). What is drawn follows from these
 * through lib/treeView.visibleTree.
 */
export function useTreeView(threadId: string | null) {
  const key = `crucible_collapsed:${threadId ?? ""}`;
  const raw = useStoredValue(key);
  const collapsedList = useMemo(() => (threadId ? parse(raw) : EMPTY), [threadId, raw]);
  const collapsed = useMemo(() => new Set(collapsedList), [collapsedList]);
  const [hoist, setHoist] = useState<{ threadId: string | null; id: string } | null>(null);
  const hoisted = hoist && hoist.threadId === threadId ? hoist.id : null;

  const write = useCallback(
    (next: Set<string>) => writeStoredValue(key, next.size ? JSON.stringify([...next]) : null),
    [key],
  );
  const setCollapsed = useCallback(
    (id: string, folded: boolean) => {
      if (!threadId) return;
      const next = new Set(collapsed);
      if (folded) next.add(id);
      else next.delete(id);
      write(next);
    },
    [threadId, collapsed, write],
  );
  const toggleCollapse = useCallback((id: string) => setCollapsed(id, !collapsed.has(id)), [collapsed, setCollapsed]);
  const hoistNode = useCallback((id: string | null) => setHoist(id ? { threadId, id } : null), [threadId]);
  /** Open whatever hides `id` (a bookmark you jump to). */
  const revealNode = useCallback(
    (edges: TreeEdge[], id: string) => {
      const next = reveal(edges, collapsed, hoisted, id);
      if (next.collapsed.size !== collapsed.size) write(next.collapsed);
      if (next.hoisted !== hoisted) setHoist(next.hoisted ? { threadId, id: next.hoisted } : null);
    },
    [collapsed, hoisted, threadId, write],
  );

  return { collapsed, hoisted, setCollapsed, toggleCollapse, hoistNode, revealNode };
}
