export const API_BASE =
  process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";
export const WS_BASE = API_BASE.replace(/^http/, "ws");

// ─── Thread CRUD ────────────────────────────────────────────────

export async function listThreads(): Promise<{
  threads: { id: string; title: string }[];
}> {
  const res = await fetch(`${API_BASE}/threads`);
  if (!res.ok) throw new Error("Failed to list threads");
  return res.json();
}

export async function deleteThread(id: string): Promise<void> {
  const res = await fetch(`${API_BASE}/threads/${id}`, { method: "DELETE" });
  if (!res.ok) throw new Error("Failed to delete thread");
}

export async function renameThread(id: string, title: string): Promise<void> {
  const res = await fetch(`${API_BASE}/threads/${id}/rename`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ title }),
  });
  if (!res.ok) throw new Error("Failed to rename thread");
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
    ? `${API_BASE}/history/${threadId}?checkpoint_id=${encodeURIComponent(checkpointId)}`
    : `${API_BASE}/history/${threadId}`;
  const res = await fetch(url);
  if (!res.ok) throw new Error("Failed to fetch history");
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
    `${API_BASE}/history/${threadId}/search?q=${encodeURIComponent(query)}`,
  );
  if (!res.ok) throw new Error("Search failed");
  return res.json();
}

export async function saveNodePositions(
  threadId: string,
  positions: { node_id: string; x: number; y: number }[],
): Promise<void> {
  await fetch(`${API_BASE}/history/${threadId}/positions`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(positions),
  });
}

export async function deleteCheckpoint(
  threadId: string,
  checkpointId: string,
): Promise<void> {
  const res = await fetch(
    `${API_BASE}/history/${threadId}/checkpoints/${checkpointId}`,
    {
      method: "DELETE",
    },
  );
  if (!res.ok) throw new Error("Failed to delete checkpoint");
}

// ─── File Upload ────────────────────────────────────────────────

export async function uploadDocument(
  file: File,
  threadId: string,
): Promise<{ filename: string; full_content: string }> {
  const formData = new FormData();
  formData.append("file", file);
  formData.append("thread_id", threadId);
  const res = await fetch(`${API_BASE}/upload`, {
    method: "POST",
    body: formData,
  });
  if (!res.ok) throw new Error("Upload failed");
  return res.json();
}

// ─── WebSocket ──────────────────────────────────────────────────

export function createWebSocketUrl(threadId: string): string {
  return `${WS_BASE}/ws/${threadId}`;
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
}> {
  const res = await fetch(`${API_BASE}/models`);
  if (!res.ok) throw new Error("Failed to fetch models");
  return res.json();
}

// ─── Debate Sessions ────────────────────────────────────────────

import type {
  DebateSession,
  DebateTreeResponse,
  TerminationPolicy,
} from "@/lib/types";

export async function createDebateSession(params: {
  parent_thread_id: string;
  participants: string[];
  termination_policy: TerminationPolicy;
  auto_synthesize: boolean;
  synthesizer_model: string | null;
}): Promise<DebateSession> {
  const res = await fetch(`${API_BASE}/debate/sessions`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(params),
  });
  if (!res.ok) throw new Error("Failed to create debate session");
  return res.json();
}

export async function fetchDebateSession(
  sessionId: string,
): Promise<DebateSession> {
  const res = await fetch(`${API_BASE}/debate/sessions/${sessionId}`);
  if (!res.ok) throw new Error("Failed to fetch debate session");
  return res.json();
}

export async function listDebateSessions(
  parentThreadId?: string,
): Promise<DebateSession[]> {
  const url = parentThreadId
    ? `${API_BASE}/debate/sessions?parent_thread_id=${encodeURIComponent(parentThreadId)}`
    : `${API_BASE}/debate/sessions`;
  const res = await fetch(url);
  if (!res.ok) throw new Error("Failed to list debate sessions");
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
  if (originalPrompt) {
    result.push({
      id: "restored-prompt",
      role: "user",
      content: originalPrompt,
      type: "human",
    } as any);
  }

  for (let r = 0; r < maxRounds; r++) {
    result.push({
      id: `round-header-${r}`,
      role: "system",
      type: "round_header",
      content: `Round ${r + 1}`,
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
      result.push({
        id: "restored-synthesis",
        role: "assistant",
        model: session.synthesizer_model ?? "synthesis",
        content: synthMsgs[synthMsgs.length - 1].content ?? "",
        type: "synthesis",
      } as any);
    }
  } catch { /* no synthesis yet */ }

  return result;
}

export async function fetchDebateTree(
  sessionId: string,
): Promise<DebateTreeResponse> {
  const res = await fetch(`${API_BASE}/debate/sessions/${sessionId}/tree`);
  if (!res.ok) throw new Error("Failed to fetch debate tree");
  return res.json();
}

export function createDebateWebSocketUrl(sessionId: string): string {
  return `${WS_BASE}/debate/ws/${sessionId}`;
}

// ─── Config / API Keys ───────────────────────────────────────────

export interface KeyInfo {
  set: boolean;
  masked: string;
}

export async function fetchKeyStatus(): Promise<Record<string, KeyInfo>> {
  const res = await fetch(`${API_BASE}/config/keys`);
  if (!res.ok) throw new Error("Failed to fetch key status");
  return res.json();
}

export async function saveApiKeys(keys: Record<string, string>): Promise<void> {
  const res = await fetch(`${API_BASE}/config/keys`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ keys }),
  });
  if (!res.ok) throw new Error("Failed to save API keys");
}
