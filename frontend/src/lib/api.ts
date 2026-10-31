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
  nodes: any[];
  edges: any[];
  messages: any[];
  current_checkpoint?: string;
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
): Promise<{ filename: string; full_content: string }> {
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
}

export interface ModelFamily {
  key: string;
  label: string;
  color: string;
  available: boolean;
  models: ModelInfo[];
}

export async function fetchModels(): Promise<{
  families: ModelFamily[];
  default_model?: string;
  default_arena_models?: string[];
  default_summarizer?: string;
}> {
  const res = await fetch(`${API_BASE}/models`);
  await ensureOk(res, "Failed to fetch models");
  return res.json();
}

// ─── Debate Sessions ────────────────────────────────────────────

import type {
  DebateSession,
  DebateTreeResponse,
  PeerLabels,
  TerminationPolicy,
} from "@/lib/types";
import { questionMessage, roundLabel } from "@/lib/debateTranscript";

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

// Reconstruct debate messages from sub-thread histories, interleaved by round with headers.
export async function loadDebateMessages(session: DebateSession): Promise<import("@/lib/types").Message[]> {
  const perModel: Record<string, import("@/lib/types").Message[]> = {};
  let originalPrompt = "";

  await Promise.all(
    session.participants.map(async (modelId) => {
      const subThreadId = session.thread_ids[modelId];
      try {
        const data = await fetchHistory(subThreadId);
        const allMsgs = data.messages ?? [];
        // Grab original prompt from first user message of any sub-thread
        if (!originalPrompt) {
          const firstUser = allMsgs.find((m: any) => m.role === "user");
          if (firstUser) originalPrompt = firstUser.content ?? "";
        }
        perModel[modelId] = allMsgs
          .filter((m: any) => m.role === "assistant")
          .map((m: any, i: number) => ({
            id: `restored-${modelId}-r${i}`,
            role: "assistant" as const,
            model: modelId,
            content: m.content ?? "",
            type: "ai",
          }));
      } catch {
        perModel[modelId] = [];
      }
    }),
  );

  const maxRounds = Math.max(0, ...Object.values(perModel).map((msgs) => msgs.length));
  const result: import("@/lib/types").Message[] = [];

  // Original prompt at the top
  if (originalPrompt) result.push(questionMessage(originalPrompt));

  for (let r = 0; r < maxRounds; r++) {
    result.push({
      id: `round-header-${r}`,
      role: "system",
      type: "round_header",
      content: roundLabel(r),
    } as any);
    for (const modelId of session.participants) {
      const msg = perModel[modelId]?.[r];
      if (msg) result.push({ ...msg, id: `restored-${modelId}-r${r}` });
    }
  }

  // Synthesis sub-thread
  const synthId = session.thread_ids["synthesis"] ?? `${session.parent_thread_id}::synthesis`;
  try {
    const synthData = await fetchHistory(synthId);
    const synthMsgs = (synthData.messages ?? []).filter((m: any) => m.role === "assistant");
    if (synthMsgs.length > 0) {
      const last = synthMsgs[synthMsgs.length - 1];
      // The session names its synthesizer once one has run; older sessions
      // whose synthesizer was left as "First participant" store none, and
      // the reply itself says which model wrote it. "synthesis" is the
      // thread key, never a model, and was shown as "Synthesis · synthesis".
      const model = session.synthesizer_model ?? last.model ?? session.participants[0];
      result.push({
        id: "restored-synthesis",
        role: "assistant",
        model,
        ...(last.model_name && !session.synthesizer_model ? { model_name: last.model_name } : {}),
        content: last.content ?? "",
        type: "synthesis",
      } as any);
    }
  } catch { /* no synthesis yet */ }

  return result;
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
