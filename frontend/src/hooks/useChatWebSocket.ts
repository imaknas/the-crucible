import { useState, useRef, useEffect, useCallback } from "react";
import * as api from "@/lib/api";
import { Message, Toggles } from "@/lib/types";
import { isOpen, useSocketFactory } from "@/lib/transport";
import { buildSynthesisPrompt, lastReply, type SynthesisAnswer } from "@/lib/synthesis";

export function useChatWebSocket({
  threadId,
  activeCheckpoint,
  selectedModels,
  toggles,
  summarizer = null,
  documents,
  clearDocuments,
  onHistoryRefreshNeeded,
  setActiveCheckpoint,
  setErrorModals,
  showConfirm,
  modelLabel = (id: string) => id,
  onThreadsChanged,
}: {
  threadId: string | null;
  activeCheckpoint: string | null;
  selectedModels: string[];
  toggles: Toggles;
  /** Model that summarizes long history; null = the backend's default. */
  summarizer?: string | null;
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
  /** Display name for a model ID. */
  modelLabel?: (id: string) => string;
  /**
   * The sidebar's thread list may be stale: a turn finished (a new thread now
   * exists) or the backend titled the thread.
   */
  onThreadsChanged?: () => void;
}) {
  const openSocket = useSocketFactory();
  const [messages, setMessages] = useState<Message[]>([]);
  const [isLoading, setIsLoading] = useState(false);
  // Bumped after an unexpected close so the effect below opens a new socket.
  const [reconnectKey, setReconnectKey] = useState(0);

  const wsRef = useRef<WebSocket | null>(null);
  const streamBufferRef = useRef<Record<string, string>>({});
  const rafRef = useRef<number | null>(null);
  const pendingModelsRef = useRef<Set<string>>(new Set());
  const streamCheckpointsRef = useRef<string[]>([]);
  const expectedModelsCountRef = useRef<number>(0);
  const finishedModelsCountRef = useRef<number>(0);
  // The model writing a synthesis right now, so its bubble streams as one.
  const synthesisModelRef = useRef<string | null>(null);

  // Use refs for items that change frequently but shouldn't trigger WS reconnect
  const activeCheckpointRef = useRef(activeCheckpoint);
  useEffect(() => {
    activeCheckpointRef.current = activeCheckpoint;
  }, [activeCheckpoint]);

  const onHistoryRefreshRef = useRef(onHistoryRefreshNeeded);
  useEffect(() => {
    onHistoryRefreshRef.current = onHistoryRefreshNeeded;
  }, [onHistoryRefreshNeeded]);

  const onThreadsChangedRef = useRef(onThreadsChanged);
  useEffect(() => {
    onThreadsChangedRef.current = onThreadsChanged;
  }, [onThreadsChanged]);

  const modelLabelRef = useRef(modelLabel);
  useEffect(() => {
    modelLabelRef.current = modelLabel;
  }, [modelLabel]);

  const setActiveCheckpointRef = useRef(setActiveCheckpoint);
  useEffect(() => {
    setActiveCheckpointRef.current = setActiveCheckpoint;
  }, [setActiveCheckpoint]);

  useEffect(() => {
    if (!threadId) return;

    const ws = openSocket(api.createWebSocketUrl(threadId));
    wsRef.current = ws;
    let disposed = false;
    let reconnectTimer: ReturnType<typeof setTimeout> | null = null;

    ws.onerror = () => {
      console.error("[WS] Connection error on thread", threadId);
      setIsLoading(false);
      pendingModelsRef.current.clear();
      streamBufferRef.current = {};
      expectedModelsCountRef.current = 0;
      finishedModelsCountRef.current = 0;
      setMessages((prev) =>
        prev.map((m) => (m.streaming ? { ...m, streaming: false } : m)),
      );
    };

    ws.onclose = (event) => {
      if (!event.wasClean && !disposed) {
        console.warn("[WS] Connection closed unexpectedly, code:", event.code);
        setIsLoading(false);
        setMessages((prev) =>
          prev.map((m) => (m.streaming ? { ...m, streaming: false } : m)),
        );
        // e.g. the backend restarted; reconnect instead of staying dead
        // until the user switches threads.
        reconnectTimer = setTimeout(() => setReconnectKey((k) => k + 1), 1500);
      }
    };

    ws.onmessage = (event) => {
      let data: any;
      try {
        data = JSON.parse(event.data);
      } catch {
        console.warn(
          "[WS] Malformed frame, skipping:",
          String(event.data).slice(0, 100),
        );
        return;
      }

      if (data.type === "stream_start") {
        streamBufferRef.current[data.model] = "";
        pendingModelsRef.current.add(data.model);

        setMessages((prev) => [
          ...prev,
          {
            id: `streaming-${data.model}-${Date.now()}`,
            role: "assistant",
            content: "",
            type: data.model === synthesisModelRef.current ? "synthesis" : "ai",
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
                    id: data.checkpoint_id || m.id,
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
              title: data.model ? `${modelLabelRef.current(data.model)} failed` : "API Error",
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
            // Load formatted server messages through reconciliation (no flash
            // because we removed the pre-clear from useHistoryTree).
            onHistoryRefreshRef.current(threadId, undefined, false);
          }

          streamCheckpointsRef.current = [];
          expectedModelsCountRef.current = 0;
          finishedModelsCountRef.current = 0;
          synthesisModelRef.current = null;
          setIsLoading(false);
          // A first turn is what makes a new thread exist on the server.
          onThreadsChangedRef.current?.();
        }
      } else if (data.type === "title_update") {
        // Title updates never overwrite messages: refresh the tree and the
        // sidebar, which otherwise kept the old name until a reload.
        onHistoryRefreshRef.current(threadId, undefined, true);
        onThreadsChangedRef.current?.();
      }
    };

    const pendingModels = pendingModelsRef.current;
    return () => {
      disposed = true;
      if (reconnectTimer) clearTimeout(reconnectTimer);
      ws.close();
      wsRef.current = null;
      if (rafRef.current) {
        cancelAnimationFrame(rafRef.current);
        rafRef.current = null;
      }
      streamBufferRef.current = {};
      pendingModels.clear();
      streamCheckpointsRef.current = [];
      expectedModelsCountRef.current = 0;
      finishedModelsCountRef.current = 0;
      // A self-initiated close is "clean", so onclose won't reset this; without
      // it, switching threads mid-stream left the new thread stuck loading.
      setIsLoading(false);
    };
  }, [threadId, setErrorModals, reconnectKey, openSocket]); // Reconnect only on thread change or after a dropped socket

  const sendInteractiveMessage = async (
    input: string,
    isDeliberation: boolean = false,
  ) => {
    if (isLoading) return;
    const userMessage = input.trim();
    if (!userMessage && !isDeliberation) return; // nothing to do

    // Check the socket before echoing the message, or a failed send leaves a
    // user bubble that was never delivered.
    if (!isOpen(wsRef.current)) {
      showConfirm(
        "Connection Lost",
        "Not connected to the backend. It will reconnect automatically; try again in a moment.",
      );
      return;
    }

    if (userMessage) {
      setMessages((prev) => [
        ...prev,
        {
          id: `user-${Date.now()}`,
          role: "user",
          content: userMessage,
          type: "human",
        },
      ]);
    }

    setIsLoading(true);
    expectedModelsCountRef.current = selectedModels.length;
    finishedModelsCountRef.current = 0;

    selectedModels.forEach((model) => {
      wsRef.current?.send(
        JSON.stringify({
          message: userMessage,
          model: model,
          toggles: toggles,
          summarizer: summarizer ?? undefined,
          documents: documents,
          parent_checkpoint_id: activeCheckpointRef.current,
          is_deliberation: isDeliberation,
        }),
      );
    });
    clearDocuments();
  };

  /**
   * Merge sibling answers into one, written by `model` (default: the first
   * selected model). The turn is sent as type "synthesis", which the backend
   * tags so the reply shows as a synthesis in the tree and the transcript.
   */
  const synthesizeConsensus = async (
    answers: SynthesisAnswer[],
    parentId: string | null,
    model?: string | null,
  ) => {
    if (isLoading) return;
    const synthesizer = model || selectedModels[0];
    if (!synthesizer || !isOpen(wsRef.current)) return;
    setIsLoading(true);
    expectedModelsCountRef.current = 1; // Synthesis is a single model call
    finishedModelsCountRef.current = 0;
    synthesisModelRef.current = synthesizer;

    wsRef.current?.send(
      JSON.stringify({
        message: buildSynthesisPrompt(answers),
        model: synthesizer,
        toggles: toggles,
        summarizer: summarizer ?? undefined,
        documents: documents,
        parent_checkpoint_id: parentId,
        type: "synthesis",
      }),
    );
    clearDocuments();
  };

  /**
   * Synthesize the answers at these checkpoints. Each branch's full reply is
   * read from the server: only the branch on screen is in `messages`, and the
   * tree nodes carry 40-character labels.
   */
  const synthesizeBranches = async (
    checkpointIds: string[],
    parentId: string | null,
    model?: string | null,
  ) => {
    if (!threadId || isLoading) return;
    const label = modelLabelRef.current;
    const answers = (
      await Promise.all(
        checkpointIds.map((id) =>
          api
            .fetchHistory(threadId, id)
            .then((data) => lastReply(data.messages ?? [], label))
            .catch(() => null),
        ),
      )
    ).filter((a): a is SynthesisAnswer => !!a);
    if (answers.length < 2) {
      setErrorModals((prev) => [
        ...prev,
        {
          id: Math.random().toString(36).substring(7),
          title: "Couldn't synthesize",
          details: "Fewer than two answers could be loaded from the server.",
          suggestion: "Check the connection to the backend and try again.",
        },
      ]);
      return;
    }
    await synthesizeConsensus(answers, parentId, model);
  };

  const stopStreaming = useCallback(() => {
    if (isOpen(wsRef.current)) {
      wsRef.current?.send(JSON.stringify({ type: "stop" }));
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
    synthesizeBranches,
    stopStreaming,
  };
}
