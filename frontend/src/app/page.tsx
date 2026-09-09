"use client";

import React, { useState, useEffect, useRef, useCallback } from "react";
import { motion, AnimatePresence } from "framer-motion";
import TreeCanvas from "@/components/TreeCanvas";
import Sidebar from "@/components/Sidebar";
import ControlPanel from "@/components/ControlPanel";
import ChatView from "@/components/ChatView";
import LandingView from "@/components/LandingView";
import ErrorModal from "@/components/ErrorModal";
import Toast, { ToastData } from "@/components/Toast";
import DebateConfigDialog from "@/components/DebateConfigDialog";
import { Layers, Zap, Sun, Moon, MessagesSquare } from "lucide-react";
import {
  Box,
  IconButton,
  Typography,
  ButtonBase,
  Dialog,
  DialogTitle,
  DialogContent,
  DialogContentText,
  DialogActions,
  Button,
} from "@mui/material";
import * as api from "@/lib/api";
import { useThemeMode } from "@/components/ThemeRegistry";
import { useStoredValue, writeStoredValue } from "@/hooks/useStoredValue";

import { useThreads } from "@/hooks/useThreads";
import { useHistoryTree } from "@/hooks/useHistoryTree";
import { useChatWebSocket } from "@/hooks/useChatWebSocket";
import { useDebateTree } from "@/hooks/useDebateTree";
import type { Message, DebateDefaults } from "@/lib/types";
import { modelFamilyColor } from "@/lib/colors";
import { modelDisplayName } from "@/lib/modelNames";

const DEFAULT_DEBATE_DEFAULTS: DebateDefaults = {
  max_rounds: 3,
  convergence_threshold: null,
  llm_judge: null,
  mode: "all",
  auto_synthesize: false,
  synthesizer_model: null,
};

export default function Home() {
  const [input, setInput] = useState("");
  const { isDark, toggleMode } = useThemeMode();
  const [editingThreadId, setEditingThreadId] = useState<string | null>(null);
  const [editingTitle, setEditingTitle] = useState("");
  // Seeded from GET /models (`default_model`) rather than a hardcoded ID, which
  // is how the previous default drifted onto a legacy model.
  const [selectedModels, setSelectedModels] = useState<string[]>([]);
  const [documents, setDocuments] = useState<Record<string, string>>({});
  const [toggles, setToggles] = useState({
    use_rag: true,
    use_web_search: false,
  });
  const [errorModals, setErrorModals] = useState<
    { id: string; title: string; details: string; suggestion?: string }[]
  >([]);
  const [toasts, setToasts] = useState<ToastData[]>([]);
  const [hasAnyKey, setHasAnyKey] = useState<boolean | null>(null);
  const [keyCount, setKeyCount] = useState(0);
  const [backendReachable, setBackendReachable] = useState<boolean | null>(null);

  const [debateDialogOpen, setDebateDialogOpen] = useState(false);
  const storedPanelCollapsed = useStoredValue("crucible_panel_collapsed");
  const panelCollapsed = storedPanelCollapsed === "1";
  const setPanelCollapsed = useCallback((next: boolean) => {
    writeStoredValue("crucible_panel_collapsed", next ? "1" : "0");
  }, []);

  const storedDebateSession = useStoredValue("crucible_active_debate");
  const [activeDebateSession, setActiveDebateSession] = useState<string | null>(
    null,
  );
  // Adopt the persisted session on the first client render (see the ownership
  // check below, which drops it if it belongs to another thread).
  const [adoptedStoredSession, setAdoptedStoredSession] = useState(false);
  if (!adoptedStoredSession && storedDebateSession) {
    setAdoptedStoredSession(true);
    setActiveDebateSession(storedDebateSession);
  }
  // Debate nodes are read-only, so selection just expands the node in place.
  const [activeDebateNode, setActiveDebateNode] = useState<string | null>(null);
  const [allModelIds, setAllModelIds] = useState<string[]>([]);
  // Kept in a ref so the debate WS handler resolves names without re-subscribing.
  const allModelsRef = useRef<import("@/lib/api").ModelFamily[]>([]);
  const [debateMessages, setDebateMessages] = useState<Message[]>([]);
  const [debateRound, setDebateRound] = useState(0);
  const [debateMaxRounds, setDebateMaxRounds] = useState(3);
  const [debateStatus, setDebateStatus] = useState<"running" | "converged" | "completed">("running");
  const [debateConvergenceScore, setDebateConvergenceScore] = useState<number | undefined>();

  const debateWsRef = useRef<WebSocket | null>(null);
  const debateStreamBufferRef = useRef<Record<string, string>>({});
  const debateRafRef = useRef<number | null>(null);
  const debateMsgIdMapRef = useRef<Record<string, string>>({});
  const pendingDebatePromptRef = useRef("");
  const debateParticipantsRef = useRef<string[]>([]);

  useEffect(() => {
    api
      .fetchKeyStatus()
      .then((status) => {
        const set = Object.values(status).filter((v) => v.set).length;
        setKeyCount(set);
        setHasAnyKey(set > 0);
        setBackendReachable(true);
      })
      .catch(() => {
        setHasAnyKey(true);
        setBackendReachable(false);
      });
  }, []);

  // The header slot now answers the question it implies: can we actually run?
  const connection = React.useMemo(() => {
    if (backendReachable === null)
      return { tone: "warn" as const, label: "Connecting…" };
    if (!backendReachable)
      return { tone: "error" as const, label: "Backend unreachable" };
    if (keyCount === 0)
      return { tone: "error" as const, label: "No API keys set" };
    return {
      tone: "ok" as const,
      label: `${keyCount} ${keyCount === 1 ? "key" : "keys"} · connected`,
    };
  }, [backendReachable, keyCount]);

  // Persisted debate defaults: the stored copy is the source of truth until the
  // user edits it, so read it through useSyncExternalStore rather than
  // hydrating with a mount effect.
  const storedDebateDefaults = useStoredValue("crucible_debate_defaults");
  const debateDefaults = React.useMemo<DebateDefaults>(() => {
    if (!storedDebateDefaults) return DEFAULT_DEBATE_DEFAULTS;
    try {
      return {
        ...DEFAULT_DEBATE_DEFAULTS,
        ...(JSON.parse(storedDebateDefaults) as Partial<DebateDefaults>),
      };
    } catch {
      return DEFAULT_DEBATE_DEFAULTS;
    }
  }, [storedDebateDefaults]);

  const setDebateDefaults = useCallback(
    (next: DebateDefaults | ((prev: DebateDefaults) => DebateDefaults)) => {
      const value =
        typeof next === "function"
          ? (next as (p: DebateDefaults) => DebateDefaults)(debateDefaults)
          : next;
      writeStoredValue("crucible_debate_defaults", JSON.stringify(value));
    },
    [debateDefaults],
  );

  // ─── Custom confirm dialog ──────────────────────────────────────
  const [confirmDialog, setConfirmDialog] = useState<{
    title: string;
    message: string;
    resolve: (v: boolean) => void;
  } | null>(null);
  const showConfirm = useCallback(
    (title: string, message: string): Promise<boolean> =>
      new Promise((resolve) => setConfirmDialog({ title, message, resolve })),
    [],
  );
  const handleConfirmClose = (accepted: boolean) => {
    confirmDialog?.resolve(accepted);
    setConfirmDialog(null);
  };

  // ─── Custom Hooks ────────────────────────────────────────────────
  const setMessagesRef = useRef<any>(null);

  const handleMessagesLoaded = useCallback((msgs: any[]) => {
    setMessagesRef.current?.((prev: any[]) => {
      return msgs.map((newMsg, idx) => {
        const existing = prev.find((p: any) => p.id === newMsg.id) || prev[idx];
        if (
          existing &&
          existing.role === newMsg.role &&
          (existing.model === newMsg.model || !newMsg.model)
        ) {
          return { ...newMsg, id: existing.id || newMsg.id || `stable-${idx}` };
        }
        return { ...newMsg, id: newMsg.id || `stable-${idx}` };
      });
    });
  }, []);

  const handleHistoryLoaded = useCallback((data: any) => {
    const cpId = data.current_checkpoint;
    const activeNode = (data.nodes || []).find((n: any) => n.id === cpId);
    if (activeNode?.metadata?.active_peer) {
      const model = activeNode.metadata.active_peer;
      setSelectedModels((prev) => {
        if (prev.length === 1 && prev[0] === model) return prev;
        return [model];
      });
    }
  }, []);

  const {
    nodes,
    setNodes,
    edges,
    activeCheckpoint,
    setActiveCheckpoint,
    showTree,
    setShowTree,
    isHistoryLoading,
    fetchHistory,
    clearTree,
  } = useHistoryTree(handleMessagesLoaded, handleHistoryLoaded);

  const handleThreadDeleted = useCallback(
    (deleted?: boolean) => {
      clearTree();
      setMessagesRef.current?.([]);
      setDocuments({});
      if (deleted)
        setToasts((prev) => [
          ...prev,
          {
            id: Date.now().toString(),
            message: "Experiment deleted",
            type: "info",
          },
        ]);
    },
    [clearTree],
  );

  const {
    threadId,
    threads,
    fetchThreads,
    startNewExperiment,
    switchThread,
    deleteThread,
    renameThread,
  } = useThreads(handleThreadDeleted, fetchHistory, showConfirm);

  const {
    messages,
    setMessages,
    isLoading,
    sendInteractiveMessage,
    synthesizeConsensus,
    stopStreaming,
  } = useChatWebSocket({
    threadId,
    activeCheckpoint,
    selectedModels,
    toggles,
    documents,
    clearDocuments: useCallback(() => setDocuments({}), []),
    onHistoryRefreshNeeded: fetchHistory,
    setActiveCheckpoint,
    setErrorModals,
    showConfirm,
  });

  useEffect(() => {
    setMessagesRef.current = setMessages;
  }, [setMessages]);

  // ─── Debate Tree ─────────────────────────────────────────────────
  const {
    nodes: debateNodes,
    edges: debateEdges,
    lanes: debateLanes,
    sessionMeta: debateSessionMeta,
    fetchTree: fetchDebateTree,
    clearTree: clearDebateTree,
    startPolling: startDebatePolling,
    stopPolling: stopDebatePolling,
    addPendingNode,
    resolvePendingNode,
  } = useDebateTree();

  // ─── Debate Helpers ──────────────────────────────────────────────
  const flushDebateBuffer = useCallback(() => {
    const buf = debateStreamBufferRef.current;
    if (!Object.keys(buf).length) return;
    const snapshot = { ...buf };
    debateStreamBufferRef.current = {};
    setDebateMessages((prev) =>
      prev.map((m) => {
        if (m.streaming && m.id && snapshot[m.id]) {
          return { ...m, content: m.content + snapshot[m.id] };
        }
        return m;
      }),
    );
  }, []);

  const scheduleDebateFlush = useCallback(() => {
    if (debateRafRef.current) return;
    debateRafRef.current = requestAnimationFrame(() => {
      debateRafRef.current = null;
      flushDebateBuffer();
    });
  }, [flushDebateBuffer]);

  const handleDebateMessage = useCallback(
    (msg: any, sessionId: string) => {
      switch (msg.type) {
        case "debate_session_created":
          debateParticipantsRef.current = msg.participants ?? [];
          break;

        case "debate_round_start": {
          const r = msg.round ?? 0;
          setDebateRound(r);
          setDebateStatus("running");
          setDebateMessages((prev) => [
            ...prev,
            { id: `round-header-${r}`, role: "system", type: "round_header", content: `Round ${r + 1}` },
          ]);
          // Optimistic pending nodes for each participant
          debateParticipantsRef.current.forEach((modelId, i) => {
            addPendingNode(
              modelId,
              msg.round ?? 0,
              i,
              modelFamilyColor(modelId),
              modelDisplayName(modelId, allModelsRef.current),
            );
          });
          break;
        }

        case "stream_start": {
          const msgId = `debate-${msg.model}-r${msg.round ?? 0}-${Date.now()}`;
          debateMsgIdMapRef.current[msg.model] = msgId;
          setDebateMessages((prev) => [
            ...prev,
            { id: msgId, role: "assistant", model: msg.model, content: "", streaming: true },
          ]);
          break;
        }

        case "stream_token": {
          const targetId = debateMsgIdMapRef.current[msg.model];
          if (targetId) {
            debateStreamBufferRef.current[targetId] =
              (debateStreamBufferRef.current[targetId] ?? "") + msg.token;
            scheduleDebateFlush();
          }
          break;
        }

        case "stream_end": {
          flushDebateBuffer();
          const targetId = debateMsgIdMapRef.current[msg.model];
          if (targetId) {
            setDebateMessages((prev) =>
              prev.map((m) =>
                m.id === targetId
                  ? { ...m, content: msg.content ?? m.content, streaming: false }
                  : m,
              ),
            );
            delete debateMsgIdMapRef.current[msg.model];
          }
          resolvePendingNode(msg.model, sessionId);
          break;
        }

        case "debate_round_end":
          if (msg.convergence_score != null) {
            setDebateConvergenceScore(msg.convergence_score);
          }
          fetchDebateTree(sessionId);
          break;

        case "debate_converged":
          setDebateStatus("converged");
          if (msg.score != null) setDebateConvergenceScore(msg.score);
          break;

        case "debate_synthesis_start": {
          const synthId = `debate-synthesis-${Date.now()}`;
          debateMsgIdMapRef.current["__synthesis__"] = synthId;
          if (msg.model) debateMsgIdMapRef.current[msg.model] = synthId;
          setDebateMessages((prev) => [
            ...prev,
            { id: synthId, role: "assistant", model: msg.model, content: "", streaming: true, type: "synthesis" },
          ]);
          break;
        }

        case "debate_synthesis_end": {
          flushDebateBuffer();
          const synthId = debateMsgIdMapRef.current["__synthesis__"];
          if (synthId) {
            setDebateMessages((prev) =>
              prev.map((m) =>
                m.id === synthId
                  ? { ...m, content: msg.content ?? m.content, streaming: false }
                  : m,
              ),
            );
            delete debateMsgIdMapRef.current["__synthesis__"];
            if (msg.model) delete debateMsgIdMapRef.current[msg.model];
          }
          fetchDebateTree(sessionId);
          // Poll for completed status in case the WS event arrives late
          setTimeout(() => {
            api.fetchDebateSession(sessionId)
              .then((s) => { if (s.status === "completed") setDebateStatus("completed"); })
              .catch(() => {});
          }, 2000);
          break;
        }

        case "debate_session_status":
          if (msg.status === "completed") {
            setDebateStatus("completed");
            stopDebatePolling();
            fetchDebateTree(sessionId);
            // Reset regular messages so post-debate chat starts clean below the debate view
            setMessages([]);
          }
          break;

        case "error":
          console.error("[Debate WS] error:", msg.message);
          break;
      }
    },
    [
      addPendingNode,
      scheduleDebateFlush,
      flushDebateBuffer,
      resolvePendingNode,
      fetchDebateTree,
      stopDebatePolling,
      setMessages,
    ],
  );

  const handleDebateOpen = useCallback((prompt: string) => {
    pendingDebatePromptRef.current = prompt;
    setDebateDialogOpen(true);
  }, []);

  const handleDebateInject = useCallback((message: string) => {
    if (!debateWsRef.current || debateWsRef.current.readyState !== WebSocket.OPEN) return;
    debateWsRef.current.send(JSON.stringify({ type: "debate_inject", message }));
    setDebateMessages((prev) => [
      ...prev,
      { id: `inject-${Date.now()}`, role: "user", content: message, type: "inject" },
    ]);
  }, []);

  const handleDebateRedirect = useCallback((message: string) => {
    if (!debateWsRef.current || debateWsRef.current.readyState !== WebSocket.OPEN) return;
    pendingDebatePromptRef.current = message;
    debateWsRef.current.send(JSON.stringify({ type: "debate_redirect", message }));
    setDebateMessages((prev) => [
      ...prev,
      { id: `redirect-${Date.now()}`, role: "user", content: message, type: "redirect" },
    ]);
  }, []);

  const handleDebateStop = useCallback(() => {
    if (debateWsRef.current && debateWsRef.current.readyState === WebSocket.OPEN) {
      debateWsRef.current.send(JSON.stringify({ type: "debate_control", action: "stop" }));
    }
    setDebateStatus("completed");
  }, []);

  const handleDebateSynthesize = useCallback(() => {
    if (!debateWsRef.current || debateWsRef.current.readyState !== WebSocket.OPEN) return;
    debateWsRef.current.send(
      JSON.stringify({
        type: "debate_synthesize",
        synthesizer_model: debateDefaults.synthesizer_model || debateParticipantsRef.current[0],
        prompt: pendingDebatePromptRef.current,
        toggles,
      }),
    );
  }, [debateDefaults.synthesizer_model, toggles]);

  // Clear debate when switching threads or exiting debate mode
  const clearDebateSession = useCallback(() => {
    debateWsRef.current?.close();
    debateWsRef.current = null;
    setActiveDebateSession(null);
    setDebateMessages([]);
    setDebateRound(0);
    setDebateStatus("running");
    setDebateConvergenceScore(undefined);
    setActiveDebateNode(null);
    clearDebateTree();
  }, [clearDebateTree]);

  // Drop the debate view when switching to a DIFFERENT thread (not on mount).
  //
  // Split deliberately: the state reset runs during render, which is React's
  // documented way to adjust state when a prop changes and means a stale debate
  // never paints for a frame. The socket/interval teardown is impure, so it
  // stays in an effect keyed on threadId.
  const [debateThreadKey, setDebateThreadKey] = useState<string | null>(threadId);
  if (threadId !== debateThreadKey) {
    setDebateThreadKey(threadId);
    if (debateThreadKey !== null) {
      setActiveDebateSession(null);
      setActiveDebateNode(null);
      setDebateMessages([]);
      setDebateRound(0);
      setDebateStatus("running");
      setDebateConvergenceScore(undefined);
    }
  }

  useEffect(() => {
    return () => {
      debateWsRef.current?.close();
      debateWsRef.current = null;
      stopDebatePolling();
    };
  }, [threadId, stopDebatePolling]);

  // Persist active debate session to localStorage
  useEffect(() => {
    writeStoredValue("crucible_active_debate", activeDebateSession);
  }, [activeDebateSession]);

  // Restore debate tree whenever activeDebateSession is set (covers initial load
  // from localStorage). A restored session is only honoured once a thread is
  // open and only if it belongs to that thread — otherwise a stale session from
  // an earlier visit would take over the tree view of an unrelated thread.
  const restoredDebateRef = useRef<string | null>(null);
  useEffect(() => {
    if (!activeDebateSession || !threadId) return;
    if (restoredDebateRef.current === activeDebateSession) return;
    restoredDebateRef.current = activeDebateSession;
    api.fetchDebateSession(activeDebateSession)
      .then((s) => {
        if (s.parent_thread_id !== threadId) {
          restoredDebateRef.current = null;
          setActiveDebateSession(null);
          return;
        }
        fetchDebateTree(activeDebateSession);
        setDebateStatus(s.status === "completed" ? "completed" : s.status === "running" ? "running" : "converged");
        setDebateRound(s.current_round);
        setDebateMaxRounds(s.termination_policy.max_rounds);
        debateParticipantsRef.current = s.participants;
        api.loadDebateMessages(s).then(setDebateMessages).catch(() => {});
      })
      .catch(() => {
        restoredDebateRef.current = null;
        setActiveDebateSession(null);
      });
  }, [activeDebateSession, threadId, fetchDebateTree]);

  // Fetch full model list for DebateConfigDialog
  useEffect(() => {
    api.fetchModels()
      .then((data) => {
        allModelsRef.current = data.families;
        setAllModelIds(data.families.flatMap((f) => f.models.map((m) => m.id)));
        if (data.default_model) {
          setSelectedModels((prev) =>
            prev.length ? prev : [data.default_model as string],
          );
        }
      })
      .catch(() => {});
  }, []);

  // Fetch debate sessions for sidebar whenever thread list changes
  const [debateSessions, setDebateSessions] = useState<import("@/lib/types").DebateSession[]>([]);
  useEffect(() => {
    api.listDebateSessions()
      .then(setDebateSessions)
      .catch(() => {});
  }, [threads]);

  // Auto-activate latest debate when switching to a debate-only thread (no regular chat)
  useEffect(() => {
    if (!threadId || isHistoryLoading || nodes.length > 0 || activeDebateSession) return;
    // Sessions arrive newest-first from the API.
    const threadDebates = debateSessions.filter((s) => s.parent_thread_id === threadId);
    if (threadDebates.length === 0) return;
    const latest =
      threadDebates.find((s) => s.current_round > 0 || s.status === "completed") ??
      threadDebates[0];
    // Activate only once the session resolves, so a deleted or unreadable
    // session can never leave the tree view stuck on an empty debate.
    api.fetchDebateSession(latest.session_id)
      .then((s) => {
        setActiveDebateSession(s.session_id);
        setDebateRound(s.current_round);
        setDebateMaxRounds(s.termination_policy.max_rounds);
        setDebateStatus(s.status === "completed" ? "completed" : "running");
        debateParticipantsRef.current = s.participants;
        setShowTree(true);
        fetchDebateTree(s.session_id);
        api.loadDebateMessages(s).then(setDebateMessages).catch(() => {});
      })
      .catch(() => {});
  }, [threadId, isHistoryLoading, nodes.length, activeDebateSession]); // eslint-disable-line react-hooks/exhaustive-deps

  // ─── Component Handlers ──────────────────────────────────────────
  const handleFileUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    try {
      if (!threadId) return;
      const data = await api.uploadDocument(file, threadId);
      setDocuments((prev) => ({ ...prev, [data.filename]: data.full_content }));
    } catch (error) {
      console.error("Upload error:", error);
    }
  };

  const deleteNode = useCallback(
    async (nodeId?: string) => {
      const targetId = nodeId || activeCheckpoint;
      if (!targetId || !threadId) return;
      if (
        !(await showConfirm(
          "Delete Node",
          "This will remove this checkpoint and all its descendants. This action cannot be undone.",
        ))
      )
        return;
      try {
        await api.deleteCheckpoint(threadId, targetId);

        // Handle navigation after deletion
        if (activeCheckpoint === targetId) {
          const parentEdge = edges.find((e) => e.target === targetId);
          const parentId = parentEdge ? parentEdge.source : null;
          setMessages([]);
          setActiveCheckpoint(parentId || null);
          fetchHistory(threadId, parentId || undefined);
        } else {
          // Just refresh the tree if we deleted something else
          fetchHistory(threadId, activeCheckpoint || undefined);
        }
        fetchThreads();
      } catch (error) {
        console.error("Node deletion failed:", error);
      }
    },
    [
      activeCheckpoint,
      threadId,
      showConfirm,
      edges,
      fetchHistory,
      fetchThreads,
      setMessages,
      setActiveCheckpoint,
    ],
  );

  const editAndRebranch = useCallback(() => {
    const node = nodes.find((n) => n.id === activeCheckpoint);
    if (node && threadId) {
      const parentEdge = edges.find((e) => e.target === node.id);
      const parentId = parentEdge ? parentEdge.source : null;
      setActiveCheckpoint(parentId || null);
      fetchHistory(threadId, parentId || undefined);
      setInput(node.data.label.replace("...", ""));
      setShowTree(false);
    }
  }, [
    activeCheckpoint,
    nodes,
    edges,
    threadId,
    fetchHistory,
    setActiveCheckpoint,
    setInput,
    setShowTree,
  ]);

  const activeCheckpointData = React.useMemo(
    () => nodes.find((n: any) => n.id === activeCheckpoint),
    [nodes, activeCheckpoint],
  );

  const handleNodeClick = useCallback(
    (id: string) => {
      setActiveCheckpoint(id);
      if (threadId) fetchHistory(threadId, id);
    },
    [threadId, fetchHistory, setActiveCheckpoint],
  );

  const handleNodeDragStop = useCallback(
    async (nodeId: string, position: { x: number; y: number }) => {
      if (!threadId) return;

      // Update local state immediately to prevent "snapping" on parent re-render
      setNodes((prevNodes: any[]) =>
        prevNodes.map((n) =>
          n.id === nodeId ? { ...n, position: { ...position } } : n,
        ),
      );

      api.saveNodePositions(threadId, [
        { node_id: nodeId, x: position.x, y: position.y },
      ]);
    },
    [threadId, setNodes],
  );

  // "Tidy Layout" moves every node at once — one request, not one per node.
  const handleLayoutPositions = useCallback(
    (updates: { node_id: string; x: number; y: number }[]) => {
      if (!threadId || updates.length === 0) return;
      setNodes((prevNodes: any[]) => {
        const byId = new Map(updates.map((u) => [u.node_id, u]));
        return prevNodes.map((n) => {
          const u = byId.get(n.id);
          return u ? { ...n, position: { x: u.x, y: u.y } } : n;
        });
      });
      api.saveNodePositions(threadId, updates);
    },
    [threadId, setNodes],
  );

  // Deliberately does not call setShowTree. Sending used to yank you out of the
  // tree; the view now changes only when you change it.
  const handleSendMessage = useCallback(
    (text: string) => {
      sendInteractiveMessage(text, false);
      setInput("");
    },
    [sendInteractiveMessage, setInput],
  );

  const handleDeliberate = useCallback(
    (text: string) => {
      sendInteractiveMessage(text, true);
      setInput("");
    },
    [sendInteractiveMessage, setInput],
  );

  const handleSwitchCheckpoint = useCallback(
    (id: string) => {
      setActiveCheckpoint(id);
      if (threadId) fetchHistory(threadId, id);
    },
    [threadId, fetchHistory, setActiveCheckpoint],
  );

  const handleSynthesize = useCallback(
    (contents: string[], targetParentId: string | null) => {
      synthesizeConsensus(contents, targetParentId);
    },
    [synthesizeConsensus],
  );

  return (
    <Box
      sx={{
        display: "flex",
        height: "100vh",
        width: "100vw",
        overflow: "hidden",
        bgcolor: "background.default",
        transition: "background-color 0.7s",
        py: 2,
      }}
    >
      <Sidebar
        threads={threads}
        threadId={threadId}
        editingThreadId={editingThreadId}
        editingTitle={editingTitle}
        onStartNewExperiment={startNewExperiment}
        onSwitchThread={switchThread}
        onDeleteThread={deleteThread}
        onRenameThread={renameThread}
        setEditingThreadId={setEditingThreadId}
        setEditingTitle={setEditingTitle}
        onSwitchCheckpoint={handleSwitchCheckpoint}
        debateSessions={debateSessions}
        activeDebateSessionId={activeDebateSession}
        onSwitchDebateSession={(sessionId) => {
          setActiveDebateSession(sessionId);
          fetchDebateTree(sessionId);
          api.fetchDebateSession(sessionId).then((s) => {
            setDebateRound(s.current_round);
            setDebateMaxRounds(s.termination_policy.max_rounds);
            setDebateStatus(s.status === "completed" ? "completed" : "running");
            debateParticipantsRef.current = s.participants;
            api.loadDebateMessages(s).then(setDebateMessages).catch(() => {});
          }).catch(() => {});
          setShowTree(true);
        }}
      />

      <Box
        component="section"
        sx={{
          flexGrow: 1,
          display: "flex",
          flexDirection: "column",
          position: "relative",
          minWidth: 0,
          overflow: "hidden",
          borderRadius: "40px",
          mx: 2,
          bgcolor: "background.paper",
          border: "1px solid",
          borderColor: "divider",
          backdropFilter: "blur(16px)",
          zIndex: 10,
        }}
      >
        <Box
          component="header"
          sx={{
            px: { xs: 3, md: 5 },
            py: 3,
            display: "flex",
            justifyContent: "space-between",
            alignItems: "center",
            position: "relative",
            zIndex: 20,
            borderBottom: "1px solid",
            borderColor: "divider",
            bgcolor: isDark
              ? "rgba(255, 255, 255, 0.01)"
              : "rgba(255, 255, 255, 0.6)",
            boxShadow: isDark
              ? "0 4px 30px rgba(0, 0, 0, 0.1)"
              : "0 4px 30px rgba(0, 0, 0, 0.03)",
          }}
        >
          <ButtonBase
            onClick={() => {
              // Same as clear thread logic
              switchThread(""); // trigger switch to empty
            }}
            sx={{
              display: "flex",
              alignItems: "center",
              gap: 2,
              textAlign: "left",
              borderRadius: 3,
              p: 0.5,
              ml: -0.5,
              transition: "all 0.2s ease",
              "&:hover": {
                bgcolor: isDark ? "rgba(255,255,255,0.05)" : "rgba(0,0,0,0.03)",
              },
            }}
          >
            <Box
              sx={{
                width: 44,
                height: 44,
                borderRadius: 3.5,
                background: isDark
                  ? "linear-gradient(135deg, rgba(37,99,235,0.8), rgba(124,58,237,0.8))"
                  : "linear-gradient(135deg, #2563eb, #7c3aed)",
                display: "flex",
                alignItems: "center",
                justifyContent: "center",
                boxShadow: isDark
                  ? "0 8px 24px -6px rgba(124,58,237,0.4), inset 0 1px 1px rgba(255,255,255,0.2)"
                  : "0 8px 24px -6px rgba(37,99,235,0.4), inset 0 1px 1px rgba(255,255,255,0.4)",
              }}
            >
              <Zap width={22} height={22} color="white" />
            </Box>

            <Box>
              <Typography
                variant="h6"
                sx={{
                  fontWeight: 900,
                  letterSpacing: "0.15em",
                  lineHeight: 1.1,
                  color: "text.primary",
                }}
              >
                THE CRUCIBLE
              </Typography>
              <Box
                sx={{
                  display: "flex",
                  alignItems: "center",
                  gap: 0.75,
                  mt: 0.5,
                }}
              >
                <Box
                  sx={{
                    width: 6,
                    height: 6,
                    borderRadius: "50%",
                    bgcolor:
                      connection.tone === "ok"
                        ? "success.main"
                        : connection.tone === "warn"
                          ? "warning.main"
                          : "error.main",
                    boxShadow:
                      connection.tone === "ok"
                        ? "0 0 8px rgba(16,185,129,0.5)"
                        : "none",
                  }}
                />
                <Typography
                  variant="overline"
                  sx={{
                    fontSize: "0.6rem",
                    fontWeight: 800,
                    letterSpacing: "0.2em",
                    color: "text.secondary",
                    lineHeight: 1,
                  }}
                >
                  {connection.label}
                </Typography>
              </Box>
            </Box>
          </ButtonBase>

          <Box sx={{ display: "flex", alignItems: "center", gap: 2 }}>
            <Box
              sx={{
                display: { xs: "none", sm: "flex" },
                alignItems: "center",
                gap: 1.5,
                px: 1.5,
                py: 0.75,
                borderRadius: 1.5,
                border: "1px solid",
                borderColor: "divider",
                bgcolor: isDark ? "rgba(255,255,255,0.03)" : "rgba(0,0,0,0.02)",
              }}
            >
              <Box sx={{ display: "flex", mr: 0.5 }}>
                {selectedModels.map((m, i) => (
                  <Box
                    key={m}
                    sx={{
                      width: 10,
                      height: 10,
                      borderRadius: "50%",
                      ml: i > 0 ? -0.75 : 0,
                      border: "2px solid",
                      borderColor: "background.paper",
                      bgcolor: modelFamilyColor(m),
                      boxShadow: "0 2px 4px rgba(0,0,0,0.1)",
                    }}
                  />
                ))}
              </Box>
              <Typography
                variant="overline"
                sx={{
                  fontSize: "0.6rem",
                  fontWeight: 800,
                  letterSpacing: "0.1em",
                  color: "text.secondary",
                  lineHeight: 1,
                }}
              >
                {selectedModels.length === 1
                  ? selectedModels[0].split("-")[0].toUpperCase()
                  : `${selectedModels.length} models`}
              </Typography>
            </Box>

            {/* Segmented, so the lit half states the CURRENT view. The old
                single button was labelled with its destination, which reads
                both ways and was routinely misread. */}
            <Box
              role="group"
              aria-label="View"
              sx={{
                display: "flex",
                p: 0.375,
                gap: 0.375,
                borderRadius: 2.5,
                border: "1px solid",
                borderColor: "divider",
                bgcolor: isDark ? "rgba(255,255,255,0.03)" : "rgba(0,0,0,0.03)",
              }}
            >
              {(
                [
                  { key: "tree", label: "Tree", icon: Layers },
                  { key: "arena", label: "Arena", icon: MessagesSquare },
                ] as const
              ).map(({ key, label, icon: Icon }) => {
                const active = key === "tree" ? showTree : !showTree;
                return (
                  <ButtonBase
                    key={key}
                    onClick={() => setShowTree(key === "tree")}
                    aria-pressed={active}
                    sx={{
                      px: 1.75,
                      py: 0.75,
                      borderRadius: 2,
                      display: "flex",
                      alignItems: "center",
                      gap: 0.75,
                      fontWeight: 800,
                      fontSize: "0.625rem",
                      letterSpacing: "0.14em",
                      textTransform: "uppercase",
                      transition: "background-color .18s ease, color .18s ease",
                      color: active
                        ? isDark
                          ? "primary.light"
                          : "primary.main"
                        : "text.secondary",
                      bgcolor: active
                        ? isDark
                          ? "rgba(37,99,235,0.16)"
                          : "primary.50"
                        : "transparent",
                      "&:hover": {
                        bgcolor: active
                          ? isDark
                            ? "rgba(37,99,235,0.22)"
                            : "primary.100"
                          : isDark
                            ? "rgba(255,255,255,0.05)"
                            : "rgba(0,0,0,0.04)",
                      },
                    }}
                  >
                    <Icon width={13} height={13} />
                    {label}
                  </ButtonBase>
                );
              })}
            </Box>

            <IconButton
              component={motion.button}
              whileHover={{ scale: 1.1, rotate: 15 }}
              whileTap={{ scale: 0.9 }}
              onClick={toggleMode}
              aria-label={isDark ? "Switch to light theme" : "Switch to dark theme"}
              sx={{
                border: "1px solid",
                borderColor: "divider",
                bgcolor: isDark ? "rgba(255,255,255,0.03)" : "background.paper",
                color: isDark ? "#fbbf24" : "text.secondary",
                "&:hover": {
                  bgcolor: isDark ? "rgba(255,255,255,0.08)" : "divider",
                },
              }}
            >
              {isDark ? (
                <Sun width={18} height={18} />
              ) : (
                <Moon width={18} height={18} />
              )}
            </IconButton>
          </Box>
        </Box>

        <div className="flex-1 relative flex flex-col min-h-0 w-full h-full">
          <AnimatePresence mode="wait">
            {!threadId ? (
              <motion.div
                key="landing"
                initial={{ opacity: 0, filter: "blur(10px)" }}
                animate={{ opacity: 1, filter: "blur(0px)" }}
                exit={{ opacity: 0, scale: 0.95 }}
                transition={{ duration: 0.4 }}
                className="absolute inset-0 w-full h-full flex"
              >
                <LandingView
                  onStartNewExperiment={startNewExperiment}
                  hasAnyKey={hasAnyKey}
                />
              </motion.div>
            ) : showTree ? (
              <motion.div
                key="tree"
                initial={{ opacity: 0 }}
                animate={{ opacity: 1 }}
                exit={{ opacity: 0 }}
                transition={{ duration: 0.2 }}
                className="absolute inset-0 w-full h-full"
              >
                {activeDebateSession ? (
                  <TreeCanvas
                    key={`debate-${activeDebateSession}`}
                    nodes={debateNodes}
                    edges={debateEdges}
                    debateMode
                    lanes={debateLanes}
                    roundScores={debateSessionMeta?.round_scores}
                    maxRound={debateSessionMeta?.max_round ?? debateRound}
                    activeNodeId={activeDebateNode || undefined}
                    onNodeClick={setActiveDebateNode}
                  />
                ) : (
                  <TreeCanvas
                    key={threadId}
                    nodes={nodes}
                    edges={edges}
                    activeNodeId={activeCheckpoint || undefined}
                    onNodeClick={handleNodeClick}
                    onNodeDragStop={handleNodeDragStop}
                    onLayoutPositions={handleLayoutPositions}
                    onDeleteNode={deleteNode}
                  />
                )}
              </motion.div>
            ) : (
              <motion.div
                key="chat"
                initial={{ opacity: 0 }}
                animate={{ opacity: 1 }}
                exit={{ opacity: 0 }}
                transition={{ duration: 0.2 }}
                className="absolute inset-0 w-full h-full flex flex-col"
              >
                <ChatView
                  messages={
                    activeDebateSession && debateMessages.length > 0
                      ? [...debateMessages, ...messages]
                      : messages
                  }
                  nodes={nodes}
                  edges={edges}
                  isLoading={isLoading || isHistoryLoading}
                  input={input}
                  setInput={setInput}
                  onSendMessage={handleSendMessage}
                  onSwitchCheckpoint={handleSwitchCheckpoint}
                  onSynthesize={handleSynthesize}
                  onDeliberate={handleDeliberate}
                  stopStreaming={stopStreaming}
                  setShowTree={setShowTree}
                  documents={documents}
                  setDocuments={setDocuments}
                  activeCheckpoint={activeCheckpoint}
                  onDeleteNode={deleteNode}
                  onEditAndRebranch={editAndRebranch}
                  onFileUpload={handleFileUpload}
                  showEditButton={
                    !activeDebateSession && activeCheckpointData?.metadata?.role === "user"
                  }
                  threadId={threadId}
                  selectedModels={selectedModels}
                  onDebateOpen={handleDebateOpen}
                  onDebateInject={activeDebateSession && debateStatus === "running" ? handleDebateInject : undefined}
                  onDebateRedirect={activeDebateSession && debateStatus === "running" ? handleDebateRedirect : undefined}
                  debateState={
                    activeDebateSession && debateMessages.length > 0
                      ? {
                          round: debateRound,
                          maxRounds: debateMaxRounds,
                          status: debateStatus,
                          convergenceScore: debateConvergenceScore,
                        }
                      : null
                  }
                  onDebateStop={
                    activeDebateSession
                      ? () => {
                          if (debateStatus === "running") handleDebateStop();
                          clearDebateSession();
                        }
                      : undefined
                  }
                  onDebateSynthesize={
                    activeDebateSession && debateMessages.length > 0 && debateStatus !== "running"
                      ? handleDebateSynthesize
                      : undefined
                  }
                />
              </motion.div>
            )}
          </AnimatePresence>
        </div>
      </Box>

      <ControlPanel
        toggles={toggles}
        setToggles={setToggles}
        selectedModels={selectedModels}
        setSelectedModels={setSelectedModels}
        messagesCount={nodes.length}
        threadId={threadId}
        activeCheckpointLabel={activeCheckpointData?.data?.label || "START"}
        debateDefaults={debateDefaults}
        setDebateDefaults={setDebateDefaults}
        collapsed={panelCollapsed}
        onCollapsedChange={setPanelCollapsed}
      />

      <DebateConfigDialog
        open={debateDialogOpen}
        onClose={() => setDebateDialogOpen(false)}
        onStart={async (config) => {
          setDebateDialogOpen(false);
          if (!threadId) return;
          try {
            const session = await api.createDebateSession({
              parent_thread_id: threadId,
              participants: selectedModels,
              termination_policy: {
                max_rounds: config.max_rounds,
                convergence_threshold: config.convergence_threshold,
                llm_judge: config.llm_judge,
                mode: config.mode,
              },
              auto_synthesize: config.auto_synthesize,
              synthesizer_model: config.synthesizer_model,
            });

            setActiveDebateSession(session.session_id);
            setDebateMaxRounds(config.max_rounds);
            setDebateRound(0);
            setDebateStatus("running");
            setDebateMessages([]);
            setDebateConvergenceScore(undefined);
            debateParticipantsRef.current = session.participants;
            setShowTree(true);

            const ws = new WebSocket(api.createDebateWebSocketUrl(session.session_id));
            debateWsRef.current = ws;

            ws.onopen = () => {
              ws.send(
                JSON.stringify({
                  type: "debate_start",
                  prompt: pendingDebatePromptRef.current,
                  toggles,
                  documents,
                  parent_checkpoint_id: activeCheckpoint,
                }),
              );
              startDebatePolling(session.session_id);
            };

            ws.onmessage = (ev) => {
              try {
                handleDebateMessage(JSON.parse(ev.data), session.session_id);
              } catch {}
            };

            ws.onerror = () => console.error("[Debate WS] connection error");
            ws.onclose = () => {
              debateWsRef.current = null;
            };
          } catch (e) {
            console.error("Failed to create debate session:", e);
          }
        }}
        defaults={debateDefaults}
        availableModels={allModelIds.length ? allModelIds : selectedModels}
      />

      <Dialog
        open={!!confirmDialog}
        onClose={() => handleConfirmClose(false)}
        PaperProps={{
          sx: {
            borderRadius: 3,
            bgcolor: isDark ? "#111827" : "#fff",
            border: "1px solid",
            borderColor: isDark ? "rgba(255,255,255,0.08)" : "divider",
            minWidth: 360,
            backgroundImage: "none",
          },
        }}
        slotProps={{
          backdrop: {
            sx: { backdropFilter: "blur(4px)", bgcolor: "rgba(0,0,0,0.5)" },
          },
        }}
      >
        <DialogTitle sx={{ fontWeight: 700, fontSize: "1rem", pb: 0.5 }}>
          {confirmDialog?.title}
        </DialogTitle>
        <DialogContent>
          <DialogContentText
            sx={{ fontSize: "0.85rem", color: "text.secondary" }}
          >
            {confirmDialog?.message}
          </DialogContentText>
        </DialogContent>
        <DialogActions sx={{ px: 3, pb: 2.5, gap: 1 }}>
          <Button
            onClick={() => handleConfirmClose(false)}
            size="small"
            sx={{
              textTransform: "none",
              fontWeight: 600,
              color: "text.secondary",
            }}
          >
            Cancel
          </Button>
          <Button
            onClick={() => handleConfirmClose(true)}
            variant="contained"
            size="small"
            color="error"
            sx={{
              textTransform: "none",
              fontWeight: 700,
              borderRadius: 2,
              px: 2.5,
              boxShadow: "none",
              "&:hover": { boxShadow: "none" },
            }}
          >
            Confirm
          </Button>
        </DialogActions>
      </Dialog>

      {errorModals.map((err) => (
        <ErrorModal
          key={err.id}
          title={err.title}
          details={err.details}
          suggestion={err.suggestion}
          onDismiss={() =>
            setErrorModals((prev) => prev.filter((e) => e.id !== err.id))
          }
        />
      ))}

      {toasts.map((toast, i) => (
        <Toast
          key={toast.id}
          {...toast}
          index={i}
          onDismiss={(id) => setToasts((t) => t.filter((x) => x.id !== id))}
        />
      ))}
    </Box>
  );
}
