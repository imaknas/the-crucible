import { cardExcerpt, orderSiblings, turnSiblings } from "./arenaCompare";

const node = (id: string, model: string, label = "", preview?: string) => ({
  id,
  data: { label },
  metadata: { active_peer: model, preview },
});

describe("orderSiblings", () => {
  it("follows the selection, not the order the answers finished in", () => {
    const finished = [node("c1", "gemini"), node("c2", "claude"), node("c3", "luna"), node("c4", "sol")];
    const ordered = orderSiblings(finished, ["sol", "luna", "claude", "gemini"]);
    expect(ordered.map((n) => n.metadata.active_peer)).toEqual(["sol", "luna", "claude", "gemini"]);
  });

  it("puts models no longer selected last, oldest first", () => {
    const ordered = orderSiblings([node("c2", "old-b"), node("c1", "old-a"), node("c3", "sol")], ["sol"]);
    expect(ordered.map((n) => n.id)).toEqual(["c3", "c1", "c2"]);
  });
});

describe("cardExcerpt", () => {
  it("shows the longer excerpt rather than the 40-character label", () => {
    const long = "Use integers in the smallest unit, such as cents, because binary floating point...";
    expect(cardExcerpt(node("c", "m", "Use integers in the smallest unit, such...", long))).toBe(long);
  });

  it("falls back to the label for nodes without an excerpt", () => {
    expect(cardExcerpt(node("c", "m", "Short answer"))).toBe("Short answer");
  });
});

describe("turnSiblings", () => {
  const n = (id: string, extra: Record<string, unknown> = {}, type?: string) => ({
    id,
    type,
    data: { label: id },
    metadata: { role: "ai", active_peer: id, ...extra },
  });

  it("finds the replies sent together by their turn, across branches", () => {
    const nodes = [
      n("q1", { role: "user", turn_id: "t2" }),
      n("a", { turn_id: "t2" }),
      n("b", { turn_id: "t2" }),
      n("old", { turn_id: "t1" }),
      n("syn", { turn_id: "t2", kind: "synthesis" }),
    ];
    // a and b hang off different parents: each model continued its own branch.
    const edges = [
      { source: "pa", target: "a" },
      { source: "pb", target: "b" },
    ];
    expect(turnSiblings(nodes, edges, "a").map((x) => x.id)).toEqual(["a", "b"]);
  });

  it("falls back to shared parents for threads without turns", () => {
    const nodes = [n("a"), n("b"), n("c"), n("syn", {}, "synthesis")];
    const edges = [
      { source: "u", target: "a" },
      { source: "u", target: "b" },
      { source: "u", target: "syn" },
      { source: "x", target: "c" },
    ];
    expect(turnSiblings(nodes, edges, "b").map((x) => x.id)).toEqual(["a", "b"]);
  });

  it("has no siblings for a user message or an unknown node", () => {
    expect(turnSiblings([n("u", { role: "user" })], [], "u")).toEqual([]);
    expect(turnSiblings([], [], "x")).toEqual([]);
  });
});
