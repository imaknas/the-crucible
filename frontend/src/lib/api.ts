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
    ? `${API_BASE}/history/${threadId}?checkpoint_id=${checkpointId}`
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

export async function uploadFile(
  file: File,
): Promise<{ filename: string; full_content: string }> {
  const formData = new FormData();
  formData.append("file", file);
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

export async function fetchModels(): Promise<{ families: ModelFamily[] }> {
  const res = await fetch(`${API_BASE}/models`);
  if (!res.ok) throw new Error("Failed to fetch models");
  return res.json();
}
