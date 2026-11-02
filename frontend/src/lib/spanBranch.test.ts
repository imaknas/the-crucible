import { QUOTE_MAX_CHARS, quoteForBranch, replyNodeAt } from "./spanBranch";
import type { TranscriptItem, TurnCard } from "./turns";

const card = (over: Partial<TurnCard>): TurnCard => ({
  key: "gpt-a",
  model: "gpt-a",
  id: "n-a",
  label: null,
  color: null,
  text: "x",
  full: true,
  streaming: false,
  stopped: false,
  error: null,
  shown: true,
  metrics: null,
  ...over,
});

const items: TranscriptItem[] = [
  { kind: "message", key: "u1", index: 0, msg: { id: "u1", role: "user", content: "Q", checkpoint_id: "u1" } },
  {
    kind: "turn",
    key: "turn-t1",
    index: 1,
    live: false,
    cards: [card({}), card({ key: "claude-b", model: "claude-b", id: "n-b", streaming: true })],
  },
  { kind: "message", key: "a2", index: 2, msg: { id: "a2", role: "assistant", content: "A", checkpoint_id: "a2" } },
  {
    kind: "message",
    key: "s1",
    index: 3,
    msg: { id: "s1", role: "assistant", content: "S", checkpoint_id: "s1", kind: "debate" },
  },
];

describe("replyNodeAt", () => {
  it("finds a finished card's node and a reply bubble's node", () => {
    expect(replyNodeAt(items, "turn-t1", "gpt-a")).toBe("n-a");
    expect(replyNodeAt(items, null, "a2")).toBe("a2");
  });

  it("refuses a streaming card, a person's message, a debate record and text outside replies", () => {
    expect(replyNodeAt(items, "turn-t1", "claude-b")).toBeNull();
    expect(replyNodeAt(items, null, "u1")).toBeNull();
    expect(replyNodeAt(items, null, "s1")).toBeNull();
    expect(replyNodeAt(items, null, null)).toBeNull();
    expect(replyNodeAt(items, "turn-gone", "gpt-a")).toBeNull();
  });
});

describe("quoteForBranch", () => {
  it("quotes every line and leaves room to write", () => {
    expect(quoteForBranch("  The ledger needs Postgres.\n\n\n\nBecause of joins. ")).toBe(
      "> The ledger needs Postgres.\n>\n> Because of joins.\n\n",
    );
  });

  it("cuts a long selection", () => {
    const quote = quoteForBranch("x".repeat(QUOTE_MAX_CHARS + 50));
    expect(quote.length).toBeLessThan(QUOTE_MAX_CHARS + 10);
    expect(quote).toContain("…");
  });
});
