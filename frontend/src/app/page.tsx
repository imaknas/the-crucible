"use client";

import React, { useCallback, useEffect, useRef, useState } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { Box } from "@mui/material";
import TreeCanvas from "@/components/TreeCanvas";
import Sidebar from "@/components/Sidebar";
import ControlPanel from "@/components/ControlPanel";
import ChatView from "@/components/ChatView";
import LandingView from "@/components/LandingView";
import ErrorModal from "@/components/ErrorModal";
import Toast from "@/components/Toast";
import DebateConfigDialog from "@/components/DebateConfigDialog";
import AppHeader from "@/components/AppHeader";
import ConfirmDialog from "@/components/ConfirmDialog";
import * as api from "@/lib/api";
import type { Message } from "@/lib/types";
import { useStoredValue, writeStoredValue } from "@/hooks/useStoredValue";
import { useThreads } from "@/hooks/useThreads";
import { useHistoryTree } from "@/hooks/useHistoryTree";
import { useChatWebSocket } from "@/hooks/useChatWebSocket";
import { useDebateSession } from "@/hooks/useDebateSession";
import { useToasts } from "@/hooks/useToasts";
import { useConfirm } from "@/hooks/useConfirm";
import { useBackendStatus } from "@/hooks/useBackendStatus";
import { useModelCatalog } from "@/hooks/useModelCatalog";
import { useDebateDefaults } from "@/hooks/useDebateDefaults";
import { useTreeActions } from "@/hooks/useTreeActions";

/**
 * The app shell. State lives in hooks; this component wires them together and
 * lays out Sidebar | main pane (header + tree or arena) | ControlPanel.
 *
 * The view never switches itself: sending a message leaves you where you are.
 * The exceptions are editAndRebranch (moving to the composer is the point) and
 * opening a debate, which shows its tree.
 */
export default function Home() {
  const [input, setInput] = useState("");
  const [editingThreadId, setEditingThreadId] = useState<string | null>(null);
  const [editingTitle, setEditingTitle] = useState("");
  const [documents, setDocuments] = useState<Record<string, string>>({});
  const [toggles, setToggles] = useState({ use_rag: true, use_web_search: false });
  const [errorModals, setErrorModals] = useState<
    { id: string; title: string; details: string; suggestion?: string }[]
  >([]);

  const storedPanelCollapsed = useStoredValue("crucible_panel_collapsed");
  const panelCollapsed = storedPanelCollapsed === "1";
  const setPanelCollapsed = useCallback((next: boolean) => {
    writeStoredValue("crucible_panel_collapsed", next ? "1" : "0");
  }, []);

  const { toasts, pushToast, dismissToast } = useToasts();
  const { confirm: showConfirm, request: confirmRequest, answer: answerConfirm } = useConfirm();
  const { connection, hasAnyKey } = useBackendStatus();
  const {
    families,
    status: modelsStatus,
    reloadModels,
    selectedModels,
    setSelectedModels,
    allModelIds,
    modelLabel,
  } = useModelCatalog();
  const { debateDefaults, setDebateDefaults } = useDebateDefaults();

  // ─── Conversation tree, threads, chat ───────────────────────────
  // useHistoryTree loads messages into the chat hook, which is created after
  // it; the ref breaks that cycle.
  const setMessagesRef = useRef<React.Dispatch<React.SetStateAction<Message[]>> | null>(null);

  const handleMessagesLoaded = useCallback((msgs: Message[]) => {
    setMessagesRef.current?.((prev) =>
      msgs.map((newMsg, idx) => {
        const existing = prev.find((p) => p.id === newMsg.id) || prev[idx];
        if (existing && existing.role === newMsg.role && (existing.model === newMsg.model || !newMsg.model)) {
          return { ...newMsg, id: existing.id || newMsg.id || `stable-${idx}` };
        }
        return { ...newMsg, id: newMsg.id || `stable-${idx}` };
      }),
    );
  }, []);

  // Opening a checkpoint selects the model that wrote it.
   
  const handleHistoryLoaded = useCallback((data: any) => {
     
    const activeNode = (data.nodes || []).find((n: any) => n.id === data.current_checkpoint);
    const model = activeNode?.metadata?.active_peer;
    if (model) setSelectedModels((prev) => (prev.length === 1 && prev[0] === model ? prev : [model]));
  }, [setSelectedModels]);

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
      if (deleted) pushToast("Experiment deleted");
    },
    [clearTree, pushToast],
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

  const clearDocuments = useCallback(() => setDocuments({}), []);
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
    clearDocuments,
    onHistoryRefreshNeeded: fetchHistory,
    setActiveCheckpoint,
    setErrorModals,
    showConfirm,
  });

  useEffect(() => {
    setMessagesRef.current = setMessages;
  }, [setMessages]);

  // ─── Debate ─────────────────────────────────────────────────────
  const clearChatMessages = useCallback(() => setMessages([]), [setMessages]);
  const debate = useDebateSession({
    threadId,
    threads,
    fetchThreads,
    historyNodeCount: nodes.length,
    isHistoryLoading,
    setShowTree,
    clearChatMessages,
    pushToast,
    confirm: showConfirm,
    modelLabel,
  });
  const inDebate = !!debate.activeSessionId;
  const debateHasTranscript = debate.messages.length > 0;

  // ─── Tree node & composer actions ───────────────────────────────
  const handleFileUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file || !threadId) return;
    try {
      const data = await api.uploadDocument(file, threadId);
      setDocuments((prev) => ({ ...prev, [data.filename]: data.full_content }));
    } catch (error) {
      console.error("Upload error:", error);
      pushToast("Upload failed.");
    }
  };

  const {
    activeCheckpointNode,
    selectCheckpoint,
    deleteNode,
    editAndRebranch,
    moveNode,
    applyLayout,
  } = useTreeActions({
    threadId,
    nodes,
    edges,
    setNodes,
    activeCheckpoint,
    setActiveCheckpoint,
    fetchHistory,
    fetchThreads,
    clearChatMessages,
    setInput,
    setShowTree,
    confirm: showConfirm,
    pushToast,
  });

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
        onSwitchCheckpoint={selectCheckpoint}
        debateSessions={debate.sessions}
        activeDebateSessionId={debate.activeSessionId}
        modelLabel={modelLabel}
        onDeleteDebateSession={debate.remove}
        onSwitchDebateSession={debate.switchTo}
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
        <AppHeader
          connection={connection}
          selectedModels={selectedModels}
          showTree={showTree}
          onShowTreeChange={setShowTree}
          onHome={() => switchThread("")}
        />

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
                <LandingView onStartNewExperiment={startNewExperiment} hasAnyKey={hasAnyKey} />
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
                {inDebate ? (
                  <TreeCanvas
                    key={`debate-${debate.activeSessionId}`}
                    nodes={debate.tree.nodes}
                    edges={debate.tree.edges}
                    debateMode
                    lanes={debate.tree.lanes}
                    roundScores={debate.tree.sessionMeta?.round_scores}
                    maxRound={debate.tree.sessionMeta?.max_round ?? debate.round}
                    activeNodeId={debate.activeNode || undefined}
                    onNodeClick={debate.setActiveNode}
                  />
                ) : (
                  <TreeCanvas
                    key={threadId}
                    nodes={nodes}
                    edges={edges}
                    activeNodeId={activeCheckpoint || undefined}
                    onNodeClick={selectCheckpoint}
                    onNodeDragStop={moveNode}
                    onLayoutPositions={applyLayout}
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
                  messages={inDebate && debateHasTranscript ? [...debate.messages, ...messages] : messages}
                  nodes={nodes}
                  edges={edges}
                  isLoading={isLoading || isHistoryLoading}
                  input={input}
                  setInput={setInput}
                  onSendMessage={handleSendMessage}
                  onSwitchCheckpoint={selectCheckpoint}
                  onSynthesize={synthesizeConsensus}
                  onDeliberate={handleDeliberate}
                  stopStreaming={stopStreaming}
                  setShowTree={setShowTree}
                  documents={documents}
                  setDocuments={setDocuments}
                  activeCheckpoint={activeCheckpoint}
                  onDeleteNode={deleteNode}
                  onEditAndRebranch={editAndRebranch}
                  onFileUpload={handleFileUpload}
                  showEditButton={!inDebate && activeCheckpointNode?.metadata?.role === "user"}
                  threadId={threadId}
                  selectedModels={selectedModels}
                  onDebateOpen={debate.openDialog}
                  onDebateInject={inDebate && debate.controls.inject ? debate.inject : undefined}
                  onDebateRedirect={inDebate && debate.controls.redirect ? debate.redirect : undefined}
                  debateState={
                    inDebate && debateHasTranscript
                      ? {
                          round: debate.round,
                          maxRounds: debate.maxRounds,
                          status: debate.status,
                          convergenceScore: debate.convergenceScore,
                        }
                      : null
                  }
                  onDebateStop={inDebate ? debate.close : undefined}
                  onDebateSynthesize={
                    inDebate && debate.controls.synthesize
                      ? () => debate.synthesize(debateDefaults.synthesizer_model, toggles)
                      : undefined
                  }
                  onDebatePause={inDebate && debate.controls.pause ? debate.pause : undefined}
                  onDebateResume={inDebate && debate.controls.resume ? debate.resume : undefined}
                />
              </motion.div>
            )}
          </AnimatePresence>
        </div>
      </Box>

      <ControlPanel
        toggles={toggles}
        setToggles={setToggles}
        families={families}
        modelsStatus={modelsStatus}
        onReloadModels={reloadModels}
        selectedModels={selectedModels}
        setSelectedModels={setSelectedModels}
        messagesCount={nodes.length}
        activeCheckpointLabel={activeCheckpointNode?.data?.label || "START"}
        debateDefaults={debateDefaults}
        setDebateDefaults={setDebateDefaults}
        collapsed={panelCollapsed}
        onCollapsedChange={setPanelCollapsed}
      />

      <DebateConfigDialog
        open={debate.dialogOpen}
        onClose={debate.closeDialog}
        onStart={(config) =>
          debate.start(config, {
            participants: selectedModels,
            toggles,
            documents,
            parentCheckpointId: activeCheckpoint,
          })
        }
        defaults={debateDefaults}
        availableModels={allModelIds.length ? allModelIds : selectedModels}
      />

      <ConfirmDialog request={confirmRequest} onAnswer={answerConfirm} />

      {errorModals.map((err) => (
        <ErrorModal
          key={err.id}
          title={err.title}
          details={err.details}
          suggestion={err.suggestion}
          onDismiss={() => setErrorModals((prev) => prev.filter((e) => e.id !== err.id))}
        />
      ))}

      {toasts.map((toast, i) => (
        <Toast key={toast.id} {...toast} index={i} onDismiss={dismissToast} />
      ))}
    </Box>
  );
}
