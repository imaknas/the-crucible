import type { Message, TreeEdge, TreeNode } from "@/lib/types";
import { cardExcerpt, isSynthesisNode, orderSiblings, turnSiblings } from "@/lib/arenaCompare";

/**
 * A multi-model turn as compare cards, from the first token to the settled
 * tree.
 *
 * A turn sent to several models streams into one card per model, and stays
 * those same cards once it settles: the history refresh only fills in ids
 * and text. It used to stream as a stack of full bubbles that collapsed
 * into cards at the end, so the page jumped as every turn finished. A
 * single-model turn is an ordinary bubble.
 */

/** One model's reply while its turn streams (useChatWebSocket). */
export interface LiveReply {
  model: string;
  content: string;
  streaming: boolean;
  /** Cut off by Stop or a dropped connection. */
  stopped?: boolean;
  /** Why the model failed, if it did. */
  error?: string | null;
  /** The tree node id, once stream_end gives it. */
  checkpoint_id?: string | null;
  turn_id?: string | null;
  model_color?: string | null;
}

/** The multi-model turn streaming (or just streamed) in this tab. */
export interface LiveTurn {
  /** Stable React key for the turn's grid, from send to settled. */
  key: string;
  /** The backend's turn id, from the first stream_start. */
  turnId: string | null;
  /** In the order the models were asked (the selection's). */
  replies: LiveReply[];
}

export function startLiveTurn(models: string[], key: string): LiveTurn {
  return { key, turnId: null, replies: models.map((model) => ({ model, content: "", streaming: true })) };
}

export function updateLiveReply(turn: LiveTurn, model: string, patch: Partial<LiveReply>): LiveTurn {
  if (!turn.replies.some((r) => r.model === model)) return turn;
  return {
    ...turn,
    turnId: turn.turnId ?? patch.turn_id ?? null,
    replies: turn.replies.map((r) => (r.model === model ? { ...r, ...patch } : r)),
  };
}

/** Stop or a dropped socket: whatever is still streaming is cut off. */
export function stopLiveTurn(turn: LiveTurn | null): LiveTurn | null {
  if (!turn || !turn.replies.some((r) => r.streaming)) return turn;
  return { ...turn, replies: turn.replies.map((r) => (r.streaming ? { ...r, streaming: false, stopped: true } : r)) };
}

/** What one compare card shows. */
export interface TurnCard {
  /** The model: a card keeps its place (and its React identity) across the turn's life. */
  key: string;
  model: string;
  /** The reply's tree node, once known: Read in full and Continue need it. */
  id: string | null;
  /** The backend's display name; null before the tree has the node. */
  label: string | null;
  color: string | null;
  text: string;
  /** `text` is the whole reply (else an excerpt, which Read in full opens). */
  full: boolean;
  streaming: boolean;
  stopped: boolean;
  error: string | null;
  /** Its conversation is the one on screen. */
  shown: boolean;
}

export type TranscriptItem =
  | { kind: "message"; key: string; msg: Message; index: number }
  | { kind: "turn"; key: string; index: number; cards: TurnCard[]; live: boolean };

interface BuildOptions {
  messages: Message[];
  nodes: TreeNode[];
  edges: TreeEdge[];
  /** The Control Panel's selection: cards follow the order models were asked in. */
  selected: string[];
  /** Full text of replies streamed in this tab, by node id. */
  replyTexts: Record<string, string>;
  live: LiveTurn | null;
}

function liveCard(r: LiveReply): TurnCard {
  return {
    key: r.model,
    model: r.model,
    id: r.checkpoint_id ?? null,
    label: null,
    color: r.model_color ?? null,
    text: r.content,
    full: true,
    streaming: r.streaming,
    stopped: !!r.stopped,
    error: r.error ?? null,
    shown: false,
  };
}

function isReply(msg: Message): boolean {
  const assistant = msg.role === "assistant" || msg.type === "ai";
  return assistant && !!msg.checkpoint_id && msg.kind !== "synthesis" && msg.kind !== "debate" && msg.type !== "synthesis";
}

/**
 * The transcript as bubbles and turn grids. A reply on the path whose turn
 * has other models' replies becomes that turn's grid, with its own card
 * holding the full text; the turn streaming now is a grid after the last
 * message until the refreshed path contains it, and then that grid keeps
 * its key, so nothing remounts.
 */
export function buildTranscript({ messages, nodes, edges, selected, replyTexts, live }: BuildOptions): TranscriptItem[] {
  const items: TranscriptItem[] = [];
  let liveUsed = false;

  messages.forEach((msg, index) => {
    const siblings = isReply(msg) ? turnSiblings(nodes, edges, msg.checkpoint_id ?? null) : [];
    if (siblings.length < 2) {
      items.push({ kind: "message", key: msg.id || `msg-${index}`, msg, index });
      return;
    }
    const turnId = siblings.find((n) => n.metadata?.turn_id)?.metadata?.turn_id ?? null;
    const ids = new Set(siblings.map((n) => n.id));
    const isLiveTurn =
      !!live && ((!!turnId && turnId === live.turnId) || live.replies.some((r) => r.checkpoint_id && ids.has(r.checkpoint_id)));
    if (isLiveTurn) liveUsed = true;

    const cards: TurnCard[] = orderSiblings(siblings, selected).map((node) => {
      const model = node.metadata?.active_peer || node.id;
      const own = node.id === msg.checkpoint_id;
      const streamed = replyTexts[node.id];
      const liveReply = isLiveTurn ? live!.replies.find((r) => r.model === model) : undefined;
      return {
        key: model,
        model,
        id: node.id,
        label: node.metadata?.model_name ?? null,
        color: (node.metadata?.model_color as string | undefined) ?? null,
        text: own ? msg.content : (streamed ?? cardExcerpt(node)),
        full: own || streamed !== undefined,
        streaming: false,
        stopped: !!liveReply?.stopped,
        error: liveReply?.error ?? null,
        shown: own,
      };
    });
    // A model that failed this turn has no node; its card stays, saying so.
    if (isLiveTurn) {
      for (const r of live!.replies) {
        if (!cards.some((c) => c.model === r.model)) cards.push(liveCard(r));
      }
    }
    items.push({
      kind: "turn",
      key: isLiveTurn ? live!.key : `turn-${turnId ?? msg.checkpoint_id}`,
      index,
      cards,
      live: false,
    });
  });

  // Until the refreshed path holds it, the streaming turn follows its
  // question (the last message). Once the person opens another branch, a
  // turn the path doesn't hold is not drawn under it.
  if (live && !liveUsed && messages[messages.length - 1]?.role === "user") {
    items.push({ kind: "turn", key: live.key, index: messages.length, cards: live.replies.map(liveCard), live: true });
  }
  return items;
}

/** The answers a synthesis can merge: replies with a node, minus failures and synthesis nodes. */
export function synthesizableIds(cards: TurnCard[], nodes: TreeNode[]): string[] {
  return cards
    .filter((c) => c.id && !c.error && !c.streaming && !isSynthesisNode(nodes.find((n) => n.id === c.id)))
    .map((c) => c.id as string);
}
