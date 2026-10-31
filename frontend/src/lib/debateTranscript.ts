/**
 * Pure bookkeeping for the debate transcript shown in the Arena view.
 *
 * Debate WebSocket events arrive interleaved across models. This module turns
 * them into chat bubbles; useDebateSession owns the socket, the timing (token
 * batching) and every side effect. Keeping the transformation pure is what
 * makes it testable without a socket or a page.
 */
import type { DebateLane, DebateSession, DebateTranscript, DebateUiStatus, Message, TreeNode } from "@/lib/types";

export interface Transcript {
  messages: Message[];
  /** model id (or SYNTHESIS_KEY) → id of the bubble it is currently streaming into. */
  streaming: Record<string, string>;
}

export const EMPTY_TRANSCRIPT: Transcript = { messages: [], streaming: {} };

const SYNTHESIS_KEY = "__synthesis__";

/** The subset of debate WebSocket events that change the transcript. */
export type TranscriptEvent =
  | { type: "debate_round_start"; round?: number }
  | { type: "stream_start"; model: string; round?: number }
  | { type: "stream_end"; model: string; content?: string; checkpoint_id?: string }
  | { type: "debate_synthesis_start"; model?: string }
  | { type: "debate_synthesis_end"; model?: string; content?: string }
  | { type: "error"; model?: string; message?: string };

export type TranscriptAction =
  | { kind: "event"; event: TranscriptEvent; now: number }
  /** Batched tokens, keyed by the model (or synthesizer) that produced them. */
  | { kind: "tokens"; chunks: Record<string, string> }
  | { kind: "user"; entry: "inject" | "redirect"; content: string; now: number }
  | { kind: "reset"; messages?: Message[] };

/**
 * A round's heading. Round 1 holds each participant's independent answer,
 * written before it saw the others; marking it lets a reader compare those
 * answers with the ones written after debating. `short` is the tree's band.
 */
export function roundLabel(round: number, form: "full" | "short" = "full"): string {
  if (round !== 0) return `Round ${round + 1}`;
  return form === "full" ? "Round 1 · independent answers" : "Round 1 · independent";
}

export interface PeerLegendEntry {
  label: string;
  name: string;
  modelId: string;
  color: string;
}

/**
 * Which model each "Participant X" is. With anonymous peers, replies and the
 * argument map refer to each other by these labels, so a reader needs the key;
 * empty when the models saw each other's names.
 */
export function peerLegend(lanes: DebateLane[] | undefined): PeerLegendEntry[] {
  return (lanes ?? [])
    .filter((lane) => !!lane.peer_label)
    .map((lane) => ({
      label: lane.peer_label as string,
      name: lane.label || lane.model_id,
      modelId: lane.model_id,
      color: lane.color,
    }))
    .sort((a, b) => a.label.localeCompare(b.label));
}

/** The debated question, shown at the top of the transcript. */
export function questionMessage(content: string): Message {
  return { id: "debate-question", role: "user", content, type: "human" };
}

/**
 * A stored debate as transcript bubbles: the question, each round under its
 * heading with every participant in session order, what was injected into a
 * round, a redirect where the question changed, and the synthesis. Rounds
 * come aligned from the server, so a model that failed a round shows why in
 * that round instead of shifting its later answers up.
 */
export function transcriptMessages(t: DebateTranscript, participants: string[]): Message[] {
  const out: Message[] = [];
  if (t.question || t.rounds[0]?.question) out.push(questionMessage(t.rounds[0]?.question || t.question));
  let asked = t.rounds[0]?.question || t.question;
  for (const r of [...t.rounds].sort((a, b) => a.round - b.round)) {
    if (r.question && r.question !== asked) {
      out.push({ id: `redirect-r${r.round}`, role: "user", type: "redirect", content: r.question });
      asked = r.question;
    }
    for (const [i, inj] of (t.injected ?? []).entries()) {
      if (inj.round === r.round) out.push({ id: `inject-r${r.round}-${i}`, role: "user", type: "inject", content: inj.message });
    }
    out.push({ id: `round-header-${r.round}`, role: "system", type: "round_header", content: roundLabel(r.round) });
    const models = [...participants, ...Object.keys(r.responses).filter((m) => !participants.includes(m))];
    for (const model of models) {
      const text = r.responses[model];
      const error = r.errors?.[model];
      if (text === undefined && error === undefined) continue;
      out.push({
        id: `restored-${model}-r${r.round}`,
        role: "assistant",
        model,
        type: "ai",
        round: r.round,
        content: text ? (error ? `${text}\n\n_(stopped: ${error})_` : text) : `_(no response: ${error})_`,
      });
    }
  }
  if (t.synthesis?.content) {
    out.push({
      id: "restored-synthesis",
      role: "assistant",
      type: "synthesis",
      model: t.synthesis.model,
      ...(t.synthesis.model_name ? { model_name: t.synthesis.model_name } : {}),
      content: t.synthesis.content,
    });
  }
  return out;
}

/**
 * The transcript reply a debate tree node stands for, so the node can be read
 * in full (the node shows a 400-character excerpt at most). A lane node is
 * `{model}::{checkpoint}`: the reply whose stream_end named that checkpoint,
 * else the model's reply in the node's round (restored replies carry no
 * checkpoint). The synthesis node is the latest synthesis. Null while nothing
 * matches, e.g. a reply still to be read back after a reload.
 */
export function debateReplyFor(node: TreeNode | undefined, messages: Message[]): Message | null {
  if (!node || node.metadata?.pending) return null;
  const replies = messages.filter((m) => m.role === "assistant");
  if (node.metadata?.role === "synthesis" || node.type === "synthesis") {
    return replies.filter((m) => m.type === "synthesis").at(-1) ?? null;
  }
  const model = node.metadata?.active_peer;
  if (!model) return null;
  const byId = replies.find((m) => m.checkpoint_id && `${model}::${m.checkpoint_id}` === node.id);
  if (byId) return byId;
  const round = node.metadata?.round_num;
  return replies.find((m) => m.model === model && m.type !== "synthesis" && m.round === round) ?? null;
}

/** The heading of a node's reply read in full: who wrote it, and in which round. */
export function debateReplyTitle(node: TreeNode, lanes: DebateLane[] | undefined): string {
  const name = node.metadata?.model_name || node.metadata?.active_peer || "";
  if (node.metadata?.role === "synthesis" || node.type === "synthesis") {
    return name && name !== "synthesis" ? `Argument map · ${name}` : "Argument map";
  }
  const peer = (lanes ?? []).find((l) => l.model_id === node.metadata?.active_peer)?.peer_label;
  const who = peer ? `${name} (${peer})` : name;
  return `${who} · ${roundLabel(node.metadata?.round_num ?? 0)}`;
}

/**
 * The most model calls a debate can make, so its cost is visible before it
 * starts: every participant every round, a judge after each round, and the
 * synthesis. An early stop makes fewer.
 */
export function debateCallEstimate(opts: {
  rounds: number;
  participants: number;
  judge: boolean;
  synthesize: boolean;
}): { calls: number; breakdown: string } {
  const answers = opts.rounds * opts.participants;
  const judge = opts.judge ? opts.rounds : 0;
  const synthesis = opts.synthesize ? 1 : 0;
  const parts = [`${opts.rounds} ${opts.rounds === 1 ? "round" : "rounds"} × ${opts.participants} models`];
  if (judge) parts.push(`${judge} judge ${judge === 1 ? "call" : "calls"}`);
  if (synthesis) parts.push("1 synthesis");
  return { calls: answers + judge + synthesis, breakdown: parts.join(" + ") };
}

/**
 * Whether a stored transcript lacks rounds its session says were finished:
 * the session is at round N, so rounds before N must have answers.
 */
export function transcriptIncomplete(t: DebateTranscript, session: Pick<DebateSession, "current_round">): boolean {
  return t.rounds.length < session.current_round;
}

/** How long ago a session started, for the sidebar ("5 min ago", "Oct 28"). */
export function sessionAge(createdAt: string | null | undefined, now: number): string | null {
  if (!createdAt) return null;
  // SQLite's CURRENT_TIMESTAMP is UTC without a zone: "2026-10-31 09:15:02".
  const iso = /[zZ]|[+-]\d\d:?\d\d$/.test(createdAt) ? createdAt : `${createdAt.replace(" ", "T")}Z`;
  const t = Date.parse(iso);
  if (Number.isNaN(t)) return null;
  const minutes = Math.round((now - t) / 60000);
  if (minutes < 1) return "just now";
  if (minutes < 60) return `${minutes} min ago`;
  const hours = Math.round(minutes / 60);
  if (hours < 24) return `${hours} h ago`;
  return new Date(t).toLocaleDateString(undefined, { month: "short", day: "numeric" });
}

/**
 * The chat messages to show under a debate's transcript. A turn after a
 * debate continues from a record of it on the thread (kind "debate"); that
 * record and the question before it repeat the transcript above, so only
 * what follows the record is shown.
 */
export function afterDebateRecord(messages: Message[]): Message[] {
  for (let i = messages.length - 1; i >= 0; i--) {
    if (messages[i].kind === "debate") return messages.slice(i + 1);
  }
  return messages;
}

function update(messages: Message[], id: string, patch: (m: Message) => Message): Message[] {
  return messages.map((m) => (m.id === id ? patch(m) : m));
}

function withoutKey(map: Record<string, string>, key: string): Record<string, string> {
  const next = { ...map };
  delete next[key];
  return next;
}

export function transcriptReducer(state: Transcript, action: TranscriptAction): Transcript {
  switch (action.kind) {
    case "reset":
      return { messages: action.messages ?? [], streaming: {} };

    case "user":
      return {
        ...state,
        messages: [
          ...state.messages,
          { id: `${action.entry}-${action.now}`, role: "user", content: action.content, type: action.entry },
        ],
      };

    case "tokens": {
      let messages = state.messages;
      for (const [key, text] of Object.entries(action.chunks)) {
        const id = state.streaming[key];
        // Tokens that land after their stream closed are dropped, not appended
        // to a finished bubble.
        if (!id || !text) continue;
        messages = update(messages, id, (m) => ({ ...m, content: m.content + text }));
      }
      return messages === state.messages ? state : { ...state, messages };
    }

    case "event":
      return applyEvent(state, action.event, action.now);
  }
}

function applyEvent(state: Transcript, event: TranscriptEvent, now: number): Transcript {
  switch (event.type) {
    case "debate_round_start": {
      const r = event.round ?? 0;
      return {
        ...state,
        messages: [
          ...state.messages,
          { id: `round-header-${r}`, role: "system", type: "round_header", content: roundLabel(r) },
        ],
      };
    }

    case "stream_start": {
      const id = `debate-${event.model}-r${event.round ?? 0}-${now}`;
      const bubble: Message = { id, role: "assistant", model: event.model, content: "", streaming: true, round: event.round ?? 0 };
      return {
        messages: [...state.messages, bubble],
        streaming: { ...state.streaming, [event.model]: id },
      };
    }

    case "stream_end": {
      const id = state.streaming[event.model];
      if (!id) return state;
      return {
        messages: update(state.messages, id, (m) => ({
          ...m,
          content: event.content ?? m.content,
          streaming: false,
          ...(event.checkpoint_id ? { checkpoint_id: event.checkpoint_id } : {}),
        })),
        streaming: withoutKey(state.streaming, event.model),
      };
    }

    case "debate_synthesis_start": {
      const id = `debate-synthesis-${now}`;
      const streaming: Record<string, string> = { ...state.streaming, [SYNTHESIS_KEY]: id };
      // Synthesis tokens arrive as stream_token under the synthesizer's id.
      if (event.model) streaming[event.model] = id;
      return {
        messages: [
          ...state.messages,
          { id, role: "assistant", model: event.model, content: "", streaming: true, type: "synthesis" },
        ],
        streaming,
      };
    }

    case "debate_synthesis_end": {
      const id = state.streaming[SYNTHESIS_KEY];
      if (!id) return state;
      let streaming = withoutKey(state.streaming, SYNTHESIS_KEY);
      if (event.model) streaming = withoutKey(streaming, event.model);
      return {
        messages: update(state.messages, id, (m) => ({ ...m, content: event.content ?? m.content, streaming: false })),
        streaming,
      };
    }

    case "error": {
      // A model that errors or times out never sends stream_end; close its
      // bubble here or it streams forever.
      if (!event.model) return state;
      const id = state.streaming[event.model];
      if (!id) return state;
      const reason = event.message ?? "error";
      return {
        messages: update(state.messages, id, (m) => ({
          ...m,
          content: m.content ? `${m.content}\n\n_(stopped: ${reason})_` : `_(no response: ${reason})_`,
          streaming: false,
        })),
        streaming: withoutKey(state.streaming, event.model),
      };
    }
  }
}

// ─── Status & controls ───────────────────────────────────────────

/**
 * The status a sidebar row shows. The server's record only knows a debate is
 * running; the tab driving it knows it is pausing or paused.
 */
export function sessionRowStatus(
  serverStatus: DebateSession["status"],
  liveStatus: DebateUiStatus | null | undefined,
): string {
  if (!liveStatus) return serverStatus === "pending" ? "not started" : serverStatus;
  return liveStatus === "converged" || liveStatus === "stable" ? "completed" : liveStatus;
}

/**
 * A session loaded from the server has no socket in this tab, so it cannot be
 * running here: the backend cancels a debate when its socket closes.
 */
export function restoredDebateStatus(status: DebateSession["status"]): DebateUiStatus {
  return status === "completed" ? "completed" : "interrupted";
}

/**
 * What leaving a debate would cost, or null when nothing is lost: a debate
 * runs only while the tab driving it is connected, so leaving a running,
 * pausing or paused one stops it.
 */
export function leaveWarning(status: DebateUiStatus, connected: boolean): string | null {
  if (!connected) return null;
  if (status === "running" || status === "pausing")
    return "The debate is still running in this tab. Leaving stops it after the current answers; you can resume it later.";
  if (status === "paused")
    return "The debate is paused, which holds only while this tab stays on it. Leaving stops it; you can resume it later.";
  return null;
}

/**
 * The status after a debate stops early. Only a judge measures agreement; a
 * stability stop means each model's answer stopped changing, which two models
 * holding opposite positions also satisfy.
 */
export function earlyStopStatus(method: string | undefined): DebateUiStatus {
  return method === "judge" ? "converged" : "stable";
}

export interface DebateControls {
  /** Run more rounds of a stopped debate (debate_continue): Resume after an interruption, or one more round. */
  continue: boolean;
  inject: boolean;
  redirect: boolean;
  pause: boolean;
  resume: boolean;
  synthesize: boolean;
  /** Whether closing the debate must first tell the backend to stop it. */
  stopOnClose: boolean;
}

/**
 * Which debate controls the UI offers for a given state.
 *
 * Injecting stays available while a debate is pausing or paused: the message
 * joins the next round's prompts, and without it the composer fell back to
 * sending an ordinary chat turn in the middle of a paused debate.
 */
export function debateControls(status: DebateUiStatus, hasTranscript: boolean): DebateControls {
  const live = status === "running";
  const held = status === "pausing" || status === "paused";
  return {
    continue: hasTranscript && (status === "interrupted" || status === "completed" || status === "stable" || status === "converged"),
    inject: live || held,
    redirect: live,
    pause: live,
    resume: status === "paused",
    synthesize: hasTranscript && status !== "running" && status !== "pausing",
    stopOnClose: live || held,
  };
}
