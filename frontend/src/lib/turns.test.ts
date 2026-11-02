import { buildTranscript, startLiveTurn, stopLiveTurn, synthesizableIds, updateLiveReply } from "./turns";
import type { Message, TreeNode } from "./types";

const node = (id: string, model: string, turn: string, extra: Partial<TreeNode> = {}): TreeNode => ({
  id,
  data: { label: id },
  position: { x: 0, y: 0 },
  metadata: { role: "ai", active_peer: model, turn_id: turn, preview: `${id} excerpt` },
  ...extra,
});
const q: Message = { id: "q", role: "user", content: "Q" };
const reply = (id: string, model: string, turn: string): Message => ({
  id,
  role: "assistant",
  content: `${model} whole`,
  model,
  checkpoint_id: id,
  turn_id: turn,
});

describe("live turns", () => {
  it("starts one streaming reply per model, in the order asked", () => {
    const t = startLiveTurn(["b", "a"], "k");
    expect(t.replies.map((r) => [r.model, r.streaming])).toEqual([
      ["b", true],
      ["a", true],
    ]);
  });

  it("takes the turn id from the first reply that has one, and ignores unknown models", () => {
    let t = startLiveTurn(["a", "b"], "k");
    t = updateLiveReply(t, "a", { turn_id: "t1", content: "x" });
    t = updateLiveReply(t, "zzz", { content: "y" });
    expect(t.turnId).toBe("t1");
    expect(t.replies[0].content).toBe("x");
  });

  it("Stop cuts off only what is still streaming", () => {
    let t = startLiveTurn(["a", "b"], "k");
    t = updateLiveReply(t, "a", { streaming: false, checkpoint_id: "n" });
    const stopped = stopLiveTurn(t)!;
    expect(stopped.replies.map((r) => !!r.stopped)).toEqual([false, true]);
    expect(stopLiveTurn(null)).toBeNull();
  });
});

describe("buildTranscript", () => {
  const nodes = [node("a1", "a", "t1"), node("b1", "b", "t1"), node("a0", "a", "t0")];

  it("turns a path reply with turn-mates into a grid with the path's reply whole", () => {
    const items = buildTranscript({ messages: [q, reply("a1", "a", "t1")], nodes, edges: [], selected: ["a", "b"], replyTexts: {}, live: null });
    expect(items.map((i) => i.kind)).toEqual(["message", "turn"]);
    const turn = items[1];
    if (turn.kind !== "turn") throw new Error();
    expect(turn.cards.map((c) => [c.model, c.full, c.shown, c.text])).toEqual([
      ["a", true, true, "a whole"],
      ["b", false, false, "b1 excerpt"],
    ]);
  });

  it("keeps a lone reply a bubble", () => {
    const items = buildTranscript({ messages: [q, reply("a0", "a", "t0")], nodes, edges: [], selected: ["a"], replyTexts: {}, live: null });
    expect(items.map((i) => i.kind)).toEqual(["message", "message"]);
  });

  it("puts the streaming turn after its question, then keeps its key once the path holds it", () => {
    let live = startLiveTurn(["a", "b"], "live-key");
    const streaming = buildTranscript({ messages: [q], nodes: [], edges: [], selected: ["a", "b"], replyTexts: {}, live });
    expect(streaming.at(-1)).toMatchObject({ kind: "turn", key: "live-key", live: true });

    live = updateLiveReply(updateLiveReply(live, "a", { turn_id: "t1", checkpoint_id: "a1", streaming: false }), "b", {
      checkpoint_id: "b1",
      streaming: false,
      content: "b streamed",
    });
    const settled = buildTranscript({
      messages: [q, reply("a1", "a", "t1")],
      nodes,
      edges: [],
      selected: ["a", "b"],
      replyTexts: { b1: "b streamed" },
      live,
    });
    expect(settled).toHaveLength(2);
    expect(settled[1]).toMatchObject({ kind: "turn", key: "live-key" });
    if (settled[1].kind !== "turn") throw new Error();
    expect(settled[1].cards.map((c) => [c.key, c.text, c.full])).toEqual([
      ["a", "a whole", true],
      ["b", "b streamed", true],
    ]);
  });

  it("keeps a failed model's card in the settled turn", () => {
    const live = updateLiveReply(
      updateLiveReply(startLiveTurn(["a", "b", "c"], "k"), "a", { turn_id: "t1", checkpoint_id: "a1", streaming: false }),
      "c",
      { streaming: false, error: "boom" },
    );
    const items = buildTranscript({ messages: [q, reply("a1", "a", "t1")], nodes, edges: [], selected: ["a", "b", "c"], replyTexts: {}, live });
    const turn = items[1];
    if (turn.kind !== "turn") throw new Error();
    expect(turn.cards.map((c) => [c.model, c.error])).toEqual([
      ["a", null],
      ["b", null],
      ["c", "boom"],
    ]);
    expect(synthesizableIds(turn.cards, nodes)).toEqual(["a1", "b1"]);
  });

  it("gives each card its metrics: live from stream_end, else the path's, else the tree node's", () => {
    const m = (cost: number) => ({
      ttft_ms: 1, total_ms: 2, input_tokens: 3, output_tokens: 4, reasoning_tokens: null, cached_input_tokens: null, cost_usd: cost,
    });
    const withMetrics = [
      node("a1", "a", "t1", { metadata: { role: "ai", active_peer: "a", turn_id: "t1", metrics: m(1) } }),
      node("b1", "b", "t1", { metadata: { role: "ai", active_peer: "b", turn_id: "t1", metrics: m(2) } }),
      node("c1", "c", "t1", { metadata: { role: "ai", active_peer: "c", turn_id: "t1" } }),
    ];
    const live = updateLiveReply(startLiveTurn(["a", "b", "c"], "k"), "c", { turn_id: "t1", checkpoint_id: "c1", streaming: false, metrics: m(3) });
    const items = buildTranscript({
      messages: [q, { ...reply("a1", "a", "t1"), metrics: m(9) }],
      nodes: withMetrics,
      edges: [],
      selected: ["a", "b", "c"],
      replyTexts: {},
      live,
    });
    const turn = items[1];
    if (turn.kind !== "turn") throw new Error();
    expect(turn.cards.map((c) => c.metrics?.cost_usd)).toEqual([9, 2, 3]);
    // An older turn without metrics: none, not zeros.
    const old = buildTranscript({ messages: [q, reply("a1", "a", "t1")], nodes, edges: [], selected: ["a", "b"], replyTexts: {}, live: null });
    if (old[1].kind !== "turn") throw new Error();
    expect(old[1].cards.map((c) => c.metrics)).toEqual([null, null]);
  });

  it("does not draw the latest turn under another branch the person opened", () => {
    const live = updateLiveReply(startLiveTurn(["a", "b"], "k"), "a", { turn_id: "t9", checkpoint_id: "z", streaming: false });
    const items = buildTranscript({ messages: [q, reply("a0", "a", "t0")], nodes, edges: [], selected: ["a"], replyTexts: {}, live });
    expect(items.every((i) => i.kind === "message")).toBe(true);
  });
});
