/**
 * Pure bookkeeping for the debate transcript shown in the Arena view.
 *
 * Debate WebSocket events arrive interleaved across models. This module turns
 * them into chat bubbles; useDebateSession owns the socket, the timing (token
 * batching) and every side effect. Keeping the transformation pure is what
 * makes it testable without a socket or a page.
 */
import type { DebateLane, DebateSession, DebateUiStatus, Message } from "@/lib/types";

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
  | { type: "stream_end"; model: string; content?: string }
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
      return {
        messages: [...state.messages, { id, role: "assistant", model: event.model, content: "", streaming: true }],
        streaming: { ...state.streaming, [event.model]: id },
      };
    }

    case "stream_end": {
      const id = state.streaming[event.model];
      if (!id) return state;
      return {
        messages: update(state.messages, id, (m) => ({ ...m, content: event.content ?? m.content, streaming: false })),
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
  if (!liveStatus) return serverStatus;
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
 * The status after a debate stops early. Only a judge measures agreement; a
 * stability stop means each model's answer stopped changing, which two models
 * holding opposite positions also satisfy.
 */
export function earlyStopStatus(method: string | undefined): DebateUiStatus {
  return method === "judge" ? "converged" : "stable";
}

export interface DebateControls {
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
    inject: live || held,
    redirect: live,
    pause: live,
    resume: status === "paused",
    synthesize: hasTranscript && status !== "running" && status !== "pausing",
    stopOnClose: live || held,
  };
}
