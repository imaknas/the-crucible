// ─── Shared Types ───────────────────────────────────────────────────────────
// Single source of truth for all shared data types across the frontend.

export interface Message {
  role: string;
  content: string;
  type?: string;
  model?: string;
  streaming?: boolean;
  sources?: { text: string; filename: string }[];
}

export interface Toggles {
  strict_logic: boolean;
  use_rag: boolean;
  cot_enabled: boolean;
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
