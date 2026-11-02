import {
  formatCost,
  formatMetrics,
  formatTurnTotal,
  metricsBreakdown,
  turnTotal,
  type ReplyMetrics,
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
      "1.2 s to first token · 8.4 s · 1,234 in / 567 out (120 reasoning) · $0.0123",
    );
  });

  it("says when the price is unknown instead of guessing one", () => {
    expect(formatMetrics({ ...one, cost_usd: null })).toMatch(
      /· price unknown$/,
    );
  });

  it("leaves out what wasn't recorded", () => {
    expect(formatMetrics({ ...one, ttft_ms: null, reasoning_tokens: 0 })).toBe(
      "8.4 s · 1,234 in / 567 out · $0.0123",
    );
    // No usage: no tokens and no cost (not "price unknown": there is nothing to price).
    expect(
      formatMetrics({
        ...one,
        input_tokens: null,
        output_tokens: null,
        cost_usd: null,
      }),
    ).toBe("1.2 s to first token · 8.4 s");
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
