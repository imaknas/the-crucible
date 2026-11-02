import type { Message, TreeEdge, TreeNode } from "@/lib/types";
import type { ReplyMetrics } from "@/lib/metrics";
import type { ReplyContext } from "@/lib/context";
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
  /** Cut off by Stop, or no live run found for it on reattaching. */
  stopped?: boolean;
  /** Why the model failed, if it did. */
  error?: string | null;
  /** The tree node id, once stream_end gives it. */
  checkpoint_id?: string | null;
  turn_id?: string | null;
  model_color?: string | null;
  /** Time, tokens and cost, once stream_end gives them. */
  metrics?: ReplyMetrics | null;
}

/** The multi-model turn streaming (or just streamed) in this tab. */
export interface LiveTurn {
  /** Stable React key for the turn's grid, from send to settled. */
  key: string;
  /** The backend's turn id, from the first stream_start. */
  turnId: string | null;
  /** In the order the models were asked (the selection's). */
  replies: LiveReply[];
  /**
   * More answers to a turn already on the thread ("+ model"): they stream
   * into that turn's grid, wherever it is, never after the last message.
   */
  joins?: boolean;
}

export function startLiveTurn(models: string[], key: string): LiveTurn {
  return { key, turnId: null, replies: models.map((model) => ({ model, content: "", streaming: true })) };
}

/** The grid key of a settled turn; a join streams under it, so the grid never remounts. */
export const turnKey = (turnId: string) => `turn-${turnId}`;

/** "+ model": `model` answering the answered turn `turnId`, streaming into its grid. */
export function startJoin(turnId: string, model: string): LiveTurn {
  return { key: turnKey(turnId), turnId, replies: [{ model, content: "", streaming: true }], joins: true };
}

/** The models that can still be added to a turn: those offered, minus the ones already in it. */
export function addableModels(available: string[], inTurn: string[]): string[] {
  return available.filter((m) => !inTurn.includes(m));
}

export function updateLiveReply(turn: LiveTurn, model: string, patch: Partial<LiveReply>): LiveTurn {
  if (!turn.replies.some((r) => r.model === model)) return turn;
  return {
    ...turn,
    turnId: turn.turnId ?? patch.turn_id ?? null,
    replies: turn.replies.map((r) => (r.model === model ? { ...r, ...patch } : r)),
  };
}

/**
 * A reply of a turn this tab didn't start (it reloaded, or another tab sent
 * it), as the server reports it: added to that turn's cards, or starting
 * them when the turn on screen is another. `joins`: it is one more answer
 * to a turn already answered (the backend's joins_turn).
 */
export function adoptLiveReply(turn: LiveTurn | null, turnId: string, reply: LiveReply, joins = false): LiveTurn {
  if (turn && turn.turnId === turnId) {
    return turn.replies.some((r) => r.model === reply.model)
      ? updateLiveReply(turn, reply.model, reply)
      : { ...turn, replies: [...turn.replies, reply] };
  }
  return joins
    ? { key: turnKey(turnId), turnId, replies: [reply], joins: true }
    : { key: `live-${turnId}`, turnId, replies: [reply] };
}

/**
 * Stop, or no live run found for it on reattaching: whatever is still
 * streaming (or only `model`'s reply) is cut off.
 */
export function stopLiveTurn(turn: LiveTurn | null, model?: string): LiveTurn | null {
  const hit = (r: LiveReply) => r.streaming && (model === undefined || r.model === model);
  if (!turn || !turn.replies.some(hit)) return turn;
  return { ...turn, replies: turn.replies.map((r) => (hit(r) ? { ...r, streaming: false, stopped: true } : r)) };
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
  /** What the answer took; null until known, or for a reply that recorded none. */
  metrics: ReplyMetrics | null;
  /** What it was written from (lib/context); null until the turn settles, or for older replies. */
  context?: ReplyContext | null;
}

export type TranscriptItem =
  | { kind: "message"; key: string; msg: Message; index: number }
  | {
      kind: "turn";
      key: string;
      index: number;
      cards: TurnCard[];
      live: boolean;
      /** The backend's turn id, once known: "+ model" joins it. */
      turnId?: string | null;
    };

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
    metrics: r.metrics ?? null,
    context: null,
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
    const turnId = siblings.find((n) => n.metadata?.turn_id)?.metadata?.turn_id ?? null;
    // A lone reply is a bubble, until a model is added to its turn.
    const joined = !!live?.joins && !!turnId && turnId === live.turnId;
    if (siblings.length < 2 && !(joined && siblings.length === 1)) {
      items.push({ kind: "message", key: msg.id || `msg-${index}`, msg, index });
      return;
    }
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
        // Live numbers first (stream_end), then the stored ones.
        metrics: (own ? msg.metrics : null) ?? liveReply?.metrics ?? node.metadata?.metrics ?? null,
        context: (own ? msg.context : null) ?? node.metadata?.context ?? null,
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
      key: isLiveTurn ? live!.key : turnId ? turnKey(turnId) : `turn-${msg.checkpoint_id}`,
      index,
      cards,
      live: false,
      turnId,
    });
  });

  // Until the refreshed path holds it, the streaming turn follows its
  // question (the last message). Once the person opens another branch, a
  // turn the path doesn't hold is not drawn under it. A join belongs to a
  // turn above, never after the last message.
  if (live && !liveUsed && !live.joins && messages[messages.length - 1]?.role === "user") {
    items.push({
      kind: "turn",
      key: live.key,
      index: messages.length,
      cards: live.replies.map(liveCard),
      live: true,
      turnId: live.turnId,
    });
  }
  return items;
}

/** The answers a synthesis can merge: replies with a node, minus failures and synthesis nodes. */
export function synthesizableIds(cards: TurnCard[], nodes: TreeNode[]): string[] {
  return cards
    .filter((c) => c.id && !c.error && !c.streaming && !isSynthesisNode(nodes.find((n) => n.id === c.id)))
    .map((c) => c.id as string);
}
