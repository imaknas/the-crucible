/**
 * Branching from a highlighted span: text selected inside one reply becomes
 * a quote in the composer, and the next message continues from that reply.
 */
import type { TranscriptItem } from "@/lib/turns";

/** The longest quote put in the composer; a longer selection is cut there. */
export const QUOTE_MAX_CHARS = 1200;

/**
 * The tree node of the reply a selection sits in: a finished assistant
 * reply with a node, found by the transcript row it is in (`turnKey`, for
 * a turn's cards) and the rendered body's message id (`messageId`: a card's
 * key, or a bubble's id). Null for a person's message, a reply still
 * streaming, a debate's record, a summary, or text outside any reply.
 */
export function replyNodeAt(items: TranscriptItem[], turnKey: string | null, messageId: string | null): string | null {
  if (!messageId) return null;
  if (turnKey) {
    const turn = items.find((i) => i.kind === "turn" && i.key === turnKey);
    if (turn?.kind !== "turn") return null;
    const card = turn.cards.find((c) => c.key === messageId);
    return card && !card.streaming && !card.error ? card.id : null;
  }
  const item = items.find((i) => i.kind === "message" && i.msg.id === messageId);
  if (item?.kind !== "message") return null;
  const msg = item.msg;
  // A synthesis is a reply like any other; a debate's record and a summary are not one model's answer.
  const reply = (msg.role === "assistant" || msg.type === "ai") && msg.kind !== "debate" && msg.kind !== "summary";
  return reply && !msg.streaming ? (msg.checkpoint_id ?? null) : null;
}

/** The selection as a markdown quote, followed by an empty line to write under. */
export function quoteForBranch(text: string): string {
  let span = text.trim().replace(/\n{3,}/g, "\n\n");
  if (span.length > QUOTE_MAX_CHARS) span = `${span.slice(0, QUOTE_MAX_CHARS).trimEnd()}…`;
  return `${span
    .split("\n")
    .map((line) => (line.trim() ? `> ${line}` : ">"))
    .join("\n")}\n\n`;
}
