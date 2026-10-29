import { cardExcerpt, orderSiblings } from "./arenaCompare";

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
