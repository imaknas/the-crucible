import type { Message } from "@/lib/types";

/**
 * Merge a freshly loaded path into what is on screen without remounting
 * bubbles that are already there (remounts replay their entry animation and
 * lose expanded reasoning).
 *
 * A message's key is its tree node id (`checkpoint_id`): the same id a
 * streamed reply got from stream_end, so it survives the refresh after a
 * turn. The question echoed when it was sent has a client id; the same
 * text at the same place keeps it, or the bubble remounted (and flickered)
 * every time a turn settled. Payloads from before ids were sent fall back
 * to the position, when the message there has the same author.
 */
export function reconcileMessages(prev: Message[], next: Message[]): Message[] {
  return next.map((msg, idx) => {
    const there = prev[idx];
    if (there?.id && there.role === "user" && msg.role === "user" && there.content === msg.content && there.id !== msg.checkpoint_id) {
      return { ...msg, id: there.id };
    }
    if (msg.checkpoint_id) return { ...msg, id: msg.checkpoint_id };
    if (msg.id) return msg;
    const sameAuthor = there && there.role === msg.role && (there.model === msg.model || !msg.model);
    return { ...msg, id: sameAuthor && there.id ? there.id : `stable-${idx}` };
  });
}

/** The person's last message on a path: what Edit & fork puts back in the composer. */
export function lastUserText(messages: Pick<Message, "role" | "content">[]): string | null {
  for (let i = messages.length - 1; i >= 0; i--) {
    if (messages[i].role === "user") return messages[i].content;
  }
  return null;
}

/** Replies still streaming are marked cut off: Stop or a dropped socket ended them. */
export function markStopped(messages: Message[]): Message[] {
  return messages.some((m) => m.streaming)
    ? messages.map((m) => (m.streaming ? { ...m, streaming: false, stopped: true } : m))
    : messages;
}
