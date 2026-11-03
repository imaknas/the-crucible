import { blindOrder, fnv1a, maskCards } from "./blind";
import type { TurnCard } from "./turns";

describe("blind order", () => {
  it("hashes like the backend", () => {
    // The same vectors are in backend/tests/test_votes.py.
    expect(fnv1a("")).toBe(0x811c9dc5);
    expect(fnv1a("a")).toBe(0xe40c292c);
    expect(blindOrder("turn-1", ["gpt-5.4", "claude-sonnet-5", "gemini-3.1-pro-preview"])).toEqual([
      "claude-sonnet-5",
      "gpt-5.4",
      "gemini-3.1-pro-preview",
    ]);
  });

  it("doesn't depend on the order the models answered in", () => {
    expect(blindOrder("t", ["a", "b", "c"])).toEqual(blindOrder("t", ["c", "a", "b"]));
  });
});

describe("maskCards", () => {
  const card = (model: string): TurnCard => ({
    key: model,
    model,
    id: `n-${model}`,
    label: model.toUpperCase(),
    color: "#10b981",
    text: "x",
    full: true,
    streaming: false,
    stopped: false,
    error: null,
    shown: false,
    metrics: { ttft_ms: 1, total_ms: 2 } as TurnCard["metrics"],
  });

  it("letters the cards in blind order and drops what names the model", () => {
    const masked = maskCards([card("gpt-5.4"), card("claude-sonnet-5")], "turn-1");
    expect(masked.map((c) => [c.model, c.label])).toEqual([
      ["claude-sonnet-5", "Answer A"],
      ["gpt-5.4", "Answer B"],
    ]);
    expect(masked.every((c) => c.color === null && c.metrics === null)).toBe(true);
  });
});
