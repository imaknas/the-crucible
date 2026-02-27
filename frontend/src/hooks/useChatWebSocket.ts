import { useState, useRef, useEffect, useCallback } from "react";
import * as api from "@/lib/api";

export function useChatWebSocket({
  threadId,
  activeCheckpoint,
  selectedModels,
  toggles,
  documents,
  clearDocuments,
  onHistoryRefreshNeeded,
  setActiveCheckpoint,
  setErrorModals,
  showConfirm,
}: {
  threadId: string | null;
  activeCheckpoint: string | null;
  selectedModels: string[];
  toggles: any;
  documents: Record<string, string>;
  clearDocuments: () => void;
  onHistoryRefreshNeeded: (
    threadId: string,
    nodeId?: string,
    skipMessages?: boolean,
  ) => void;
  setActiveCheckpoint: (cpId: string | null) => void;
  setErrorModals: React.Dispatch<React.SetStateAction<any[]>>;
  showConfirm: (title: string, message: string) => Promise<boolean>;
}) {
  const [messages, setMessages] = useState<any[]>([]);
  const [isLoading, setIsLoading] = useState(false);

  const wsRef = useRef<WebSocket | null>(null);
  const streamBufferRef = useRef<Record<string, string>>({});
  const rafRef = useRef<number | null>(null);
  const pendingModelsRef = useRef<Set<string>>(new Set());
  const streamCheckpointsRef = useRef<string[]>([]);
  const expectedModelsCountRef = useRef<number>(0);
  const finishedModelsCountRef = useRef<number>(0);

  // Use refs for items that change frequently but shouldn't trigger WS reconnect
  const activeCheckpointRef = useRef(activeCheckpoint);
  useEffect(() => {
    activeCheckpointRef.current = activeCheckpoint;
  }, [activeCheckpoint]);

  const onHistoryRefreshRef = useRef(onHistoryRefreshNeeded);
  useEffect(() => {
    onHistoryRefreshRef.current = onHistoryRefreshNeeded;
  }, [onHistoryRefreshNeeded]);

  const setActiveCheckpointRef = useRef(setActiveCheckpoint);
  useEffect(() => {
    setActiveCheckpointRef.current = setActiveCheckpoint;
  }, [setActiveCheckpoint]);

  useEffect(() => {
    if (!threadId) return;

    const ws = new WebSocket(api.createWebSocketUrl(threadId));
    wsRef.current = ws;

    ws.onmessage = (event) => {
      const data = JSON.parse(event.data);

      if (data.type === "stream_start") {
        streamBufferRef.current[data.model] = "";
        pendingModelsRef.current.add(data.model);

        setMessages((prev) => [
          ...prev,
          {
            role: "assistant",
            content: "",
            type: "ai",
            model: data.model,
            streaming: true,
          },
        ]);
      } else if (data.type === "stream_token") {
        streamBufferRef.current[data.model] =
          (streamBufferRef.current[data.model] || "") + data.token;

        if (!rafRef.current) {
          rafRef.current = requestAnimationFrame(() => {
            rafRef.current = null;
            const buf = streamBufferRef.current;
            setMessages((prev) => {
              let changed = false;
              const updated = prev.map((m) => {
                if (
                  m.streaming &&
                  m.model &&
                  buf[m.model] !== undefined &&
                  m.content !== buf[m.model]
                ) {
                  changed = true;
                  return { ...m, content: buf[m.model] };
                }
                return m;
              });
              return changed ? updated : prev;
            });
          });
        }
      } else if (data.type === "stream_end" || data.type === "error") {
        if (data.type === "stream_end") {
          pendingModelsRef.current.delete(data.model);
          setMessages((prev) =>
            prev.map((m) =>
              m.streaming && m.model === data.model
                ? {
                    ...m,
                    content: streamBufferRef.current[data.model] || m.content,
                    streaming: false,
                  }
                : m,
            ),
          );
          delete streamBufferRef.current[data.model];
          streamCheckpointsRef.current.push(data.checkpoint_id);
        } else if (data.type === "error") {
          if (data.model) {
            pendingModelsRef.current.delete(data.model);
            delete streamBufferRef.current[data.model];
            setMessages((prev) =>
              prev.filter((m) => !(m.streaming && m.model === data.model)),
            );
          }
          setErrorModals((prev) => [
            ...prev,
            {
              id: Math.random().toString(36).substring(7),
              title: data.model ? `${data.model} Error` : "API Error",
              details: data.message,
              suggestion: "Check your API keys and model parameters.",
            },
          ]);
        }

        finishedModelsCountRef.current += 1;

        if (finishedModelsCountRef.current >= expectedModelsCountRef.current) {
          if (rafRef.current) {
            cancelAnimationFrame(rafRef.current);
            rafRef.current = null;
          }

          if (streamCheckpointsRef.current.length > 0) {
            const firstCp = streamCheckpointsRef.current[0];
            setActiveCheckpointRef.current(firstCp);
            // If we had multiple models, tell history fetcher to NOT overwrite messages
            const skipMessages = expectedModelsCountRef.current > 1;
            onHistoryRefreshRef.current(threadId, undefined, skipMessages);
          }

          streamCheckpointsRef.current = [];
          expectedModelsCountRef.current = 0;
          finishedModelsCountRef.current = 0;
          setIsLoading(false);
        }
      } else if (data.type === "chat_update") {
        // Only allow chat_update to overwrite if we are not currently in a multi-model stream
        if (
          expectedModelsCountRef.current === 0 ||
          finishedModelsCountRef.current >= expectedModelsCountRef.current
        ) {
          setMessages(data.messages);
          setActiveCheckpointRef.current(data.checkpoint_id);
          onHistoryRefreshRef.current(threadId);
          setIsLoading(false);
        } else {
          console.log(
            "[WS] Ignoring chat_update during parallel streaming to prevent bubble flickering.",
          );
        }
      } else if (data.type === "title_update") {
        // Defer refresh or skip messages if we are in a parallel context
        const isParallelFlush =
          expectedModelsCountRef.current > 1 ||
          finishedModelsCountRef.current > 0;
        if (isParallelFlush) {
          console.log(
            "[WS] Deferring title_update message refresh for parallel context.",
          );
          onHistoryRefreshRef.current(threadId, undefined, true);
        } else {
          onHistoryRefreshRef.current(threadId);
        }
      }
    };

    const pendingModels = pendingModelsRef.current;
    return () => {
      ws.close();
      wsRef.current = null;
      if (rafRef.current) {
        cancelAnimationFrame(rafRef.current);
        rafRef.current = null;
      }
      streamBufferRef.current = {};
      pendingModels.clear();
      expectedModelsCountRef.current = 0;
      finishedModelsCountRef.current = 0;
    };
  }, [threadId, setErrorModals]); // Extreme stability: only reconnect if threadId changes

  const sendInteractiveMessage = async (
    input: string,
    isDeliberation: boolean = false,
  ) => {
    if (isLoading) return;
    const userMessage = input.trim();
    if (userMessage || isDeliberation) {
      if (userMessage) {
        setMessages((prev) => [
          ...prev,
          { role: "user", content: userMessage, type: "human" },
        ]);
      }
    } else {
      return; // nothing to do
    }

    setIsLoading(true);
    expectedModelsCountRef.current = selectedModels.length;
    finishedModelsCountRef.current = 0;

    if (wsRef.current && wsRef.current.readyState === WebSocket.OPEN) {
      selectedModels.forEach((model) => {
        wsRef.current?.send(
          JSON.stringify({
            message: userMessage,
            model: model,
            toggles: toggles,
            documents: documents,
            parent_checkpoint_id: activeCheckpointRef.current,
            is_deliberation: isDeliberation,
          }),
        );
      });
      clearDocuments();
    } else {
      setIsLoading(false);
      showConfirm(
        "Connection Lost",
        "WebSocket is not connected. Please refresh the page or select a thread.",
      );
    }
  };

  const synthesizeConsensus = async (
    contents: string[],
    parentId: string | null,
  ) => {
    if (isLoading) return;
    setIsLoading(true);
    expectedModelsCountRef.current = 1; // Synthesis is a single model call
    finishedModelsCountRef.current = 0;

    const formattedContents = contents
      .map((c, i) => `Model ${i + 1}: ${c}`)
      .join("\n\n");
    const synthesisPrompt = `I have received perspectives from multiple models:\n${formattedContents}\n\nPlease act as the Crucible Lead. Synthesize these viewpoints into a single, cohesive consensus that resolves contradictions and extracts the highest quality insights. Maintain an academic and rigorous tone.`;

    if (wsRef.current && wsRef.current.readyState === WebSocket.OPEN) {
      wsRef.current.send(
        JSON.stringify({
          message: synthesisPrompt,
          model: "gemini-3-flash-preview",
          toggles: toggles,
          documents: documents,
          parent_checkpoint_id: parentId,
          type: "synthesis",
        }),
      );
      clearDocuments();
    } else {
      setIsLoading(false);
    }
  };

  const stopStreaming = useCallback(() => {
    if (wsRef.current && wsRef.current.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify({ type: "stop" }));
    }
    // Optimistic UI reset
    setIsLoading(false);
    pendingModelsRef.current.clear();
    streamBufferRef.current = {};
    expectedModelsCountRef.current = 0;
    finishedModelsCountRef.current = 0;
    setMessages((prev) =>
      prev.map((m) => (m.streaming ? { ...m, streaming: false } : m)),
    );
  }, []);

  return {
    messages,
    setMessages,
    isLoading,
    sendInteractiveMessage,
    synthesizeConsensus,
    stopStreaming,
  };
}
