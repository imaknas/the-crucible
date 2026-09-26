/**
 * Pure bookkeeping for the debate transcript shown in the Arena view.
 *
 * Debate WebSocket events arrive interleaved across models. This module turns
 * them into chat bubbles; useDebateSession owns the socket, the timing (token
 * batching) and every side effect. Keeping the transformation pure is what
 * makes it testable without a socket or a page.
 */
import type { DebateSession, DebateUiStatus, Message } from "@/lib/types";

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
          { id: `round-header-${r}`, role: "system", type: "round_header", content: `Round ${r + 1}` },
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
 * A session loaded from the server has no socket in this tab, so it cannot be
 * running here: the backend cancels a debate when its socket closes.
 */
export function restoredDebateStatus(status: DebateSession["status"]): DebateUiStatus {
  return status === "completed" ? "completed" : "interrupted";
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

/** Which debate controls the UI offers for a given state. */
export function debateControls(status: DebateUiStatus, hasTranscript: boolean): DebateControls {
  const live = status === "running";
  return {
    inject: live,
    redirect: live,
    pause: live,
    resume: status === "paused",
    synthesize: hasTranscript && status !== "running" && status !== "pausing",
    stopOnClose: live || status === "pausing" || status === "paused",
  };
}
