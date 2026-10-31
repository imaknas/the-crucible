import { ensureOk } from "@/lib/errors";

export const API_BASE =
  process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";
export const WS_BASE = API_BASE.replace(/^http/, "ws");


// ─── Thread CRUD ────────────────────────────────────────────────

export async function listThreads(): Promise<{
  threads: { id: string; title: string }[];
}> {
  const res = await fetch(`${API_BASE}/threads`);
  await ensureOk(res, "Failed to list threads");
  return res.json();
}

export async function deleteThread(id: string): Promise<void> {
  const res = await fetch(`${API_BASE}/threads/${encodeURIComponent(id)}`, { method: "DELETE" });
  await ensureOk(res, "Failed to delete thread");
}

export async function renameThread(id: string, title: string): Promise<void> {
  const res = await fetch(`${API_BASE}/threads/${encodeURIComponent(id)}/rename`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ title }),
  });
  await ensureOk(res, "Failed to rename thread");
}

// ─── History & Tree ─────────────────────────────────────────────

export interface HistoryResponse {
  nodes: TreeNode[];
  edges: TreeEdge[];
  messages: Message[];
  /** The node the returned path ends at; null for a thread with no checkpoints. */
  current_checkpoint?: string | null;
}

export async function fetchHistory(
  threadId: string,
  checkpointId?: string,
): Promise<HistoryResponse> {
  const url = checkpointId
    ? `${API_BASE}/history/${encodeURIComponent(threadId)}?checkpoint_id=${encodeURIComponent(checkpointId)}`
    : `${API_BASE}/history/${encodeURIComponent(threadId)}`;
  const res = await fetch(url);
  await ensureOk(res, "Failed to fetch history");
  return res.json();
}

export async function searchHistory(
  threadId: string,
  query: string,
): Promise<{
  results: {
    checkpoint_id: string;
    role: string;
    model?: string;
    excerpt: string;
  }[];
}> {
  const res = await fetch(
    `${API_BASE}/history/${encodeURIComponent(threadId)}/search?q=${encodeURIComponent(query)}`,
  );
  await ensureOk(res, "Search failed");
  return res.json();
}

export async function saveNodePositions(
  threadId: string,
  positions: { node_id: string; x: number; y: number }[],
): Promise<void> {
  const res = await fetch(`${API_BASE}/history/${encodeURIComponent(threadId)}/positions`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(positions),
  });
  await ensureOk(res, "Failed to save node positions");
}

export async function deleteCheckpoint(
  threadId: string,
  checkpointId: string,
): Promise<void> {
  const res = await fetch(
    `${API_BASE}/history/${encodeURIComponent(threadId)}/checkpoints/${encodeURIComponent(checkpointId)}`,
    {
      method: "DELETE",
    },
  );
  await ensureOk(res, "Failed to delete checkpoint");
}

// ─── File Upload ────────────────────────────────────────────────

// The backend refuses form, text and untyped POSTs without this header: such
// requests skip the CORS preflight, so another site could send them from the
// user's browser. A custom header forces the preflight, which CORS answers
// only for allowed origins.
export const CLIENT_HEADERS = { "X-Crucible-Client": "1" } as const;

export async function uploadDocument(
  file: File,
  threadId: string,
): Promise<{ filename: string }> {
  const formData = new FormData();
  formData.append("file", file);
  formData.append("thread_id", threadId);
  const res = await fetch(`${API_BASE}/upload`, {
    method: "POST",
    headers: CLIENT_HEADERS,
    body: formData,
  });
  await ensureOk(res, "Upload failed");
  return res.json();
}

// ─── WebSocket ──────────────────────────────────────────────────

export function createWebSocketUrl(threadId: string): string {
  return `${WS_BASE}/ws/${encodeURIComponent(threadId)}`;
}

// ─── Models ─────────────────────────────────────────────────────

export interface ModelInfo {
  id: string;
  name: string;
  desc: string;
  /** The provider's own web search works for this model. */
  native_search?: boolean;
}

export interface ModelFamily {
  key: string;
  label: string;
  color: string;
  /** The API key this family needs, e.g. "ANTHROPIC_API_KEY". */
  env_key?: string;
  available: boolean;
  models: ModelInfo[];
}

export async function fetchModels(): Promise<{
  families: ModelFamily[];
  default_model?: string;
  default_arena_models?: string[];
  default_summarizer?: string;
  limits?: Partial<import("@/lib/catalog").Limits>;
}> {
  const res = await fetch(`${API_BASE}/models`);
  await ensureOk(res, "Failed to fetch models");
  return res.json();
}

// ─── Debate Sessions ────────────────────────────────────────────

import type {
  Message,
  TreeEdge,
  TreeNode,
  DebateSession,
  DebateTranscript,
  DebateTreeResponse,
  PeerLabels,
  TerminationPolicy,
} from "@/lib/types";

export async function createDebateSession(params: {
  parent_thread_id: string;
  participants: string[];
  termination_policy: TerminationPolicy;
  auto_synthesize: boolean;
  synthesizer_model: string | null;
  peer_labels: PeerLabels;
}): Promise<DebateSession> {
  const res = await fetch(`${API_BASE}/debate/sessions`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(params),
  });
  await ensureOk(res, "Failed to create debate session");
  return res.json();
}

export async function fetchDebateSession(
  sessionId: string,
): Promise<DebateSession> {
  const res = await fetch(`${API_BASE}/debate/sessions/${encodeURIComponent(sessionId)}`);
  await ensureOk(res, "Failed to fetch debate session");
  return res.json();
}

export async function listDebateSessions(
  parentThreadId?: string,
): Promise<DebateSession[]> {
  const url = parentThreadId
    ? `${API_BASE}/debate/sessions?parent_thread_id=${encodeURIComponent(parentThreadId)}`
    : `${API_BASE}/debate/sessions`;
  const res = await fetch(url);
  await ensureOk(res, "Failed to list debate sessions");
  return res.json();
}

/**
 * The whole debate in one request: question, rounds aligned by number (a
 * failed model has an `errors` entry, not a shifted index), injected
 * messages and the synthesis. It replaces rebuilding the transcript from
 * every sub-thread's history, one request per participant.
 */
export async function fetchDebateTranscript(sessionId: string): Promise<DebateTranscript> {
  const res = await fetch(`${API_BASE}/debate/sessions/${encodeURIComponent(sessionId)}/transcript`);
  await ensureOk(res, "Failed to load the debate transcript");
  return res.json();
}

export async function deleteDebateSession(sessionId: string): Promise<void> {
  const res = await fetch(`${API_BASE}/debate/sessions/${encodeURIComponent(sessionId)}`, {
    method: "DELETE",
  });
  await ensureOk(res, "Failed to delete debate session");
}

export async function fetchDebateTree(
  sessionId: string,
): Promise<DebateTreeResponse> {
  const res = await fetch(`${API_BASE}/debate/sessions/${encodeURIComponent(sessionId)}/tree`);
  await ensureOk(res, "Failed to fetch debate tree");
  return res.json();
}

export function createDebateWebSocketUrl(sessionId: string): string {
  return `${WS_BASE}/debate/ws/${encodeURIComponent(sessionId)}`;
}

// ─── Config / API Keys ───────────────────────────────────────────

export interface KeyInfo {
  set: boolean;
  masked: string;
}

export async function fetchKeyStatus(): Promise<Record<string, KeyInfo>> {
  const res = await fetch(`${API_BASE}/config/keys`);
  await ensureOk(res, "Failed to fetch key status");
  return res.json();
}

export async function saveApiKeys(keys: Record<string, string>): Promise<void> {
  const res = await fetch(`${API_BASE}/config/keys`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ keys }),
  });
  // The backend explains rejections (e.g. localhost-only, invalid characters).
  await ensureOk(res, "Failed to save API keys");
}
