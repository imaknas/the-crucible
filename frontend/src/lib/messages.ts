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
  const merged = next.map((msg, idx) => {
    const there = prev[idx];
    if (there?.id && there.role === "user" && msg.role === "user" && there.content === msg.content && there.id !== msg.checkpoint_id) {
      return { ...msg, id: there.id };
    }
    if (msg.checkpoint_id) return { ...msg, id: msg.checkpoint_id };
    if (msg.id) return msg;
    const sameAuthor = there && there.role === msg.role && (there.model === msg.model || !msg.model);
    return { ...msg, id: sameAuthor && there.id ? there.id : `stable-${idx}` };
  });
  return [...merged, ...turnInFlight(prev, next)];
}

/** Id prefix of what a tab shows for a run it attached to (useChatWebSocket). */
export const RESUMED = "resumed-";

/**
 * A turn this tab attached to (a reload, another tab) is not on any loaded
 * path yet: the history ends at the last answered turn. Its question and
 * single-model bubble stay after a load until the path holds the turn.
 */
function turnInFlight(prev: Message[], next: Message[]): Message[] {
  const tail: Message[] = [];
  for (let i = prev.length - 1; i >= 0 && prev[i].id?.startsWith(RESUMED); i--) tail.unshift(prev[i]);
  if (!tail.length) return [];
  const loaded = new Set(next.map((m) => m.turn_id).filter(Boolean));
  return tail.filter((m) => !m.turn_id || !loaded.has(m.turn_id));
}

/**
 * The question of a turn this tab attached to, after the messages on
 * screen: unless it is already there (this tab sent it, or the path holds
 * the turn).
 */
export function withResumedQuestion(messages: Message[], turnId: string, question: string): Message[] {
  const id = `${RESUMED}q-${turnId}`;
  if (messages.some((m) => m.id === id || m.turn_id === turnId)) return messages;
  const last = messages[messages.length - 1];
  if (last?.role === "user" && last.content === question) return messages;
  return [...messages, { id, role: "user", content: question, type: "human", turn_id: turnId }];
}

/** The person's last message on a path: what Edit & fork puts back in the composer. */
export function lastUserText(messages: Pick<Message, "role" | "content">[]): string | null {
  for (let i = messages.length - 1; i >= 0; i--) {
    if (messages[i].role === "user") return messages[i].content;
  }
  return null;
}

/**
 * Replies still streaming (or only `model`'s) are marked cut off: Stop
 * ended them, or a reattached socket found no live run for them. A dropped
 * socket alone doesn't: the run goes on without it.
 */
export function markStopped(messages: Message[], model?: string): Message[] {
  const hit = (m: Message) => !!m.streaming && (model === undefined || m.model === model);
  return messages.some(hit) ? messages.map((m) => (hit(m) ? { ...m, streaming: false, stopped: true } : m)) : messages;
}
