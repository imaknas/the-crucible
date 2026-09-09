// ─── Shared Types ───────────────────────────────────────────────────────────
// Single source of truth for all shared data types across the frontend.

export interface Message {
  id: string; // Stable client-side key; updated to server checkpoint_id after stream_end
  role: string;
  content: string;
  type?: string;
  model?: string;
  streaming?: boolean;
  sources?: { text: string; filename: string }[];
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
    thesis_preview?: string;
    has_thoughts?: boolean;
    /** Longer excerpt, revealed when the node is selected. */
    preview?: string;
    /** Debate mode: lane column, debate round, and the family colour. */
    lane_index?: number;
    round_num?: number;
    model_color?: string;
    pending?: boolean;
    [key: string]: unknown;
  };
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

export interface DebateDefaults extends TerminationPolicy {
  auto_synthesize: boolean;
  synthesizer_model: string | null;
}

export interface DebateSession {
  session_id: string;
  parent_thread_id: string;
  participants: string[];
  thread_ids: Record<string, string>;
  current_round: number;
  status: "running" | "paused" | "completed";
  termination_policy: TerminationPolicy;
  auto_synthesize: boolean;
  synthesizer_model: string | null;
}

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
    /** Convergence score per round, keyed by round number as a string. */
    round_scores?: Record<string, number>;
    max_round?: number;
  };
}
