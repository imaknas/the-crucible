import {
  combineUsage,
  formatCost,
  formatMetrics,
  formatTurnTotal,
  formatUsage,
  metricsBreakdown,
  turnTotal,
  usageBreakdown,
  type ReplyMetrics,
  type UsageSummary,
} from "./metrics";

const one: ReplyMetrics = {
  ttft_ms: 1200,
  total_ms: 8400,
  input_tokens: 1234,
  output_tokens: 567,
  reasoning_tokens: 120,
  cached_input_tokens: 200,
  cost_usd: 0.0123,
};

describe("formatMetrics", () => {
  it("puts an answer on one readable line", () => {
    expect(formatMetrics(one)).toBe(
      "1.2 s to first token · 8.4 s total · 1,234 in / 567 out (120 reasoning) · $0.0123",
    );
  });

  it("says when the price is unknown instead of guessing one", () => {
    expect(formatMetrics({ ...one, cost_usd: null })).toMatch(
      /· price unknown$/,
    );
  });

  it("leaves out what wasn't recorded", () => {
    expect(formatMetrics({ ...one, ttft_ms: null, reasoning_tokens: 0 })).toBe(
      "8.4 s total · 1,234 in / 567 out · $0.0123",
    );
    // No usage: no tokens and no cost (not "price unknown": there is nothing to price).
    expect(
      formatMetrics({
        ...one,
        input_tokens: null,
        output_tokens: null,
        cost_usd: null,
      }),
    ).toBe("1.2 s to first token · 8.4 s total");
    expect(formatMetrics(null)).toBe("");
  });

  it("formats costs at a useful precision", () => {
    expect(formatCost(0)).toBe("$0");
    expect(formatCost(0.00012)).toBe("$0.0001");
    expect(formatCost(0.00001)).toBe("<$0.0001");
    expect(formatCost(1234.5)).toBe("$1,234.50");
  });
});

describe("metricsBreakdown", () => {
  it("lists every number exactly, cached and reasoning tokens as parts", () => {
    expect(metricsBreakdown(one)).toEqual([
      "Time to first token: 1.20 s",
      "Total time: 8.40 s",
      "Input tokens: 1,234 (200 read from cache)",
      "Output tokens: 567 (120 of them reasoning)",
      "Cost: $0.012300",
      "Times cover the model's own call.",
    ]);
    expect(metricsBreakdown({ ...one, cost_usd: null })).toContain(
      "Cost: unknown, no price is listed for this model",
    );
  });
});

describe("turnTotal", () => {
  const two: ReplyMetrics = {
    ...one,
    ttft_ms: 300,
    total_ms: 9100,
    reasoning_tokens: null,
    cost_usd: 0.02,
  };

  it("sums tokens and cost and keeps the slowest time", () => {
    const t = turnTotal([one, two, null])!;
    expect(t).toMatchObject({
      answers: 2,
      ttft_ms: 1200,
      total_ms: 9100,
      input_tokens: 2468,
      output_tokens: 1134,
      reasoning_tokens: 120,
      unpriced: 0,
    });
    expect(t.cost_usd).toBeCloseTo(0.0323);
    expect(formatTurnTotal(t)).toBe(
      "Total · slowest 9.1 s · 2,468 in / 1,134 out (120 reasoning) · $0.0323",
    );
    expect(metricsBreakdown(t)).toContain("Over 2 answers");
  });

  it("never shows a total with an unpriced answer as complete", () => {
    const t = turnTotal([one, { ...two, cost_usd: null }])!;
    expect(t.unpriced).toBe(1);
    expect(formatTurnTotal(t)).toMatch(/\$0\.0123 \+ 1 price unknown$/);
    expect(metricsBreakdown(t)).toContain(
      "Cost: $0.012300, not counting 1 answer without a known price",
    );
    expect(formatTurnTotal(turnTotal([{ ...one, cost_usd: null }]))).toMatch(
      /· price unknown$/,
    );
  });

  it("is nothing when no answer has metrics", () => {
    expect(turnTotal([null, undefined])).toBeNull();
    expect(formatTurnTotal(null)).toBe("");
  });
});

describe("the calls made for an answer", () => {
  const helpers: UsageSummary = {
    calls: 2,
    kinds: ["recall", "summary"],
    input_tokens: 4000,
    output_tokens: 200,
    reasoning_tokens: 0,
    cached_input_tokens: 0,
    cost_usd: 0.002,
    unpriced: 0,
  };
  const reply: ReplyMetrics = { ...one, helpers };

  it("are named beside the answer's own numbers, not added to them", () => {
    expect(formatMetrics(reply)).toMatch(
      /· \$0\.0123 · \+ \$0\.0020 for 2 other calls \(recall, summary\)$/,
    );
    expect(metricsBreakdown(reply)).toContain(
      "Not counted above: $0.0020 for 2 other calls (recall, summary), 4,000 in / 200 out",
    );
  });

  it("are in a turn's total, as the backend's turn_total counts them", () => {
    const judge: UsageSummary = {
      ...helpers,
      calls: 1,
      kinds: ["agreement judge"],
      cost_usd: null,
      unpriced: 1,
    };
    const t = turnTotal([reply, one], [judge])!;
    expect(t.input_tokens).toBe(1234 * 2 + 4000 + 4000);
    expect(t.cost_usd).toBeCloseTo(0.0123 * 2 + 0.002);
    expect(t.unpriced).toBe(1);
    expect(t.helpers).toMatchObject({
      calls: 3,
      kinds: ["agreement judge", "recall", "summary"],
    });
    expect(formatTurnTotal(t)).toContain(
      "incl. $0.0020 + 1 price unknown for 3 other calls",
    );
    // Only extra calls, no answers: still a total.
    expect(turnTotal([], [helpers])).toMatchObject({
      answers: 0,
      cost_usd: 0.002,
    });
  });

  it("read on their own for an operation that is only such calls", () => {
    expect(formatUsage(helpers)).toBe("2 calls · 4,000 in / 200 out · $0.0020");
    expect(
      formatUsage({ ...helpers, calls: 1, cost_usd: null, unpriced: 1 }),
    ).toBe("1 call · 4,000 in / 200 out · price unknown");
    expect(formatUsage(null)).toBe("");
    expect(usageBreakdown(helpers)[0]).toBe("2 calls: recall, summary");
    expect(combineUsage([helpers, null, helpers])).toMatchObject({
      calls: 4,
      input_tokens: 8000,
      cost_usd: 0.004,
    });
  });
});
