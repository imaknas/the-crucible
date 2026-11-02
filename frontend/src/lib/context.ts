/**
 * What a turn is written from, in words: a reply's own record (what its
 * call saw) and the backend's estimate for the next turn from a branch
 * point (GET /history/{thread}/context). Token counts are approximate: one
 * tokenizer for every provider.
 */

/** One excerpt recall brought back from the hidden history. */
export interface RecalledExcerpt {
  role: "user" | "assistant";
  author?: string | null;
  excerpt: string;
}

/** What a reply's drafting call saw; null for replies from before it was recorded. */
export interface ReplyContext {
  tokens: number;
  soft_limit: number;
  context_window: number | null;
  /** The call jumped to the latest summary instead of the whole history. */
  pruned: boolean;
  kept_verbatim?: number;
  hidden?: number;
  recalled: RecalledExcerpt[];
}

/** What the next turn from a branch point would send one model. */
export interface NextTurnContext {
  model: string;
  tokens: number;
  history_tokens: number;
  messages: number;
  summarized: boolean;
  from_summary: boolean;
  summarizes_next: boolean;
  soft_limit: number;
  context_window: number | null;
}

export function formatTokens(n: number): string {
  if (n >= 1_000_000) return `~${(n / 1_000_000).toFixed(1).replace(/\.0$/, "")}M`;
  if (n >= 1_000) return `~${(n / 1_000).toFixed(n >= 10_000 ? 0 : 1).replace(/\.0$/, "")}k`;
  return `~${n}`;
}

/** The model whose budget the next turn fills most; null for no rows. */
export function tightest(rows: NextTurnContext[]): NextTurnContext | null {
  return rows.reduce<NextTurnContext | null>(
    (worst, r) => (!worst || r.tokens / r.soft_limit > worst.tokens / worst.soft_limit ? r : worst),
    null,
  );
}

/** The chip's line: what the next turn inherits. Null when there is nothing to say. */
export function inheritLine(rows: NextTurnContext[]): string | null {
  const worst = tightest(rows);
  if (!worst) return null;
  if (worst.messages === 0) return "no earlier messages";
  const parts = [`${worst.messages} message${worst.messages === 1 ? "" : "s"}`, `${formatTokens(worst.tokens)} tokens`];
  if (rows.some((r) => r.summarizes_next)) parts.push("summarizes first");
  else if (rows.some((r) => r.from_summary)) parts.push("from a summary");
  return parts.join(" · ");
}

/** Share of the tightest model's soft limit the next turn uses, 0–1. */
export function budgetShare(rows: NextTurnContext[]): number {
  const worst = tightest(rows);
  return worst ? Math.min(1, worst.tokens / worst.soft_limit) : 0;
}

/** One line per model for the chip's tooltip. */
export function inheritDetails(rows: NextTurnContext[], modelLabel: (id: string) => string): string[] {
  return rows.map((r) => {
    const share = Math.round((r.tokens / r.soft_limit) * 100);
    const how = r.summarizes_next
      ? "the turn writes a summary first"
      : r.from_summary
        ? "answers from the summary and the latest messages"
        : r.summarized
          ? "the whole history (a summary exists but isn't needed)"
          : "the whole history";
    return `${modelLabel(r.model)}: ${formatTokens(r.tokens)} of ${formatTokens(r.soft_limit)} tokens before summarizing (${share}%), ${how}`;
  });
}

/** Under a reply: how it was written, when that wasn't simply the whole history. */
export function replyContextNote(ctx: ReplyContext | null | undefined): string | null {
  if (!ctx) return null;
  const recalled = ctx.recalled?.length ?? 0;
  if (!ctx.pruned && !recalled) return null;
  const parts: string[] = [];
  if (ctx.pruned) {
    const kept = ctx.kept_verbatim ?? 0;
    parts.push(
      kept ? `Written from the summary and ${kept} recent message${kept === 1 ? "" : "s"}` : "Written from the summary",
    );
  }
  if (recalled) parts.push(`recall brought back ${recalled} earlier message${recalled === 1 ? "" : "s"}`);
  const text = parts.join("; ");
  return text.charAt(0).toUpperCase() + text.slice(1);
}
