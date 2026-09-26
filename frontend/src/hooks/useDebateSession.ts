import { useCallback, useEffect, useMemo, useReducer, useRef, useState } from "react";
import * as api from "@/lib/api";
import { modelFamilyColor } from "@/lib/colors";
import {
  EMPTY_TRANSCRIPT,
  debateControls,
  restoredDebateStatus,
  transcriptReducer,
  type TranscriptEvent,
} from "@/lib/debateTranscript";
import type { DebateDefaults, DebateSession, DebateUiStatus, Toggles } from "@/lib/types";
import { useDebateTree } from "@/hooks/useDebateTree";
import { useStoredValue, writeStoredValue } from "@/hooks/useStoredValue";

const STORAGE_KEY = "crucible_active_debate";

export interface DebateStartContext {
  participants: string[];
  prompt: string;
  toggles: Toggles;
  documents: Record<string, string>;
  parentCheckpointId: string | null;
}

interface Options {
  threadId: string | null;
  /** The sidebar's thread list; the debate list is refreshed whenever it changes. */
  threads: unknown[];
  fetchThreads: () => void;
  /** Regular-chat tree state, used to auto-open a debate-only thread's latest debate. */
  historyNodeCount: number;
  isHistoryLoading: boolean;
  setShowTree: (tree: boolean) => void;
  /** Called when a debate completes, so post-debate chat starts clean. */
  clearChatMessages: () => void;
  pushToast: (message: string, model?: string) => void;
  confirm: (title: string, message: string) => Promise<boolean>;
  modelLabel: (modelId: string) => string;
}

/**
 * Everything about the debate on screen: which session is active (persisted
 * across reloads), its transcript and status, the WebSocket that drives it,
 * the sidebar's session list and the debate tree.
 *
 * Invariants (each was a bug):
 * - Anything that shows a different debate calls closeSocket() first, so the
 *   old stream can't append bubbles or overwrite the new tree.
 * - A socket's onclose only clears the ref if it is still the current socket.
 * - Code that loads a session itself marks restoredRef, so the restore effect
 *   doesn't replace a live stream with a server snapshot.
 * - The persisted session is adopted during render and its write skips the
 *   mount run; writing the hydration-time null erased it.
 * - A restored session is only honoured for the thread it belongs to.
 */
export function useDebateSession({
  threadId,
  threads,
  fetchThreads,
  historyNodeCount,
  isHistoryLoading,
  setShowTree,
  clearChatMessages,
  pushToast,
  confirm,
  modelLabel,
}: Options) {
  const tree = useDebateTree();
  const {
    fetchTree,
    clearTree,
    startPolling,
    stopPolling,
    addPendingNode,
    resolvePendingNode,
    clearPendingNodes,
  } = tree;

  // ─── Active session (persisted) ──────────────────────────────
  const storedSession = useStoredValue(STORAGE_KEY);
  const [activeSessionId, setActiveSessionId] = useState<string | null>(null);
  const [adoptedStored, setAdoptedStored] = useState(false);
  if (!adoptedStored && storedSession) {
    setAdoptedStored(true);
    setActiveSessionId(storedSession);
  }

  const persistReadyRef = useRef(false);
  useEffect(() => {
    if (!persistReadyRef.current) {
      persistReadyRef.current = true;
      return;
    }
    writeStoredValue(STORAGE_KEY, activeSessionId);
  }, [activeSessionId]);

  // ─── Debate state ────────────────────────────────────────────
  const [transcript, dispatch] = useReducer(transcriptReducer, EMPTY_TRANSCRIPT);
  const [round, setRound] = useState(0);
  const [maxRounds, setMaxRounds] = useState(3);
  const [status, setStatus] = useState<DebateUiStatus>("running");
  const [convergenceScore, setConvergenceScore] = useState<number | undefined>();
  const [sessions, setSessions] = useState<DebateSession[]>([]);
  // Debate nodes are read-only, so selection just expands the node in place.
  const [activeNode, setActiveNode] = useState<string | null>(null);
  const [dialogOpen, setDialogOpen] = useState(false);

  const wsRef = useRef<WebSocket | null>(null);
  const tokenBufferRef = useRef<Record<string, string>>({});
  const rafRef = useRef<number | null>(null);
  const promptRef = useRef("");
  const participantsRef = useRef<string[]>([]);
  const restoredRef = useRef<string | null>(null);

  const refreshSessions = useCallback(() => {
    api.listDebateSessions().then(setSessions).catch(() => {});
  }, []);

  useEffect(() => {
    refreshSessions();
  }, [threads, refreshSessions]);

  // ─── Token batching ──────────────────────────────────────────
  const flushTokens = useCallback(() => {
    const chunks = tokenBufferRef.current;
    if (!Object.keys(chunks).length) return;
    tokenBufferRef.current = {};
    dispatch({ kind: "tokens", chunks });
  }, []);

  const scheduleFlush = useCallback(() => {
    if (rafRef.current) return;
    rafRef.current = requestAnimationFrame(() => {
      rafRef.current = null;
      flushTokens();
    });
  }, [flushTokens]);

  const closeSocket = useCallback(() => {
    const ws = wsRef.current;
    wsRef.current = null;
    if (ws) {
      ws.onmessage = null;
      ws.onclose = null;
      ws.close();
    }
    stopPolling();
    if (rafRef.current) {
      cancelAnimationFrame(rafRef.current);
      rafRef.current = null;
    }
    tokenBufferRef.current = {};
  }, [stopPolling]);

  const transcriptEvent = useCallback(
    (event: TranscriptEvent) => dispatch({ kind: "event", event, now: Date.now() }),
    [],
  );

  // ─── Incoming events ─────────────────────────────────────────
  const handleEvent = useCallback(
     
    (msg: any, sessionId: string) => {
      switch (msg.type) {
        case "debate_session_created":
          participantsRef.current = msg.participants ?? [];
          // The backend has just titled the parent thread; list it (and the
          // debate) so a debate started from a new session is findable.
          fetchThreads();
          refreshSessions();
          break;

        case "debate_round_start": {
          const r = msg.round ?? 0;
          setRound(r);
          setStatus("running");
          transcriptEvent(msg);
          participantsRef.current.forEach((modelId, i) =>
            addPendingNode(modelId, r, i, modelFamilyColor(modelId), modelLabel(modelId)),
          );
          break;
        }

        case "stream_start":
          transcriptEvent(msg);
          break;

        case "stream_token":
          tokenBufferRef.current[msg.model] = (tokenBufferRef.current[msg.model] ?? "") + msg.token;
          scheduleFlush();
          break;

        case "stream_end":
          flushTokens();
          transcriptEvent(msg);
          resolvePendingNode(msg.model, sessionId, msg.round ?? 0);
          break;

        case "debate_round_end":
          if (msg.convergence_score != null) setConvergenceScore(msg.convergence_score);
          fetchTree(sessionId);
          break;

        case "debate_converged":
          setStatus("converged");
          if (msg.score != null) setConvergenceScore(msg.score);
          break;

        case "debate_synthesis_start":
          flushTokens();
          transcriptEvent(msg);
          break;

        case "debate_synthesis_end":
          flushTokens();
          transcriptEvent(msg);
          fetchTree(sessionId);
          // Poll for completed status in case the WS event arrives late.
          setTimeout(() => {
            api
              .fetchDebateSession(sessionId)
              .then((s) => {
                if (s.status === "completed") setStatus("completed");
              })
              .catch(() => {});
          }, 2000);
          break;

        case "debate_session_status":
          if (msg.status === "completed") {
            setStatus("completed");
            stopPolling();
            fetchTree(sessionId);
            clearPendingNodes();
            refreshSessions();
            clearChatMessages();
          } else if (msg.status === "pausing" || msg.status === "paused" || msg.status === "running") {
            setStatus(msg.status);
          } else if (msg.status === "inject_queued") {
            pushToast("Added — the models will see it in the next round.");
          }
          break;

        case "error":
          // A failed model never sends stream_end: the reducer closes its
          // bubble, and its "Thinking…" node is resolved here.
          flushTokens();
          transcriptEvent(msg);
          if (msg.model) resolvePendingNode(msg.model, sessionId, msg.round ?? 0);
          pushToast(msg.message ?? "Debate error", msg.model ? modelLabel(msg.model) : undefined);
          break;
      }
    },
    [
      fetchThreads,
      refreshSessions,
      transcriptEvent,
      addPendingNode,
      modelLabel,
      scheduleFlush,
      flushTokens,
      resolvePendingNode,
      fetchTree,
      stopPolling,
      clearPendingNodes,
      clearChatMessages,
      pushToast,
    ],
  );

  // Sockets outlive renders; they call whatever handler is current.
  const handleEventRef = useRef(handleEvent);
  useEffect(() => {
    handleEventRef.current = handleEvent;
  }, [handleEvent]);

  // One socket per debate session. firstFrame is sent once it opens.
  const connect = useCallback(
    (sessionId: string, firstFrame: Record<string, unknown>, onOpen?: () => void) => {
      const ws = new WebSocket(api.createDebateWebSocketUrl(sessionId));
      wsRef.current = ws;

      ws.onopen = () => {
        ws.send(JSON.stringify(firstFrame));
        onOpen?.();
      };
      ws.onmessage = (ev) => {
        try {
          handleEventRef.current(JSON.parse(ev.data), sessionId);
        } catch {}
      };
      ws.onerror = () => console.error("[Debate WS] connection error");
      ws.onclose = () => {
        if (wsRef.current !== ws) return;
        wsRef.current = null;
        stopPolling();
        clearPendingNodes();
        setStatus((prev) => (prev === "completed" || prev === "converged" ? prev : "interrupted"));
        refreshSessions();
      };
      return ws;
    },
    [stopPolling, clearPendingNodes, refreshSessions],
  );

  // ─── Loading an existing session ─────────────────────────────
  const adoptSession = useCallback(
    (s: DebateSession) => {
      setRound(s.current_round);
      setMaxRounds(s.termination_policy.max_rounds);
      setStatus(restoredDebateStatus(s.status));
      participantsRef.current = s.participants;
      api
        .loadDebateMessages(s)
        .then((messages) => dispatch({ kind: "reset", messages }))
        .catch(() => {});
    },
    [],
  );

  // Restore whenever the active session is set by something that didn't load
  // it itself (initial adoption from localStorage). Only for its own thread.
  useEffect(() => {
    if (!activeSessionId || !threadId) return;
    if (restoredRef.current === activeSessionId) return;
    restoredRef.current = activeSessionId;
    api
      .fetchDebateSession(activeSessionId)
      .then((s) => {
        if (s.parent_thread_id !== threadId) {
          restoredRef.current = null;
          setActiveSessionId(null);
          return;
        }
        fetchTree(activeSessionId);
        adoptSession(s);
      })
      .catch(() => {
        restoredRef.current = null;
        setActiveSessionId(null);
      });
  }, [activeSessionId, threadId, fetchTree, adoptSession]);

  // A debate-only thread (no regular chat) opens its latest debate.
  useEffect(() => {
    if (!threadId || isHistoryLoading || historyNodeCount > 0 || activeSessionId) return;
    // Sessions arrive newest-first from the API.
    const threadDebates = sessions.filter((s) => s.parent_thread_id === threadId);
    if (threadDebates.length === 0) return;
    const latest =
      threadDebates.find((s) => s.current_round > 0 || s.status === "completed") ?? threadDebates[0];
    // Activate only once the session resolves, so a deleted or unreadable
    // session can never leave the tree view stuck on an empty debate.
    api
      .fetchDebateSession(latest.session_id)
      .then((s) => {
        restoredRef.current = s.session_id;
        setActiveSessionId(s.session_id);
        adoptSession(s);
        setShowTree(true);
        fetchTree(s.session_id);
      })
      .catch(() => {});
  }, [threadId, isHistoryLoading, historyNodeCount, activeSessionId]); // eslint-disable-line react-hooks/exhaustive-deps

  // ─── Thread switches ─────────────────────────────────────────
  // The state reset runs during render (React's documented way to adjust
  // state on a prop change), so a stale debate never paints for a frame. The
  // socket/interval teardown is impure, so it stays in an effect.
  const [threadKey, setThreadKey] = useState<string | null>(threadId);
  if (threadId !== threadKey) {
    setThreadKey(threadId);
    if (threadKey !== null) {
      setActiveSessionId(null);
      setActiveNode(null);
      dispatch({ kind: "reset" });
      setRound(0);
      setStatus("running");
      setConvergenceScore(undefined);
    }
  }
  useEffect(() => closeSocket, [threadId, closeSocket]);

  // ─── Actions ─────────────────────────────────────────────────
  const socketOpen = useCallback(() => {
    if (wsRef.current?.readyState === WebSocket.OPEN) return true;
    pushToast("This debate is no longer connected. Start a new debate to continue.");
    return false;
  }, [pushToast]);

  const send = useCallback((frame: Record<string, unknown>) => {
    wsRef.current?.send(JSON.stringify(frame));
  }, []);

  const openDialog = useCallback((prompt: string) => {
    promptRef.current = prompt;
    setDialogOpen(true);
  }, []);

  const closeDialog = useCallback(() => setDialogOpen(false), []);

  const start = useCallback(
    async (
      config: DebateDefaults,
      ctx: Omit<DebateStartContext, "prompt">,
    ) => {
      setDialogOpen(false);
      if (!threadId) return;
      try {
        const session = await api.createDebateSession({
          parent_thread_id: threadId,
          participants: ctx.participants,
          termination_policy: {
            max_rounds: config.max_rounds,
            convergence_threshold: config.convergence_threshold,
            llm_judge: config.llm_judge,
            mode: config.mode,
          },
          auto_synthesize: config.auto_synthesize,
          synthesizer_model: config.synthesizer_model,
        });

        // A new debate replaces whatever was on screen, live or not.
        closeSocket();
        restoredRef.current = session.session_id;
        setActiveSessionId(session.session_id);
        fetchTree(session.session_id);
        refreshSessions();
        setMaxRounds(config.max_rounds);
        setRound(0);
        setStatus("running");
        dispatch({ kind: "reset" });
        setConvergenceScore(undefined);
        participantsRef.current = session.participants;
        setShowTree(true);

        connect(
          session.session_id,
          {
            type: "debate_start",
            prompt: promptRef.current,
            toggles: ctx.toggles,
            documents: ctx.documents,
            parent_checkpoint_id: ctx.parentCheckpointId,
          },
          () => startPolling(session.session_id),
        );
      } catch (e) {
        console.error("Failed to create debate session:", e);
        pushToast("Couldn't start the debate.");
      }
    },
    [threadId, closeSocket, fetchTree, refreshSessions, setShowTree, connect, startPolling, pushToast],
  );

  const inject = useCallback(
    (message: string) => {
      if (!socketOpen()) return;
      send({ type: "debate_inject", message });
      dispatch({ kind: "user", entry: "inject", content: message, now: Date.now() });
    },
    [socketOpen, send],
  );

  const redirect = useCallback(
    (message: string) => {
      if (!socketOpen()) return;
      promptRef.current = message;
      send({ type: "debate_redirect", message });
      dispatch({ kind: "user", entry: "redirect", content: message, now: Date.now() });
    },
    [socketOpen, send],
  );

  const pause = useCallback(() => {
    if (socketOpen()) send({ type: "debate_control", action: "pause" });
  }, [socketOpen, send]);

  const resume = useCallback(() => {
    if (socketOpen()) send({ type: "debate_control", action: "resume" });
  }, [socketOpen, send]);

  const synthesize = useCallback(
    (synthesizerModel: string | null, toggles: Toggles) => {
      const frame = {
        type: "debate_synthesize",
        synthesizer_model: synthesizerModel || participantsRef.current[0],
        prompt: promptRef.current,
        toggles,
      };
      if (wsRef.current?.readyState === WebSocket.OPEN) {
        send(frame);
      } else if (activeSessionId) {
        // A restored or finished debate has no socket; synthesis opens one
        // for its own stream.
        connect(activeSessionId, frame);
      }
    },
    [activeSessionId, connect, send],
  );

  const clear = useCallback(() => {
    closeSocket();
    setActiveSessionId(null);
    dispatch({ kind: "reset" });
    setRound(0);
    setStatus("running");
    setConvergenceScore(undefined);
    setActiveNode(null);
    clearTree();
  }, [closeSocket, clearTree]);

  /** The banner's close button: stop the debate if it is still going, then drop it. */
  const close = useCallback(() => {
    if (debateControls(status, true).stopOnClose && wsRef.current?.readyState === WebSocket.OPEN) {
      send({ type: "debate_control", action: "stop" });
    }
    clear();
  }, [status, send, clear]);

  const remove = useCallback(
    async (sessionId: string) => {
      const ok = await confirm(
        "Delete Debate",
        "This removes the debate and every model's responses in it. This action cannot be undone.",
      );
      if (!ok) return;
      try {
        await api.deleteDebateSession(sessionId);
        if (sessionId === activeSessionId) clear();
        setSessions((prev) => prev.filter((d) => d.session_id !== sessionId));
      } catch {
        pushToast("Couldn't delete the debate.");
      }
    },
    [confirm, activeSessionId, clear, pushToast],
  );

  const switchTo = useCallback(
    (sessionId: string) => {
      if (sessionId === activeSessionId) {
        // Re-selecting the debate on screen: refresh it, but keep its socket,
        // or a live debate would be cancelled by its own click.
        fetchTree(sessionId);
        setShowTree(true);
        return;
      }
      // Leaving a live debate: its socket closing cancels it server-side.
      closeSocket();
      restoredRef.current = sessionId;
      setActiveSessionId(sessionId);
      dispatch({ kind: "reset" });
      setConvergenceScore(undefined);
      fetchTree(sessionId);
      api.fetchDebateSession(sessionId).then(adoptSession).catch(() => {});
      setShowTree(true);
    },
    [activeSessionId, fetchTree, setShowTree, closeSocket, adoptSession],
  );

  const hasTranscript = transcript.messages.length > 0;
  const controls = useMemo(() => debateControls(status, hasTranscript), [status, hasTranscript]);

  return {
    activeSessionId,
    sessions,
    tree,
    activeNode,
    setActiveNode,
    messages: transcript.messages,
    round,
    maxRounds,
    status,
    convergenceScore,
    controls,
    dialogOpen,
    openDialog,
    closeDialog,
    start,
    inject,
    redirect,
    pause,
    resume,
    synthesize,
    close,
    remove,
    switchTo,
  };
}
