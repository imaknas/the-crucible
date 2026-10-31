// ─── Shared Types ───────────────────────────────────────────────────────────
// Single source of truth for all shared data types across the frontend.

export interface Message {
  /** Stable client-side key: the tree node id once the server has one, so a refresh doesn't remount it. */
  id: string;
  role: string;
  content: string;
  type?: string;
  model?: string;
  /** Display name for `model`, from the backend; the raw ID stays in `model`. */
  model_name?: string;
  /** "synthesis" for a reply that merged sibling answers (set by the backend). */
  kind?: string | null;
  streaming?: boolean;
  /** Cut off before it finished (Stop, or the connection dropped): what is shown is partial. */
  stopped?: boolean;
  sources?: { text: string; filename: string }[];
  /** The tree node this message is (path messages and stream_end carry it). */
  checkpoint_id?: string | null;
  /** The person's message and every reply sent with it share one. */
  turn_id?: string | null;
  /** The model family's colour, from the backend. */
  model_color?: string | null;
}

/** One model's failed turn, shown inline with a Retry instead of a modal. */
export interface ModelError {
  id: string;
  model: string;
  message: string;
  /** The exact frame that failed, its parent pinned, so Retry asks again from the same point. */
  frame: Record<string, unknown>;
}

export interface Toggles {
  use_rag: boolean;
  use_web_search: boolean;
}

export interface TreeNode {
  id: string;
  data: {
    label: string;
  };
  position: { x: number; y: number };
  metadata?: {
    role?: string;
    active_peer?: string;
    /** Human-facing model label, e.g. "Claude Haiku 4.5". Prefer this over active_peer. */
    model_name?: string;
    has_thoughts?: boolean;
    /** Longer excerpt, revealed when the node is selected. */
    preview?: string;
    /** Debate mode: lane column, debate round, and the family colour. */
    lane_index?: number;
    round_num?: number;
    model_color?: string;
    pending?: boolean;
    /** "synthesis" for a chat synthesis reply. */
    kind?: string;
    /** The person's message and every reply sent with it share one; absent on older threads. */
    turn_id?: string;
    [key: string]: unknown;
  };
  /** "synthesis" renders the node as a SynthesisTreeNode. */
  type?: string;
  [key: string]: unknown;
}

export interface TreeEdge {
  id: string;
  source: string;
  target: string;
  [key: string]: unknown;
}

export interface TerminationPolicy {
  max_rounds: number;
  convergence_threshold: number | null;
  llm_judge: string | null;
  mode: "any" | "all";
}

/**
 * How debaters see each other: "anonymous" as Participant A/B…, "named" by
 * model id. Anonymous is the default: seeing a peer's model name invites
 * deference to the stronger-sounding brand.
 */
export type PeerLabels = "anonymous" | "named";

export interface DebateDefaults extends TerminationPolicy {
  auto_synthesize: boolean;
  synthesizer_model: string | null;
  peer_labels: PeerLabels;
}

export interface DebateSession {
  session_id: string;
  parent_thread_id: string;
  participants: string[];
  thread_ids: Record<string, string>;
  current_round: number;
  // "interrupted": the socket driving it closed mid-debate; nothing is running.
  status: "running" | "paused" | "completed" | "interrupted";
  termination_policy: TerminationPolicy;
  auto_synthesize: boolean;
  synthesizer_model: string | null;
  /** How participants saw each other; null for sessions stored before the choice existed (named). */
  peer_labels?: PeerLabels | null;
}

/**
 * Debate status as the UI tracks it. "pausing" = pause requested, current round
 * finishing. A debate that stopped early is "converged" when a judge found the
 * models agree, "stable" when their answers only stopped changing.
 */
export type DebateUiStatus =
  | "running"
  | "pausing"
  | "paused"
  | "converged"
  | "stable"
  | "completed"
  | "interrupted";

export interface DebateRoundState {
  round: number;
  responses: Record<string, string>;
  checkpoint_ids: Record<string, string>;
  convergence_score?: number;
}

export interface DebateLane {
  model_id: string;
  /** Human-facing label; falls back to model_id for older payloads. */
  label?: string;
  /**
   * What the other models called this participant ("Participant A") when
   * peers were anonymous; null when they saw model ids. Replies and the
   * argument map refer to participants by it.
   */
  peer_label?: string | null;
  lane_index: number;
  color: string;
}

export interface DebateTreeResponse {
  nodes: TreeNode[];
  edges: TreeEdge[];
  lanes: DebateLane[];
  session_metadata: {
    session_id: string;
    status: string;
    current_round: number;
    /** Stability per round (each model vs its own previous answer), keyed by round number as a string. */
    round_scores?: Record<string, number>;
    max_round?: number;
  };
}
