import { useCallback, useEffect, useMemo, useReducer, useRef, useState } from "react";
import * as api from "@/lib/api";
import { errorMessage } from "@/lib/errors";
import {
  EMPTY_TRANSCRIPT,
  debateControls,
  earlyStopStatus,
  leaveWarning,
  questionMessage,
  restoredDebateStatus,
  transcriptIncomplete,
  transcriptMessages,
  transcriptReducer,
  type TranscriptEvent,
} from "@/lib/debateTranscript";
import type { DebateDefaults, DebateSession, DebateUiStatus, Toggles } from "@/lib/types";
import { useDebateTree } from "@/hooks/useDebateTree";
import { useDebateSessions } from "@/hooks/useDebateSessions";
import { useStoredValue, writeStoredValue } from "@/hooks/useStoredValue";
import { isOpen, useSocketFactory } from "@/lib/transport";
import { contextFields, type RunContext } from "@/lib/runContext";
import type { Confirm } from "@/hooks/useConfirm";
import type { PushToast } from "@/hooks/useToasts";

const STORAGE_KEY = "crucible_active_debate";
const TRANSCRIPT_RETRIES = 3;
const TRANSCRIPT_RETRY_MS = 600;

export interface DebateStartContext extends RunContext {
  participants: string[];
  prompt: string;
  toggles: Toggles;
  /** Files attached to the question, by name (stored on the parent thread). */
  documentNames: string[];
  parentCheckpointId: string | null;
}

interface Options {
  threadId: string | null;
  fetchThreads: () => void;
  /** Regular-chat tree state, used to auto-open a debate-only thread's latest debate. */
  historyNodeCount: number;
  isHistoryLoading: boolean;
  setShowTree: (tree: boolean) => void;
  /** Called when a debate completes, so post-debate chat starts clean. */
  clearChatMessages: () => void;
  pushToast: PushToast;
  confirm: Confirm;
  modelLabel: (modelId: string) => string;
  /** A model's family colour, for the placeholder nodes drawn while it answers. */
  modelColor: (modelId: string) => string;
}

/**
 * The persisted active session: adopted during render once storage is
 * readable, written on every later change. The write skips the mount run:
 * writing the hydration-time null erased the stored session before it could
 * be adopted.
 */
function usePersistedSession() {
  const stored = useStoredValue(STORAGE_KEY);
  const [activeSessionId, setActiveSessionId] = useState<string | null>(null);
  const [adopted, setAdopted] = useState(false);
  if (!adopted && stored) {
    setAdopted(true);
    setActiveSessionId(stored);
  }
  const readyRef = useRef(false);
  useEffect(() => {
    if (!readyRef.current) {
      readyRef.current = true;
      return;
    }
    writeStoredValue(STORAGE_KEY, activeSessionId);
  }, [activeSessionId]);
  return [activeSessionId, setActiveSessionId] as const;
}

/**
 * Everything about the debate on screen: which session is active (persisted
 * across reloads), its transcript and status, the WebSocket that drives it,
 * and the debate tree. The sidebar's list is useDebateSessions.
 *
 * Invariants (each was a bug):
 * - Anything that shows a different debate calls closeSocket() first, so the
 *   old stream can't append bubbles or overwrite the new tree.
 * - A socket's onclose only clears the ref if it is still the current socket.
 * - Code that loads a session itself marks restoredRef, so the restore effect
 *   doesn't replace a live stream with a server snapshot.
 * - A restored session is only honoured for the thread it belongs to.
 * - A debate runs only while its socket is open, so leaving a live one asks
 *   first (confirmLeave); an interrupted one can be resumed (debate_continue).
 */
export function useDebateSession({
  threadId,
  fetchThreads,
  historyNodeCount,
  isHistoryLoading,
  setShowTree,
  clearChatMessages,
  pushToast,
  confirm,
  modelLabel,
  modelColor,
}: Options) {
  const openSocket = useSocketFactory();
  const tree = useDebateTree();
  const { fetchTree, refreshSoon, clearTree, addPendingNode, resolvePendingNode, clearPendingNodes } = tree;
  const { sessions, refreshSessions, forgetSession } = useDebateSessions(threadId);
  const [activeSessionId, setActiveSessionId] = usePersistedSession();

  // ─── Debate state ────────────────────────────────────────────
  const [transcript, dispatch] = useReducer(transcriptReducer, EMPTY_TRANSCRIPT);
  const [round, setRound] = useState(0);
  const [maxRounds, setMaxRounds] = useState(3);
  const [status, setStatus] = useState<DebateUiStatus>("running");
  const [convergenceScore, setConvergenceScore] = useState<number | undefined>();
  // Debate nodes are read-only, so selection just expands the node in place.
  const [activeNode, setActiveNode] = useState<string | null>(null);
  const [dialogOpen, setDialogOpen] = useState(false);
  // The question the open dialog is about to debate.
  const [dialogPrompt, setDialogPrompt] = useState("");
  // Whether this tab has a socket to the debate on screen (pause and leave
  // warnings depend on it).
  const [connected, setConnected] = useState(false);

  const wsRef = useRef<WebSocket | null>(null);
  const tokenBufferRef = useRef<Record<string, string>>({});
  const rafRef = useRef<number | null>(null);
  // The question being debated now: what a synthesis or a redirect is about.
  const promptRef = useRef("");
  // What the dialog was opened with; read by start() in the same tick.
  const dialogPromptRef = useRef("");
  const participantsRef = useRef<string[]>([]);
  const restoredRef = useRef<string | null>(null);
  // Status before a Resume, restored if the backend refuses it.
  const beforeResumeRef = useRef<DebateUiStatus | null>(null);

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
    setConnected(false);
    if (ws) {
      ws.onmessage = null;
      ws.onclose = null;
      ws.close();
    }
    if (rafRef.current) {
      cancelAnimationFrame(rafRef.current);
      rafRef.current = null;
    }
    tokenBufferRef.current = {};
  }, []);

  const transcriptEvent = useCallback(
    (event: TranscriptEvent) => dispatch({ kind: "event", event, now: Date.now() }),
    [],
  );

  // ─── Incoming events ─────────────────────────────────────────
  const handleEvent = useCallback(
    (msg: any, sessionId: string) => {
      switch (msg.type) {
        case "debate_session_created":
          participantsRef.current = msg.participants ?? participantsRef.current;
          // The backend has just titled the parent thread; list it (and the
          // debate) so a debate started from a new session is findable.
          fetchThreads();
          refreshSessions();
          break;

        case "debate_round_start": {
          const r = msg.round ?? 0;
          beforeResumeRef.current = null;
          setRound(r);
          setStatus("running");
          transcriptEvent(msg);
          participantsRef.current.forEach((modelId, i) =>
            addPendingNode(modelId, r, i, modelColor(modelId), modelLabel(modelId)),
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
          refreshSoon(sessionId);
          break;

        case "debate_converged":
          setStatus(earlyStopStatus(msg.method));
          if (msg.score != null) setConvergenceScore(msg.score);
          break;

        case "debate_synthesis_start":
          flushTokens();
          transcriptEvent(msg);
          break;

        case "debate_synthesis_end":
          flushTokens();
          transcriptEvent(msg);
          refreshSoon(sessionId);
          break;

        case "debate_session_status":
          if (msg.status === "completed") {
            setStatus("completed");
            refreshSoon(sessionId);
            clearPendingNodes();
            refreshSessions();
            clearChatMessages();
          } else if (msg.status === "pausing" || msg.status === "paused" || msg.status === "running") {
            setStatus(msg.status);
          } else if (msg.status === "inject_queued") {
            pushToast("Added. The models will see it in the next round.", "success");
          }
          break;

        case "error":
          // A failed model never sends stream_end: the reducer closes its
          // bubble, and its "Thinking…" node is resolved here.
          flushTokens();
          transcriptEvent(msg);
          if (msg.model) {
            resolvePendingNode(msg.model, sessionId, msg.round ?? 0);
          } else if (beforeResumeRef.current) {
            // A Resume the backend refused (e.g. another tab runs it).
            setStatus(beforeResumeRef.current);
            beforeResumeRef.current = null;
          }
          pushToast(
            msg.message ?? "The debate reported an error.",
            "error",
            msg.model ? `${modelLabel(msg.model)} failed` : undefined,
          );
          break;
      }
    },
    [
      fetchThreads,
      refreshSessions,
      transcriptEvent,
      addPendingNode,
      modelLabel,
      modelColor,
      scheduleFlush,
      flushTokens,
      resolvePendingNode,
      refreshSoon,
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
    (sessionId: string, firstFrame: Record<string, unknown>) => {
      const ws = openSocket(api.createDebateWebSocketUrl(sessionId));
      wsRef.current = ws;

      ws.onopen = () => {
        setConnected(true);
        ws.send(JSON.stringify(firstFrame));
      };
      ws.onmessage = (ev) => {
        // Same guard as onclose: a replaced socket must not touch this debate.
        if (wsRef.current !== ws) return;
        try {
          handleEventRef.current(JSON.parse(ev.data), sessionId);
        } catch {}
      };
      ws.onerror = () => console.error("[Debate WS] connection error");
      ws.onclose = () => {
        if (wsRef.current !== ws) return;
        wsRef.current = null;
        setConnected(false);
        clearPendingNodes();
        setStatus((prev) => (prev === "completed" || prev === "converged" || prev === "stable" ? prev : "interrupted"));
        refreshSessions();
      };
      return ws;
    },
    [openSocket, clearPendingNodes, refreshSessions],
  );

  // ─── Loading an existing session ─────────────────────────────
  // The session whose stored transcript may be applied: a load for any other
  // (one still in flight when the person switched) is dropped.
  const adoptingRef = useRef<string | null>(null);
  const retryTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const cancelRetry = useCallback(() => {
    if (retryTimerRef.current) clearTimeout(retryTimerRef.current);
    retryTimerRef.current = null;
  }, []);
  useEffect(() => cancelRetry, [cancelRetry]);
  const adoptSession = useCallback((s: DebateSession) => {
    cancelRetry();
    adoptingRef.current = s.session_id;
    setRound(s.current_round);
    setMaxRounds(s.termination_policy.max_rounds);
    setStatus(restoredDebateStatus(s.status));
    participantsRef.current = s.participants;
    promptRef.current = s.question ?? "";
    const load = (attempt: number) =>
      api
        .fetchDebateTranscript(s.session_id)
        .then((t) => {
          if (adoptingRef.current !== s.session_id) return;
          if (!promptRef.current) promptRef.current = t.question;
          dispatch({ kind: "reset", messages: transcriptMessages(t, s.participants) });
          // Read right after a reload, while the backend is still stopping
          // the run this tab left, a transcript can come back without rounds
          // the session says were finished; ask again shortly.
          if (transcriptIncomplete(t, s) && attempt < TRANSCRIPT_RETRIES) {
            retryTimerRef.current = setTimeout(() => load(attempt + 1), TRANSCRIPT_RETRY_MS);
          }
        })
        .catch(() => {});
    load(0);
  }, [cancelRetry]);

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
  }, [activeSessionId, threadId, fetchTree, adoptSession, setActiveSessionId]);

  // A debate-only thread (no regular chat) opens its latest debate — once
  // per thread visit. Closing it used to bring it straight back, since the
  // effect refired the moment no session was active.
  const autoOpenedRef = useRef<string | null>(null);
  useEffect(() => {
    if (!threadId || isHistoryLoading || historyNodeCount > 0 || activeSessionId) return;
    if (autoOpenedRef.current === threadId) return;
    // Sessions arrive newest-first from the API.
    const threadDebates = sessions.filter((s) => s.parent_thread_id === threadId);
    if (threadDebates.length === 0) return;
    autoOpenedRef.current = threadId;
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
  }, [threadId, isHistoryLoading, historyNodeCount, activeSessionId, sessions]); // eslint-disable-line react-hooks/exhaustive-deps

  // ─── Thread switches ─────────────────────────────────────────
  // The state reset runs during render (React's documented way to adjust
  // state on a prop change), so a stale debate never paints for a frame. The
  // socket teardown is impure, so it stays in an effect.
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
    if (isOpen(wsRef.current)) return true;
    pushToast("This debate is no longer connected to this tab.", "error");
    return false;
  }, [pushToast]);

  const send = useCallback((frame: Record<string, unknown>) => {
    wsRef.current?.send(JSON.stringify(frame));
  }, []);

  /**
   * Ask before something takes the live debate off screen: its socket
   * closing stops it. Resolves true when nothing is lost or the person
   * agreed.
   */
  const confirmLeave = useCallback(async () => {
    const warning = leaveWarning(status, isOpen(wsRef.current));
    if (!warning) return true;
    return confirm("Leave the debate?", warning, { confirmLabel: "Stop and leave" });
  }, [status, confirm]);

  const openDialog = useCallback((prompt: string) => {
    dialogPromptRef.current = prompt;
    setDialogPrompt(prompt);
    setDialogOpen(true);
  }, []);

  const closeDialog = useCallback(() => setDialogOpen(false), []);

  const start = useCallback(
    async (config: DebateDefaults, ctx: Omit<DebateStartContext, "prompt">): Promise<boolean> => {
      setDialogOpen(false);
      if (!threadId) return false;
      if (!(await confirmLeave())) return false;
      const prompt = dialogPromptRef.current;
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
          peer_labels: config.peer_labels,
        });

        // A new debate replaces whatever was on screen.
        closeSocket();
        cancelRetry();
        adoptingRef.current = session.session_id;
        restoredRef.current = session.session_id;
        setActiveSessionId(session.session_id);
        fetchTree(session.session_id);
        refreshSessions();
        setMaxRounds(config.max_rounds);
        setRound(0);
        setStatus("running");
        promptRef.current = prompt;
        dispatch({ kind: "reset", messages: [questionMessage(prompt)] });
        setConvergenceScore(undefined);
        participantsRef.current = session.participants;
        setShowTree(true);

        connect(session.session_id, {
          type: "debate_start",
          prompt,
          toggles: ctx.toggles,
          ...contextFields(ctx),
          document_names: ctx.documentNames,
          parent_checkpoint_id: ctx.parentCheckpointId,
        });
        return true;
      } catch (e) {
        pushToast(errorMessage(e, "Couldn't start the debate"), "error");
        return false;
      }
    },
    [threadId, confirmLeave, closeSocket, cancelRetry, setActiveSessionId, fetchTree, refreshSessions, setShowTree, connect, pushToast],
  );

  const inject = useCallback(
    (message: string) => {
      if (!socketOpen()) return;
      send({ type: "debate_inject", message });
      dispatch({ kind: "user", entry: "inject", content: message, now: Date.now() });
    },
    [socketOpen, send],
  );

  /** Change the question: the backend stops the round in progress and restarts on it. */
  const redirect = useCallback(
    async (message: string): Promise<boolean> => {
      if (!socketOpen()) return false;
      const ok = await confirm(
        "Redirect the debate?",
        "The round in progress stops and the models start again on your new question. Their answers so far stay in the transcript.",
        { confirmLabel: "Redirect", destructive: false },
      );
      if (!ok) return false;
      promptRef.current = message;
      send({ type: "debate_redirect", message });
      dispatch({ kind: "user", entry: "redirect", content: message, now: Date.now() });
      return true;
    },
    [socketOpen, confirm, send],
  );

  const pause = useCallback(() => {
    if (socketOpen()) send({ type: "debate_control", action: "pause" });
  }, [socketOpen, send]);

  const resume = useCallback(() => {
    if (socketOpen()) send({ type: "debate_control", action: "resume" });
  }, [socketOpen, send]);

  /**
   * Run more rounds of a debate that stopped: the rest of an interrupted
   * one, or one more round of a finished one. Same events as a start.
   */
  const continueDebate = useCallback(
    (message?: string) => {
      if (!activeSessionId) return;
      const rounds = status === "interrupted" ? Math.max(1, maxRounds - (round + 1)) : 1;
      const frame = { type: "debate_continue", rounds, ...(message ? { message } : {}) };
      beforeResumeRef.current = status;
      setStatus("running");
      if (message) dispatch({ kind: "user", entry: "inject", content: message, now: Date.now() });
      if (isOpen(wsRef.current)) send(frame);
      else connect(activeSessionId, frame);
    },
    [activeSessionId, status, maxRounds, round, send, connect],
  );

  const synthesize = useCallback(
    (synthesizerModel: string | null, toggles: Toggles, context: RunContext = {}) => {
      // The synthesis frame carries the run's choices again: a frame that
      // names any of them replaces the ones the debate started with. The
      // prompt is the question being debated, also after a reload (it used
      // to be empty then).
      const frame = {
        type: "debate_synthesize",
        synthesizer_model: synthesizerModel || participantsRef.current[0],
        prompt: promptRef.current,
        toggles,
        ...contextFields(context),
      };
      if (isOpen(wsRef.current)) {
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
    cancelRetry();
    adoptingRef.current = null;
    setActiveSessionId(null);
    dispatch({ kind: "reset" });
    setRound(0);
    setStatus("running");
    setConvergenceScore(undefined);
    setActiveNode(null);
    clearTree();
  }, [closeSocket, cancelRetry, setActiveSessionId, clearTree]);

  /** The banner's close button: ask if the debate is live, stop it, then drop it. */
  const close = useCallback(async () => {
    if (!(await confirmLeave())) return;
    if (debateControls(status, true).stopOnClose && isOpen(wsRef.current)) {
      send({ type: "debate_control", action: "stop" });
    }
    clear();
  }, [confirmLeave, status, send, clear]);

  const remove = useCallback(
    async (sessionId: string) => {
      const ok = await confirm(
        "Delete debate",
        "This removes the debate and every model's responses in it. This can't be undone.",
        { confirmLabel: "Delete" },
      );
      if (!ok) return;
      try {
        await api.deleteDebateSession(sessionId);
        if (sessionId === activeSessionId) clear();
        forgetSession(sessionId);
        pushToast("Debate deleted.", "success");
      } catch (e) {
        pushToast(errorMessage(e, "Couldn't delete the debate"), "error");
      }
    },
    [confirm, activeSessionId, clear, forgetSession, pushToast],
  );

  const switchTo = useCallback(
    async (sessionId: string) => {
      if (sessionId === activeSessionId) {
        // Re-selecting the debate on screen: refresh it, but keep its socket,
        // or a live debate would be cancelled by its own click.
        fetchTree(sessionId);
        setShowTree(true);
        return;
      }
      if (!(await confirmLeave())) return;
      closeSocket();
      restoredRef.current = sessionId;
      setActiveSessionId(sessionId);
      dispatch({ kind: "reset" });
      setConvergenceScore(undefined);
      fetchTree(sessionId);
      api
        .fetchDebateSession(sessionId)
        .then(adoptSession)
        .catch((e) => pushToast(errorMessage(e, "Couldn't open the debate"), "error"));
      setShowTree(true);
    },
    [activeSessionId, confirmLeave, fetchTree, setShowTree, closeSocket, setActiveSessionId, adoptSession, pushToast],
  );

  const hasTranscript = transcript.messages.length > 0;
  const controls = useMemo(() => {
    const c = debateControls(status, hasTranscript);
    // Pause and the live controls need this tab's socket; Resume needs a session.
    return { ...c, continue: c.continue && !connected };
  }, [status, hasTranscript, connected]);

  // The debate a chat turn sent now continues: the one on screen until a
  // turn has followed it here. Tracked rather than read off the chat
  // messages: a restored debate that started mid-thread sits above that
  // thread's messages, and the turn then skipped the debate.
  const [followedUp, setFollowedUp] = useState<string | null>(null);
  const continuesDebate = activeSessionId && followedUp !== activeSessionId ? activeSessionId : null;
  const markFollowedUp = useCallback(() => setFollowedUp(activeSessionId), [activeSessionId]);

  return {
    activeSessionId,
    continuesDebate,
    markFollowedUp,
    sessions,
    tree,
    activeNode,
    setActiveNode,
    messages: transcript.messages,
    round,
    maxRounds,
    status,
    connected,
    convergenceScore,
    controls,
    dialogOpen,
    dialogPrompt,
    openDialog,
    closeDialog,
    start,
    inject,
    redirect,
    pause,
    resume,
    continueDebate,
    synthesize,
    close,
    confirmLeave,
    remove,
    switchTo,
  };
}
