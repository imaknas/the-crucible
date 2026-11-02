import { ancestors, bookmarks, descendants, neighbor, reveal, treeShape, visibleTree } from "./treeView";
import type { TreeNode } from "./types";

//        root
//         |
//         q
//       /   \
//      a     b
//      |
//      q2
//      |
//      a2
const ids = ["root", "q", "a", "b", "q2", "a2"];
const nodes = ids.map((id) => ({ id }));
const edges = [
  { source: "root", target: "q" },
  { source: "q", target: "a" },
  { source: "q", target: "b" },
  { source: "a", target: "q2" },
  { source: "q2", target: "a2" },
];

describe("tree shape", () => {
  it("knows each node's ancestors and descendants", () => {
    const shape = treeShape(edges);
    expect(descendants(shape, "q").sort()).toEqual(["a", "a2", "b", "q2"]);
    expect(ancestors(shape, "a2")).toEqual(["q2", "a", "q", "root"]);
  });
});

describe("visibleTree", () => {
  it("hides what a collapsed node holds and says how much", () => {
    const v = visibleTree(nodes, edges, new Set(["a"]), null);
    expect(v.nodes.map((n) => n.id)).toEqual(["root", "q", "a", "b"]);
    expect(v.edges).toHaveLength(3);
    expect(v.hidden.get("a")).toBe(2);
  });

  it("shows only a hoisted subtree, and a collapsed leaf hides nothing", () => {
    const v = visibleTree(nodes, edges, new Set(["b"]), "a");
    expect(v.nodes.map((n) => n.id)).toEqual(["a", "q2", "a2"]);
    expect(v.hidden.size).toBe(0);
  });

  it("drops a collapsed node that sits inside another collapsed subtree", () => {
    const v = visibleTree(nodes, edges, new Set(["q", "a"]), null);
    expect(v.nodes.map((n) => n.id)).toEqual(["root", "q"]);
    expect([...v.hidden]).toEqual([["q", 4]]);
  });

  it("ignores a hoist on a node the tree no longer has", () => {
    expect(visibleTree(nodes, edges, new Set(), "gone").nodes).toHaveLength(6);
  });
});

describe("neighbor", () => {
  it("moves to parent, first child, siblings and the root", () => {
    expect(neighbor(nodes, edges, "a", "ArrowUp")).toBe("q");
    expect(neighbor(nodes, edges, "q", "ArrowDown")).toBe("a");
    expect(neighbor(nodes, edges, "a", "ArrowRight")).toBe("b");
    expect(neighbor(nodes, edges, "b", "ArrowLeft")).toBe("a");
    expect(neighbor(nodes, edges, "a2", "Home")).toBe("root");
  });

  it("stays put where there is nowhere to go", () => {
    expect(neighbor(nodes, edges, "root", "ArrowUp")).toBe("root");
    expect(neighbor(nodes, edges, "b", "ArrowDown")).toBe("b");
    expect(neighbor(nodes, edges, "b", "ArrowRight")).toBe("b");
    expect(neighbor(nodes, edges, "root", "ArrowRight")).toBe("root");
  });
});

describe("reveal", () => {
  it("opens collapsed ancestors and drops a hoist the node is outside of", () => {
    const r = reveal(edges, new Set(["q", "b"]), "b", "a2");
    expect([...r.collapsed]).toEqual(["b"]);
    expect(r.hoisted).toBeNull();
    expect(reveal(edges, new Set(), "a", "a2").hoisted).toBe("a");
  });
});

describe("bookmarks", () => {
  it("lists bookmarked nodes by name, else their label", () => {
    const tree = [
      { id: "q", data: { label: "The question" }, position: { x: 0, y: 0 }, metadata: { bookmarked: true } },
      {
        id: "a",
        data: { label: "An answer" },
        position: { x: 0, y: 0 },
        metadata: { bookmarked: true, name: "Plan A" },
      },
      { id: "b", data: { label: "Other" }, position: { x: 0, y: 0 }, metadata: {} },
    ] as TreeNode[];
    expect(bookmarks(tree)).toEqual([
      { id: "q", label: "The question" },
      { id: "a", label: "Plan A" },
    ]);
  });
});
