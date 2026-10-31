import { useState, useRef, useEffect, useCallback } from "react";
import * as api from "@/lib/api";
import { Message, ModelError, Toggles } from "@/lib/types";
import { isOpen, useSocketFactory, whenOpen } from "@/lib/transport";
import { contextFields } from "@/lib/runContext";
import { markStopped } from "@/lib/messages";
import { startLiveTurn, stopLiveTurn, updateLiveReply, type LiveTurn } from "@/lib/turns";
import type { PushToast } from "@/hooks/useToasts";

const NOT_CONNECTED = "Not connected to the backend. It reconnects by itself; try again in a moment.";

export function useChatWebSocket({
  threadId,
  parentCheckpoint,
  selectedModels,
  respondingModels = selectedModels,
  toggles,
  summarizer = null,
  systemPrompt = null,
  documentNames,
  clearDocuments,
  onTurnSettled,
  setErrorModals,
  pushToast,
  onThreadsChanged,
}: {
  threadId: string | null;
  /**
   * The node the person chose to continue from, or null for the latest
   * turn: the backend then continues every model from its own reply there.
   */
  parentCheckpoint: string | null;
  /** The Control Panel's selection; its first model writes a synthesis by default. */
  selectedModels: string[];
  /** Who answers the next message (lib/replyTarget); default: the selection. */
  respondingModels?: string[];
  toggles: Toggles;
  /** Model that summarizes long history; null = the backend's default. */
  summarizer?: string | null;
  /** The person's system prompt; null = models get none. */
  systemPrompt?: string | null;
  /** Files attached to this turn, by name; the backend reads them from the thread. */
  documentNames: string[];
  clearDocuments: () => void;
  /**
   * Every model of a turn has finished. The next message continues the
   * latest turn again; the caller resets the branch point and reloads.
   */
  onTurnSettled: (threadId: string) => void;
  setErrorModals: React.Dispatch<React.SetStateAction<any[]>>;
  /** Notices, e.g. that a message couldn't be sent. */
  pushToast: PushToast;
  /**
   * The sidebar's thread list may be stale: a turn finished (a new thread now
   * exists) or the backend titled the thread.
   */
  onThreadsChanged?: () => void;
}) {
  const openSocket = useSocketFactory();
  const [messages, setMessages] = useState<Message[]>([]);
  // Per-model failures of the latest turn. Kept apart from `messages`, which
  // the post-turn history refresh replaces with the server's copy.
  const [modelErrors, setModelErrors] = useState<ModelError[]>([]);
  // The frame each model was last sent, for Retry.
  const sentFramesRef = useRef<Record<string, Record<string, unknown>>>({});
  const [isLoading, setIsLoading] = useState(false);
  // Bumped after an unexpected close so the effect below opens a new socket.
  const [reconnectKey, setReconnectKey] = useState(0);

  const wsRef = useRef<WebSocket | null>(null);
  // A send waiting for its socket to open; a second click meanwhile is ignored.
  const waitingRef = useRef(false);
  const streamBufferRef = useRef<Record<string, string>>({});
  const rafRef = useRef<number | null>(null);
  const pendingModelsRef = useRef<Set<string>>(new Set());
  const streamCheckpointsRef = useRef<string[]>([]);
  const expectedModelsCountRef = useRef<number>(0);
  const finishedModelsCountRef = useRef<number>(0);
  // The model writing a synthesis right now, so its bubble streams as one.
  const synthesisModelRef = useRef<string | null>(null);

  // Full text of each reply streamed here, by tree node id: the compare
  // cards show it whole instead of the node's excerpt.
  const [replyTexts, setReplyTexts] = useState<Record<string, string>>({});
  // A turn sent to several models streams into compare cards (lib/turns),
  // not bubbles; these are the models it streams for.
  const [liveTurn, setLiveTurn] = useState<LiveTurn | null>(null);
  const liveModelsRef = useRef<Set<string>>(new Set());

  // Use refs for items that change frequently but shouldn't trigger WS reconnect
  const parentCheckpointRef = useRef(parentCheckpoint);
  useEffect(() => {
    parentCheckpointRef.current = parentCheckpoint;
  }, [parentCheckpoint]);

  const onThreadsChangedRef = useRef(onThreadsChanged);
  useEffect(() => {
    onThreadsChangedRef.current = onThreadsChanged;
  }, [onThreadsChanged]);

  const onTurnSettledRef = useRef(onTurnSettled);
  useEffect(() => {
    onTurnSettledRef.current = onTurnSettled;
  }, [onTurnSettled]);

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
      setMessages(markStopped);
      setLiveTurn(stopLiveTurn);
    };

    ws.onclose = (event) => {
      if (!event.wasClean && !disposed) {
        console.warn("[WS] Connection closed unexpectedly, code:", event.code);
        setIsLoading(false);
        setMessages(markStopped);
        setLiveTurn(stopLiveTurn);
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
        // Pin the parent the backend actually forked from (a first turn is
        // sent without one), so a retry lands on the same branch point.
        const sent = sentFramesRef.current[data.model];
        if (sent && data.parent_checkpoint_id) sent.parent_checkpoint_id = data.parent_checkpoint_id;
        streamBufferRef.current[data.model] = "";
        pendingModelsRef.current.add(data.model);

        if (liveModelsRef.current.has(data.model) && data.model !== synthesisModelRef.current) {
          setLiveTurn((turn) =>
            turn &&
            updateLiveReply(turn, data.model, {
              content: "",
              streaming: true,
              stopped: false,
              error: null,
              turn_id: data.turn_id ?? null,
              ...(data.model_color ? { model_color: data.model_color } : {}),
            }),
          );
          return;
        }

        setMessages((prev) => [
          ...prev,
          {
            id: `streaming-${data.model}-${Date.now()}`,
            role: "assistant",
            content: "",
            type: data.model === synthesisModelRef.current ? "synthesis" : "ai",
            model: data.model,
            ...(data.model_color ? { model_color: data.model_color } : {}),
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
            setLiveTurn((turn) => {
              if (!turn) return turn;
              let next = turn;
              for (const r of turn.replies) {
                if (r.streaming && buf[r.model] !== undefined && r.content !== buf[r.model]) {
                  next = updateLiveReply(next, r.model, { content: buf[r.model] });
                }
              }
              return next;
            });
          });
        }
      } else if (data.type === "stream_end" || data.type === "error") {
        // A reply of the multi-model turn on screen (not a synthesis by one of its models).
        const inLiveTurn = liveModelsRef.current.has(data.model) && data.model !== synthesisModelRef.current;
        if (data.type === "stream_end") {
          pendingModelsRef.current.delete(data.model);
          const content = streamBufferRef.current[data.model] ?? "";
          setMessages((prev) =>
            prev.map((m) =>
              m.streaming && m.model === data.model
                ? {
                    ...m,
                    // The tree node id: the history refresh keys the same reply by it.
                    id: data.checkpoint_id || m.id,
                    checkpoint_id: data.checkpoint_id ?? null,
                    turn_id: data.turn_id ?? null,
                    ...(data.model_color ? { model_color: data.model_color } : {}),
                    content: content || m.content,
                    streaming: false,
                  }
                : m,
            ),
          );
          if (inLiveTurn) setLiveTurn((turn) =>
            turn &&
            updateLiveReply(turn, data.model, {
              ...(content ? { content } : {}),
              streaming: false,
              checkpoint_id: data.checkpoint_id ?? null,
              ...(data.turn_id ? { turn_id: data.turn_id } : {}),
            }),
          );
          delete streamBufferRef.current[data.model];
          if (data.checkpoint_id) {
            streamCheckpointsRef.current.push(data.checkpoint_id);
            if (content) setReplyTexts((prev) => ({ ...prev, [data.checkpoint_id]: content }));
          }
        } else if (data.type === "error") {
          if (data.model) {
            // One model failing is shown inline, next to its siblings'
            // replies, with a Retry; a modal per model covered the answers
            // that did arrive.
            pendingModelsRef.current.delete(data.model);
            delete streamBufferRef.current[data.model];
            setMessages((prev) =>
              prev.filter((m) => !(m.streaming && m.model === data.model)),
            );
            if (inLiveTurn) setLiveTurn((turn) =>
              turn &&
              updateLiveReply(turn, data.model, {
                streaming: false,
                error: String(data.message ?? "The model call failed."),
              }),
            );
            const frame = {
              ...(sentFramesRef.current[data.model] ?? { model: data.model }),
              ...(data.parent_checkpoint_id ? { parent_checkpoint_id: data.parent_checkpoint_id } : {}),
            };
            setModelErrors((prev) => [
              ...prev.filter((e) => e.model !== data.model),
              {
                id: `error-${data.model}-${Date.now()}`,
                model: data.model,
                message: String(data.message ?? "The model call failed."),
                frame,
              },
            ]);
          } else {
            setErrorModals((prev) => [
              ...prev,
              {
                id: Math.random().toString(36).substring(7),
                title: "The backend reported an error",
                details: data.message,
                suggestion: "Check your API keys in the Control Panel and that the backend is running.",
              },
            ]);
          }
        }

        finishedModelsCountRef.current += 1;

        if (finishedModelsCountRef.current >= expectedModelsCountRef.current) {
          if (rafRef.current) {
            cancelAnimationFrame(rafRef.current);
            rafRef.current = null;
          }

          if (streamCheckpointsRef.current.length > 0) {
            // No reply becomes the branch point: the next message continues
            // the latest turn, every model from its own reply. Pinning the
            // first reply here sent every model's next turn after one model.
            onTurnSettledRef.current(threadId);
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
        // The title shows only in the sidebar, which otherwise kept the old
        // name until a reload. The tree is left alone: reloading it here
        // moved the transcript to the thread's head mid-turn.
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
      sentFramesRef.current = {};
      setModelErrors([]);
      setReplyTexts({});
      setLiveTurn(null);
      liveModelsRef.current = new Set();
      streamCheckpointsRef.current = [];
      expectedModelsCountRef.current = 0;
      finishedModelsCountRef.current = 0;
      // A self-initiated close is "clean", so onclose won't reset this; without
      // it, switching threads mid-stream left the new thread stuck loading.
      setIsLoading(false);
    };
  }, [threadId, setErrorModals, reconnectKey, openSocket]); // Reconnect only on thread change or after a dropped socket

  /**
   * `continuesDebate`: the finished debate on screen this turn follows. The
   * backend writes that debate onto the thread and forks from it; without
   * it the models saw nothing of the debate the person just read.
   */
  const sendInteractiveMessage = async (
    input: string,
    isDeliberation: boolean = false,
    continuesDebate: string | null = null,
  ): Promise<boolean> => {
    if (isLoading || waitingRef.current) return false;
    const userMessage = input.trim();
    if (!userMessage && !isDeliberation) return false; // nothing to do

    // Check the socket before echoing the message, or a failed send leaves a
    // user bubble that was never delivered.
    waitingRef.current = true;
    const open = await whenOpen(() => wsRef.current).finally(() => {
      waitingRef.current = false;
    });
    if (!open) {
      pushToast(NOT_CONNECTED, "error", "Not sent");
      return false;
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
    // Several models: their replies stream into cards; one model: a bubble.
    const multi = respondingModels.length > 1;
    liveModelsRef.current = new Set(multi ? respondingModels : []);
    setLiveTurn(multi ? startLiveTurn(respondingModels, `live-${Date.now()}`) : null);
    expectedModelsCountRef.current = respondingModels.length;
    finishedModelsCountRef.current = 0;

    setModelErrors([]);
    sentFramesRef.current = {};
    respondingModels.forEach((model) => {
      sendFrame({
        message: userMessage,
        model: model,
        toggles: toggles,
        ...contextFields({ summarizer, systemPrompt }),
        document_names: documentNames,
        ...(continuesDebate
          ? { debate_session_id: continuesDebate, parent_checkpoint_id: null }
          : { parent_checkpoint_id: parentCheckpointRef.current }),
        is_deliberation: isDeliberation,
      });
    });
    clearDocuments();
    return true;
  };

  function sendFrame(frame: Record<string, unknown>) {
    sentFramesRef.current[String(frame.model)] = { ...frame };
    wsRef.current?.send(JSON.stringify(frame));
  }

  /** Ask a failed model again, with the same request from the same parent. */
  const retryModel = (errorId: string) => {
    const error = modelErrors.find((e) => e.id === errorId);
    if (!error || isLoading) return;
    if (!isOpen(wsRef.current)) {
      pushToast(NOT_CONNECTED, "error", "Not sent");
      return;
    }
    setModelErrors((prev) => prev.filter((e) => e.id !== errorId));
    // A retried card streams again in place.
    setLiveTurn((turn) => turn && updateLiveReply(turn, error.model, { streaming: true, error: null, content: "" }));
    setIsLoading(true);
    expectedModelsCountRef.current = 1;
    finishedModelsCountRef.current = 0;
    if (error.frame.type === "synthesis") synthesisModelRef.current = error.model;
    sendFrame(error.frame);
  };

  const dismissModelError = (errorId: string) =>
    setModelErrors((prev) => prev.filter((e) => e.id !== errorId));

  /**
   * Merge the replies at these checkpoints into one, written by `model`
   * (default: the first selected model). The backend reads the full replies,
   * writes the prompt (the same synthesis `crucible synthesize --answers` and
   * MCP `synthesize_answers` run), hangs it from the question the answers
   * responded to, and tags the turn so the reply shows as a synthesis in the
   * tree and the transcript. Replies sent together may sit on different
   * branches, so no parent is named here.
   */
  const synthesizeBranches = async (checkpointIds: string[], model?: string | null) => {
    if (!threadId || isLoading || checkpointIds.length < 2) return;
    const synthesizer = model || selectedModels[0];
    if (!synthesizer || !isOpen(wsRef.current)) return;
    setIsLoading(true);
    expectedModelsCountRef.current = 1; // Synthesis is a single model call
    finishedModelsCountRef.current = 0;
    synthesisModelRef.current = synthesizer;
    setModelErrors([]);

    sendFrame({
      answer_checkpoint_ids: checkpointIds,
      model: synthesizer,
      toggles: toggles,
      ...contextFields({ summarizer, systemPrompt }),
      document_names: documentNames,
      parent_checkpoint_id: null,
      type: "synthesis",
    });
    clearDocuments();
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
    setMessages(markStopped);
    setLiveTurn(stopLiveTurn);
  }, []);

  return {
    messages,
    setMessages,
    isLoading,
    sendInteractiveMessage,
    synthesizeBranches,
    stopStreaming,
    modelErrors,
    retryModel,
    dismissModelError,
    replyTexts,
    liveTurn,
  };
}
