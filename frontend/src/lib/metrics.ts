/**
 * What an answer took: time to first token, total time, tokens and cost.
 *
 * The backend sends one `metrics` object per reply (stream_end, path
 * messages, tree node metadata; services/metrics.py), or null for a reply
 * that recorded none (one written before metrics existed). Reasoning and
 * cached tokens are part of output and input, never added to them.
 * `cost_usd` null means the model has no known price: shown as "price
 * unknown", never guessed.
 */

export interface ReplyMetrics {
  ttft_ms: number | null;
  total_ms: number | null;
  input_tokens: number | null;
  output_tokens: number | null;
  reasoning_tokens: number | null;
  cached_input_tokens: number | null;
  cost_usd: number | null;
}

/** A turn's answers together: tokens and cost summed, times the slowest. */
export interface TurnMetrics extends ReplyMetrics {
  /** Answers with metrics. */
  answers: number;
  /** Answers with tokens but no known price: `cost_usd` leaves them out. */
  unpriced: number;
}

const count = (n: number) => n.toLocaleString("en-US");
const seconds = (ms: number, digits = 1) => `${(ms / 1000).toFixed(digits)} s`;

export function formatCost(cost: number | null): string {
  if (cost === null) return "price unknown";
  if (cost === 0) return "$0";
  // Four decimals would round a real cost to "$0.0000".
  if (cost < 0.0001) return "<$0.0001";
  return cost < 1
    ? `$${cost.toFixed(4)}`
    : `$${cost.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
}

function hasTokens(m: ReplyMetrics): boolean {
  return m.input_tokens !== null && m.output_tokens !== null;
}

function tokens(m: ReplyMetrics): string {
  const reasoning = m.reasoning_tokens
    ? ` (${count(m.reasoning_tokens)} reasoning)`
    : "";
  return `${count(m.input_tokens ?? 0)} in / ${count(m.output_tokens ?? 0)} out${reasoning}`;
}

function cost(m: ReplyMetrics | TurnMetrics): string {
  const unpriced = "unpriced" in m ? m.unpriced : 0;
  if (unpriced && m.cost_usd !== null)
    return `${formatCost(m.cost_usd)} + ${unpriced} price unknown`;
  return formatCost(m.cost_usd);
}

/** One answer on one line: "1.2 s to first token · 8.4 s · 1,234 in / 567 out (120 reasoning) · $0.0123". */
export function formatMetrics(m: ReplyMetrics | null | undefined): string {
  if (!m) return "";
  const parts: string[] = [];
  if (m.ttft_ms !== null) parts.push(`${seconds(m.ttft_ms)} to first token`);
  if (m.total_ms !== null) parts.push(seconds(m.total_ms));
  if (hasTokens(m)) parts.push(tokens(m), cost(m));
  return parts.join(" · ");
}

/** Every number, one per line, for the tooltip. */
export function metricsBreakdown(m: ReplyMetrics | TurnMetrics): string[] {
  const turn = "answers" in m;
  const lines: string[] = [];
  if (m.ttft_ms !== null)
    lines.push(
      `${turn ? "Slowest time" : "Time"} to first token: ${seconds(m.ttft_ms, 2)}`,
    );
  if (m.total_ms !== null)
    lines.push(
      `${turn ? "Slowest total time" : "Total time"}: ${seconds(m.total_ms, 2)}`,
    );
  if (m.input_tokens !== null) {
    const cached = m.cached_input_tokens
      ? ` (${count(m.cached_input_tokens)} read from cache)`
      : "";
    lines.push(`Input tokens: ${count(m.input_tokens)}${cached}`);
  }
  if (m.output_tokens !== null) {
    const reasoning = m.reasoning_tokens
      ? ` (${count(m.reasoning_tokens)} of them reasoning)`
      : "";
    lines.push(`Output tokens: ${count(m.output_tokens)}${reasoning}`);
  }
  if (hasTokens(m)) {
    const exact = m.cost_usd === null ? null : `$${m.cost_usd.toFixed(6)}`;
    if (turn && m.unpriced) {
      lines.push(
        `Cost: ${exact ?? "unknown"}, not counting ${m.unpriced} answer${m.unpriced > 1 ? "s" : ""} without a known price`,
      );
    } else {
      lines.push(
        exact
          ? `Cost: ${exact}`
          : "Cost: unknown, no price is listed for this model",
      );
    }
  }
  if (turn) lines.push(`Over ${m.answers} answer${m.answers > 1 ? "s" : ""}`);
  lines.push("Times cover the model's own call.");
  return lines;
}

const sum = (values: (number | null)[]) => {
  const known = values.filter(
    (v): v is number => v !== null && v !== undefined,
  );
  return known.length ? known.reduce((a, b) => a + b, 0) : null;
};
const max = (values: (number | null)[]) => {
  const known = values.filter(
    (v): v is number => v !== null && v !== undefined,
  );
  return known.length ? Math.max(...known) : null;
};

/** A turn's total, or null when no answer has metrics. */
export function turnTotal(
  metrics: (ReplyMetrics | null | undefined)[],
): TurnMetrics | null {
  const known = metrics.filter((m): m is ReplyMetrics => !!m);
  if (!known.length) return null;
  const priced = known.filter((m) => m.cost_usd !== null);
  return {
    answers: known.length,
    ttft_ms: max(known.map((m) => m.ttft_ms)),
    total_ms: max(known.map((m) => m.total_ms)),
    input_tokens: sum(known.map((m) => m.input_tokens)),
    output_tokens: sum(known.map((m) => m.output_tokens)),
    reasoning_tokens: sum(known.map((m) => m.reasoning_tokens)),
    cached_input_tokens: sum(known.map((m) => m.cached_input_tokens)),
    cost_usd: priced.length
      ? priced.reduce((a, m) => a + (m.cost_usd as number), 0)
      : null,
    unpriced: known.filter((m) => hasTokens(m) && m.cost_usd === null).length,
  };
}

/** The turn's line: "Total · slowest 9.1 s · 2,468 in / 1,134 out · $0.0246". */
export function formatTurnTotal(t: TurnMetrics | null): string {
  if (!t) return "";
  const parts = ["Total"];
  if (t.total_ms !== null) parts.push(`slowest ${seconds(t.total_ms)}`);
  if (hasTokens(t)) parts.push(tokens(t), cost(t));
  return parts.join(" · ");
}
