import {
  budgetShare,
  formatTokens,
  inheritDetails,
  inheritLine,
  replyContextNote,
  tightest,
  type NextTurnContext,
} from "./context";

const row = (over: Partial<NextTurnContext> = {}): NextTurnContext => ({
  model: "gpt-5.4",
  tokens: 3400,
  history_tokens: 3400,
  messages: 12,
  summarized: false,
  from_summary: false,
  summarizes_next: false,
  soft_limit: 100_000,
  context_window: 272_000,
  ...over,
});

describe("next turn context", () => {
  it("formats approximate token counts", () => {
    expect(formatTokens(120)).toBe("~120");
    expect(formatTokens(3400)).toBe("~3.4k");
    expect(formatTokens(3000)).toBe("~3k");
    expect(formatTokens(140_000)).toBe("~140k");
    expect(formatTokens(1_000_000)).toBe("~1M");
  });

  it("speaks for the model whose budget fills most", () => {
    const small = row({ model: "claude-sonnet-5", soft_limit: 10_000 });
    expect(tightest([row(), small])?.model).toBe("claude-sonnet-5");
    expect(budgetShare([row(), small])).toBeCloseTo(0.34);
    expect(tightest([])).toBeNull();
  });

  it("says what the next turn inherits", () => {
    expect(inheritLine([row()])).toBe("12 messages · ~3.4k tokens");
    expect(inheritLine([row({ from_summary: true })])).toBe("12 messages · ~3.4k tokens · from a summary");
    expect(inheritLine([row({ from_summary: true }), row({ summarizes_next: true })])).toContain("summarizes first");
    expect(inheritLine([row({ messages: 0, tokens: 0 })])).toBe("no earlier messages");
    expect(inheritLine([])).toBeNull();
  });

  it("details each model by its display name", () => {
    const [line] = inheritDetails([row({ from_summary: true, summarized: true })], () => "GPT-5.4");
    expect(line).toBe(
      "GPT-5.4: ~3.4k of ~100k tokens before summarizing (3%), answers from the summary and the latest messages",
    );
  });
});

describe("a reply's context note", () => {
  const ctx = {
    tokens: 900,
    soft_limit: 1000,
    context_window: null,
    recalled: [],
  };

  it("says nothing for a reply written from the whole history", () => {
    expect(replyContextNote({ ...ctx, pruned: false })).toBeNull();
    expect(replyContextNote(null)).toBeNull();
  });

  it("names the summary and what recall brought back", () => {
    expect(replyContextNote({ ...ctx, pruned: true, kept_verbatim: 5 })).toBe(
      "Written from the summary and 5 recent messages",
    );
    expect(
      replyContextNote({
        ...ctx,
        pruned: true,
        kept_verbatim: 1,
        recalled: [{ role: "user", excerpt: "budget" }],
      }),
    ).toBe("Written from the summary and 1 recent message; recall brought back 1 earlier message");
    expect(
      replyContextNote({
        ...ctx,
        pruned: false,
        recalled: [
          { role: "user", excerpt: "a" },
          { role: "assistant", excerpt: "b" },
        ],
      }),
    ).toBe("Recall brought back 2 earlier messages");
  });
});
