/**
 * What an answer took: time to first token, total time, tokens and cost.
 *
 * The backend sends one `metrics` object per reply (stream_end, path
 * messages, tree node metadata; services/metrics.py), or null for a reply
 * that recorded none (one written before metrics existed). Reasoning and
 * cached tokens are part of output and input, never added to them.
 * `cost_usd` null means the model has no known price: shown as "price
 * unknown", never guessed.
 *
 * A reply's own numbers are its answering call alone. `helpers` is the other
 * calls made for it (a history summary, document grading, recall); an
 * operation that is only such calls (peer review, a check, a debate's judge)
 * reports the same shape as `usage`. Only completed calls are counted.
 */

/** Model calls together (services/metrics.usage_summary). */
export interface UsageSummary {
  calls: number;
  /** What they were for: "summary", "recall", "document grading", … */
  kinds: string[];
  input_tokens: number;
  output_tokens: number;
  reasoning_tokens: number;
  cached_input_tokens: number;
  /** The priced calls' cost; null when none had a known price. */
  cost_usd: number | null;
  /** Calls with no known price, which cost_usd leaves out. */
  unpriced: number;
}

export interface ReplyMetrics {
  ttft_ms: number | null;
  total_ms: number | null;
  input_tokens: number | null;
  output_tokens: number | null;
  reasoning_tokens: number | null;
  cached_input_tokens: number | null;
  cost_usd: number | null;
  /** The other calls made for this reply; null (or absent, older payloads) for none. */
  helpers?: UsageSummary | null;
}

/**
 * A turn's answers together: tokens and cost summed, times the slowest.
 * Tokens and cost include every answer's helpers (and any extra calls, a
 * debate's judge), which `helpers` also sums on its own.
 */
export interface TurnMetrics extends ReplyMetrics {
  /** Answers with metrics. */
  answers: number;
  /** Answers and calls with tokens but no known price: `cost_usd` leaves them out. */
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

function usageCost(u: UsageSummary): string {
  if (u.cost_usd === null) return "price unknown";
  return u.unpriced
    ? `${formatCost(u.cost_usd)} + ${u.unpriced} price unknown`
    : formatCost(u.cost_usd);
}

const plural = (n: number, word: string) =>
  `${n} ${word}${n === 1 ? "" : "s"}`;

/** "$0.0012 for 3 other calls (summary, recall)". */
export function formatHelpers(u: UsageSummary): string {
  const kinds = u.kinds.length ? ` (${u.kinds.join(", ")})` : "";
  return `${usageCost(u)} for ${plural(u.calls, "other call")}${kinds}`;
}

/** Calls on their own: "2 calls · 1,234 in / 56 out · $0.0012". */
export function formatUsage(u: UsageSummary | null | undefined): string {
  if (!u) return "";
  return `${plural(u.calls, "call")} · ${count(u.input_tokens)} in / ${count(u.output_tokens)} out · ${usageCost(u)}`;
}

/** A usage summary's numbers, one per line, for a tooltip. */
export function usageBreakdown(u: UsageSummary): string[] {
  const cached = u.cached_input_tokens
    ? ` (${count(u.cached_input_tokens)} read from cache)`
    : "";
  const reasoning = u.reasoning_tokens
    ? ` (${count(u.reasoning_tokens)} of them reasoning)`
    : "";
  const exact = u.cost_usd === null ? "unknown" : `$${u.cost_usd.toFixed(6)}`;
  return [
    `${plural(u.calls, "call")}${u.kinds.length ? `: ${u.kinds.join(", ")}` : ""}`,
    `Input tokens: ${count(u.input_tokens)}${cached}`,
    `Output tokens: ${count(u.output_tokens)}${reasoning}`,
    u.unpriced
      ? `Cost: ${exact}, not counting ${plural(u.unpriced, "call")} without a known price`
      : `Cost: ${exact}`,
    "Completed calls only: a stopped or failed call reports nothing.",
  ];
}

/** One answer on one line: "1.2 s to first token · 8.4 s total · 1,234 in / 567 out (120 reasoning) · $0.0123". */
export function formatMetrics(m: ReplyMetrics | null | undefined): string {
  if (!m) return "";
  const parts: string[] = [];
  if (m.ttft_ms !== null) parts.push(`${seconds(m.ttft_ms)} to first token`);
  if (m.total_ms !== null) parts.push(`${seconds(m.total_ms)} total`);
  if (hasTokens(m)) parts.push(tokens(m), cost(m));
  if (m.helpers) parts.push(`+ ${formatHelpers(m.helpers)}`);
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
  if (m.helpers) {
    lines.push(
      turn
        ? `Includes ${formatHelpers(m.helpers)}`
        : `Not counted above: ${formatHelpers(m.helpers)}, ${count(m.helpers.input_tokens)} in / ${count(m.helpers.output_tokens)} out`,
    );
  }
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

type UsageCount =
  | "calls"
  | "input_tokens"
  | "output_tokens"
  | "reasoning_tokens"
  | "cached_input_tokens"
  | "unpriced";

/** Several usage summaries as one, or null for none. */
export function combineUsage(
  usages: (UsageSummary | null | undefined)[],
): UsageSummary | null {
  const known = usages.filter((u): u is UsageSummary => !!u);
  if (!known.length) return null;
  const add = (key: UsageCount) =>
    known.reduce((a, u) => a + (u[key] ?? 0), 0);
  const costs = known
    .map((u) => u.cost_usd)
    .filter((c): c is number => c !== null);
  return {
    calls: add("calls"),
    kinds: [...new Set(known.flatMap((u) => u.kinds))].sort(),
    input_tokens: add("input_tokens"),
    output_tokens: add("output_tokens"),
    reasoning_tokens: add("reasoning_tokens"),
    cached_input_tokens: add("cached_input_tokens"),
    cost_usd: costs.length ? costs.reduce((a, b) => a + b, 0) : null,
    unpriced: add("unpriced"),
  };
}

/**
 * A turn's total (services/metrics.turn_total), or null when nothing has
 * metrics. `extra` is calls that belong to no answer (a debate's judge).
 */
export function turnTotal(
  metrics: (ReplyMetrics | null | undefined)[],
  extra: (UsageSummary | null | undefined)[] = [],
): TurnMetrics | null {
  const known = metrics.filter((m): m is ReplyMetrics => !!m);
  const helpers = combineUsage([...known.map((m) => m.helpers), ...extra]);
  if (!known.length && !helpers) return null;
  const priced = known.filter((m) => m.cost_usd !== null);
  const plus = (own: number | null, more: number | undefined) =>
    helpers ? (own ?? 0) + (more ?? 0) : own;
  const answerCost = priced.length
    ? priced.reduce((a, m) => a + (m.cost_usd as number), 0)
    : null;
  const helperCost = helpers?.cost_usd ?? null;
  return {
    answers: known.length,
    ttft_ms: max(known.map((m) => m.ttft_ms)),
    total_ms: max(known.map((m) => m.total_ms)),
    input_tokens: plus(
      sum(known.map((m) => m.input_tokens)),
      helpers?.input_tokens,
    ),
    output_tokens: plus(
      sum(known.map((m) => m.output_tokens)),
      helpers?.output_tokens,
    ),
    reasoning_tokens: plus(
      sum(known.map((m) => m.reasoning_tokens)),
      helpers?.reasoning_tokens,
    ),
    cached_input_tokens: plus(
      sum(known.map((m) => m.cached_input_tokens)),
      helpers?.cached_input_tokens,
    ),
    cost_usd:
      answerCost === null && helperCost === null
        ? null
        : (answerCost ?? 0) + (helperCost ?? 0),
    unpriced:
      known.filter((m) => hasTokens(m) && m.cost_usd === null).length +
      (helpers?.unpriced ?? 0),
    helpers,
  };
}

/** The turn's line: "Total · slowest 9.1 s · 2,468 in / 1,134 out · $0.0246". */
export function formatTurnTotal(t: TurnMetrics | null): string {
  if (!t) return "";
  const parts = ["Total"];
  if (t.total_ms !== null) parts.push(`slowest ${seconds(t.total_ms)}`);
  if (hasTokens(t)) parts.push(tokens(t), cost(t));
  if (t.helpers) parts.push(`incl. ${formatHelpers(t.helpers)}`);
  return parts.join(" · ");
}
