import { useCallback, useEffect, useMemo, useReducer, useRef, useState } from "react";
import * as api from "@/lib/api";
import { errorMessage } from "@/lib/errors";
import {
  EMPTY_TRANSCRIPT,
  debateControls,
  debateReplyFor,
  closeWarning,
  earlyStopStatus,
  mayBeLive,
  questionMessage,
  restoredDebateStatus,
  resumedMessages,
  transcriptIncomplete,
  transcriptMessages,
  transcriptReducer,
  type DebateResume,
  type TranscriptEvent,
} from "@/lib/debateTranscript";
import type { DebateDefaults, DebateSession, DebateUiStatus, Toggles } from "@/lib/types";
import { useDebateTree } from "@/hooks/useDebateTree";
import { useDebateSessions } from "@/hooks/useDebateSessions";
import { useStoredValue, writeStoredValue } from "@/hooks/useStoredValue";
import { isOpen, reconnectDelay, useSocketFactory } from "@/lib/transport";
import { contextFields, type RunContext } from "@/lib/runContext";
import type { Confirm } from "@/hooks/useConfirm";
import type { PushToast } from "@/hooks/useToasts";

const STORAGE_KEY = "crucible_active_debate";
const LIVE: DebateUiStatus[] = ["running", "pausing", "paused"];
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
 * - A debate runs on the backend whether or not a tab watches it: leaving
 *   one (another session or thread, a reload) asks nothing and stops
 *   nothing, and reopening a running or paused one attaches to it (a socket
 *   with no first frame; the backend answers debate_resume). A dropped
 *   socket reattaches the same way. Closing the debate stops it, so that
 *   asks first. One interrupted by a server restart can be resumed
 *   (debate_continue).
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
  const { fetchTree, refreshSoon, clearTree, addPendingNode, settlePendingNode, resolvePendingNode, clearPendingNodes } =
    tree;
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
  // The node whose reply is open in full ("Read" on a node).
  const [readingId, setReadingId] = useState<string | null>(null);
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
  // The session whose stored transcript may be applied: a load for any other
  // (one still in flight when the person switched) is dropped.
  const adoptingRef = useRef<string | null>(null);
  // The session a socket is attaching to, until the backend says whether it runs.
  const attachingRef = useRef<string | null>(null);
  // Frames that arrive while a resumed debate's stored rounds load; applied after them.
  const syncQueueRef = useRef<any[] | null>(null);
  // A dropped socket's reattach: unexpected closes in a row, and the pending timer.
  const attemptRef = useRef(0);
  const reconnectTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  // What an attach that finds nothing running shows (loadStored, below).
  const loadStoredRef = useRef<(s: DebateSession) => void>(() => {});
  const statusRef = useRef(status);
  useEffect(() => {
    statusRef.current = status;
  }, [status]);

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
    attachingRef.current = null;
    syncQueueRef.current = null;
    if (reconnectTimerRef.current) clearTimeout(reconnectTimerRef.current);
    reconnectTimerRef.current = null;
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
  // The current handleEvent (set below): sockets and replayed frames call it.
  const handleEventRef = useRef<(msg: any, sessionId: string) => void>(() => {});
  const handleEvent = useCallback(
    (msg: any, sessionId: string) => {
      switch (msg.type) {
        case "debate_resume": {
          // Attached to a live debate: its stored rounds, then the round in
          // progress as the backend has it. Frames arriving meanwhile wait.
          attachingRef.current = null;
          const resume = msg as DebateResume;
          if (resume.round !== null) setRound(resume.round);
          setStatus(resume.status);
          if (resume.convergence_score != null) setConvergenceScore(resume.convergence_score);
          if (resume.question) promptRef.current = resume.question;
          syncQueueRef.current = [];
          api
            .fetchDebateTranscript(sessionId)
            .catch(() => null)
            .then((t) => {
              if (adoptingRef.current !== sessionId || syncQueueRef.current === null) return;
              const queued = syncQueueRef.current;
              syncQueueRef.current = null;
              const stored = t ?? { question: resume.question ?? "", rounds: [], synthesis: null };
              dispatch({ kind: "reset", messages: resumedMessages(stored, participantsRef.current, resume) });
              dispatch({ kind: "resume", resume, now: Date.now() });
              if (resume.round !== null) {
                for (const a of resume.answers) {
                  if (a.done) continue;
                  const lane = Math.max(0, participantsRef.current.indexOf(a.model));
                  addPendingNode(a.model, resume.round, lane, modelColor(a.model), modelLabel(a.model));
                }
              }
              for (const m of queued) handleEventRef.current(m, sessionId);
            });
          break;
        }

        case "attached":
          if (!msg.live && attachingRef.current === sessionId) {
            // Nothing runs it any more (it finished meanwhile, or the server
            // restarted): show it as stored.
            closeSocket();
            api
              .fetchDebateSession(sessionId)
              .then((s) => {
                if (adoptingRef.current === sessionId) loadStoredRef.current(s);
              })
              .catch(() => {});
          }
          break;

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
          if (msg.checkpoint_id) settlePendingNode(msg.model, msg.round ?? 0, msg.checkpoint_id, msg.content ?? "");
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
      closeSocket,
      fetchThreads,
      refreshSessions,
      transcriptEvent,
      addPendingNode,
      settlePendingNode,
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
  useEffect(() => {
    handleEventRef.current = handleEvent;
  }, [handleEvent]);

  // A dropped socket reattaches through this (defined below, after connect).
  const attachRef = useRef<(sessionId: string) => void>(() => {});

  // One socket per debate session. firstFrame, if any, is sent once it opens;
  // without one the socket only attaches to whatever runs.
  const connect = useCallback(
    (sessionId: string, firstFrame: Record<string, unknown> | null) => {
      const ws = openSocket(api.createDebateWebSocketUrl(sessionId));
      wsRef.current = ws;

      ws.onopen = () => {
        setConnected(true);
        attemptRef.current = 0;
        if (firstFrame) ws.send(JSON.stringify(firstFrame));
      };
      ws.onmessage = (ev) => {
        // Same guard as onclose: a replaced socket must not touch this debate.
        if (wsRef.current !== ws) return;
        try {
          const msg = JSON.parse(ev.data);
          if (syncQueueRef.current && msg.type !== "debate_resume") syncQueueRef.current.push(msg);
          else handleEventRef.current(msg, sessionId);
        } catch {}
      };
      ws.onerror = () => console.error("[Debate WS] connection error");
      ws.onclose = () => {
        if (wsRef.current !== ws) return;
        wsRef.current = null;
        setConnected(false);
        syncQueueRef.current = null;
        clearPendingNodes();
        refreshSessions();
        // The debate goes on without this socket: attach to it again.
        if (LIVE.includes(statusRef.current)) {
          const delay = reconnectDelay(attemptRef.current);
          attemptRef.current += 1;
          reconnectTimerRef.current = setTimeout(() => attachRef.current(sessionId), delay);
        }
      };
      return ws;
    },
    [openSocket, clearPendingNodes, refreshSessions],
  );

  /** Watch the session's run, if it has one (debate_resume, else attached {live: false}). */
  const attach = useCallback(
    (sessionId: string) => {
      closeSocket();
      attachingRef.current = sessionId;
      connect(sessionId, null);
    },
    [closeSocket, connect],
  );
  useEffect(() => {
    attachRef.current = attach;
  }, [attach]);

  // ─── Loading an existing session ─────────────────────────────
  const retryTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const cancelRetry = useCallback(() => {
    if (retryTimerRef.current) clearTimeout(retryTimerRef.current);
    retryTimerRef.current = null;
  }, []);
  useEffect(() => cancelRetry, [cancelRetry]);
  const adoptFields = useCallback((s: DebateSession, live: boolean) => {
    cancelRetry();
    adoptingRef.current = s.session_id;
    setRound(s.current_round);
    setMaxRounds(s.termination_policy.max_rounds);
    setStatus(restoredDebateStatus(s.status, live));
    participantsRef.current = s.participants;
    promptRef.current = s.question ?? "";
  }, [cancelRetry]);

  /** A stored session with nothing running: its transcript as the server has it. */
  const loadStored = useCallback((s: DebateSession) => {
    adoptFields(s, false);
    const load = (attempt: number) =>
      api
        .fetchDebateTranscript(s.session_id)
        .then((t) => {
          if (adoptingRef.current !== s.session_id) return;
          if (!promptRef.current) promptRef.current = t.question;
          dispatch({ kind: "reset", messages: transcriptMessages(t, s.participants) });
          // A transcript read while a round's checkpoints are still being
          // written can come back without rounds the session says were
          // finished; ask again shortly.
          if (transcriptIncomplete(t, s) && attempt < TRANSCRIPT_RETRIES) {
            retryTimerRef.current = setTimeout(() => load(attempt + 1), TRANSCRIPT_RETRY_MS);
          }
        })
        .catch(() => {});
    load(0);
  }, [adoptFields]);
  useEffect(() => {
    loadStoredRef.current = loadStored;
  }, [loadStored]);

  /**
   * A session from the server: a running or paused one is attached to (its
   * transcript then comes with the backend's debate_resume), anything else
   * is shown as stored.
   */
  const adoptSession = useCallback(
    (s: DebateSession) => {
      if (!mayBeLive(s.status)) return loadStored(s);
      adoptFields(s, true);
      attach(s.session_id);
    },
    [loadStored, adoptFields, attach],
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

        // A new debate replaces whatever was on screen (which, if it runs,
        // runs on: the sidebar shows it).
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
        // Information, not a failure: the debate runs either way.
        for (const warning of session.warnings ?? []) pushToast(warning, "info", "About this debate");

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
    [threadId, closeSocket, cancelRetry, setActiveSessionId, fetchTree, refreshSessions, setShowTree, connect, pushToast],
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

  /**
   * The banner's close button: stops a debate that is running or paused, so
   * it asks first. (Leaving one without closing it keeps it running.)
   */
  const close = useCallback(async () => {
    const warning = closeWarning(status);
    if (warning && !(await confirm("Stop the debate?", warning, { confirmLabel: "Stop and close" }))) return;
    if (debateControls(status, true).stopOnClose) {
      const stop = { type: "debate_control", action: "stop" };
      if (isOpen(wsRef.current)) send(stop);
      else if (activeSessionId) {
        // Between a dropped socket and its reattach: a socket of its own carries the stop.
        const ws = openSocket(api.createDebateWebSocketUrl(activeSessionId));
        ws.onopen = () => {
          ws.send(JSON.stringify(stop));
          ws.close();
        };
      }
    }
    clear();
  }, [confirm, status, send, clear, activeSessionId, openSocket]);

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
      // The debate on screen runs on if it runs; this tab stops watching it.
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
    [activeSessionId, fetchTree, setShowTree, closeSocket, setActiveSessionId, adoptSession, pushToast],
  );

  // A node from another debate (the tree was cleared or replaced) reads as closed.
  const reading = useMemo(() => {
    const node = readingId ? tree.nodes.find((n) => n.id === readingId) : undefined;
    return node ? { node, reply: debateReplyFor(node, transcript.messages) } : null;
  }, [readingId, tree.nodes, transcript.messages]);
  const closeReading = useCallback(() => setReadingId(null), []);

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
    reading,
    readNode: setReadingId,
    closeReading,
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
    remove,
    switchTo,
  };
}
