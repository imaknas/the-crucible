"use client";

import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
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
import DebateBanner, { type DebateBannerProps } from "@/components/DebateBanner";
import ConfirmDialog from "@/components/ConfirmDialog";
import * as api from "@/lib/api";
import { errorMessage } from "@/lib/errors";
import type { Message } from "@/lib/types";
import { useLayoutPanels } from "@/hooks/useLayoutPanels";
import { useThreads } from "@/hooks/useThreads";
import { useHistoryTree } from "@/hooks/useHistoryTree";
import { useChatWebSocket } from "@/hooks/useChatWebSocket";
import { useDebateSession } from "@/hooks/useDebateSession";
import { useToasts } from "@/hooks/useToasts";
import { useConfirm } from "@/hooks/useConfirm";
import { useBackendStatus } from "@/hooks/useBackendStatus";
import { useModelCatalog } from "@/hooks/useModelCatalog";
import { useSummarizerChoice } from "@/hooks/useSummarizerChoice";
import { useSystemPrompt } from "@/hooks/useSystemPrompt";
import { useDebateDefaults } from "@/hooks/useDebateDefaults";
import { useToggles } from "@/hooks/useToggles";
import { useTreeActions } from "@/hooks/useTreeActions";
import { useReplyTarget } from "@/hooks/useReplyTarget";
import { afterDebateRecord, peerLegend } from "@/lib/debateTranscript";
import { reconcileMessages } from "@/lib/messages";

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
  const [documents, setDocuments] = useState<Record<string, string>>({});
  const { toggles, setToggles } = useToggles();
  const [errorModals, setErrorModals] = useState<
    { id: string; title: string; details: string; suggestion?: string }[]
  >([]);

  const layout = useLayoutPanels();

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
    availableModelIds,
    modelLabel,
    defaultSummarizer,
  } = useModelCatalog();
  const { choice: summarizerChoice, summarizer, setChoice: setSummarizerChoice } = useSummarizerChoice(families);
  const { text: systemPromptText, systemPrompt, setText: setSystemPromptText } = useSystemPrompt();
  const { debateDefaults, setDebateDefaults } = useDebateDefaults();

  // ─── Conversation tree, threads, chat ───────────────────────────
  // useHistoryTree loads messages into the chat hook, which is created after
  // it; the ref breaks that cycle.
  const setMessagesRef = useRef<React.Dispatch<React.SetStateAction<Message[]>> | null>(null);

  const handleMessagesLoaded = useCallback((msgs: Message[]) => {
    setMessagesRef.current?.((prev) => reconcileMessages(prev, msgs));
  }, []);

  const {
    nodes,
    setNodes,
    edges,
    chosen,
    setChosen,
    head,
    shown,
    showTree,
    setShowTree,
    isHistoryLoading,
    fetchHistory,
    clearTree,
  } = useHistoryTree(handleMessagesLoaded, pushToast);

  // Leaving the open thread stops whatever runs on it (its sockets close).
  // The guard is composed further down from the chat and the debate, which
  // need the thread id first; the ref breaks that cycle.
  const leaveGuardRef = useRef<() => Promise<boolean>>(async () => true);
  const beforeLeave = useCallback(() => leaveGuardRef.current(), []);

  const handleThreadCleared = useCallback(() => {
    clearTree();
    setMessagesRef.current?.([]);
    setDocuments({});
  }, [clearTree]);

  const {
    threadId,
    threads,
    fetchThreads,
    startNewExperiment,
    switchThread,
    deleteThread,
    renameThread,
  } = useThreads({
    onThreadClear: handleThreadCleared,
    onThreadSwitch: fetchHistory,
    confirm: showConfirm,
    pushToast,
    beforeLeave,
  });

  // The node the next message continues: the chosen one, else the head.
  const anchorNode = useMemo(() => nodes.find((n) => n.id === (chosen ?? head)), [nodes, chosen, head]);
  // A clicked reply is continued with its model; the selection stays as set.
  const reply = useReplyTarget(threadId, selectedModels, anchorNode);

  // A turn has finished: the next one continues the latest turn again.
  const handleTurnSettled = useCallback(
    (tid: string) => {
      setChosen(null);
      fetchHistory(tid);
    },
    [setChosen, fetchHistory],
  );

  const clearDocuments = useCallback(() => setDocuments({}), []);
  const {
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
  } = useChatWebSocket({
    threadId,
    parentCheckpoint: chosen,
    selectedModels,
    respondingModels: reply.responders,
    toggles,
    summarizer,
    systemPrompt,
    documents,
    clearDocuments,
    onTurnSettled: handleTurnSettled,
    setErrorModals,
    pushToast,
    onThreadsChanged: fetchThreads,
  });

  useEffect(() => {
    setMessagesRef.current = setMessages;
  }, [setMessages]);

  // ─── Debate ─────────────────────────────────────────────────────
  const clearChatMessages = useCallback(() => setMessages([]), [setMessages]);
  const debate = useDebateSession({
    threadId,
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
  // A turn sent under a debate's transcript, before any turn has followed
  // it, continues that debate (a running one takes sends as injections).
  const { continuesDebate, markFollowedUp } = debate;
  // One banner for both views: its controls must be reachable from the tree too.
  const debateBanner: DebateBannerProps | null = inDebate
    ? {
        state: {
          round: debate.round,
          maxRounds: debate.maxRounds,
          status: debate.status,
          convergenceScore: debate.convergenceScore,
          legend: peerLegend(debate.tree.lanes),
        },
        onClose: debate.close,
        onSynthesize: debate.controls.synthesize
          ? () => debate.synthesize(debateDefaults.synthesizer_model, toggles, { summarizer, systemPrompt })
          : undefined,
        onPause: debate.controls.pause ? debate.pause : undefined,
        onResume: debate.controls.resume ? debate.resume : undefined,
        onContinue: debate.controls.continue ? () => debate.continueDebate() : undefined,
      }
    : null;

  const { confirmLeave: confirmLeaveDebate } = debate;
  useEffect(() => {
    leaveGuardRef.current = async () => {
      if (
        isLoading &&
        !(await showConfirm(
          "Leave while models answer?",
          "The models are still answering in this session. Leaving stops them where they are.",
          { confirmLabel: "Stop and leave" },
        ))
      )
        return false;
      return confirmLeaveDebate();
    };
  }, [isLoading, showConfirm, confirmLeaveDebate]);

  // ─── Tree node & composer actions ───────────────────────────────
  const handleFileUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file || !threadId) return;
    try {
      const data = await api.uploadDocument(file, threadId);
      setDocuments((prev) => ({ ...prev, [data.filename]: data.full_content }));
    } catch (error) {
      pushToast(errorMessage(error, "Couldn't upload the file"), "error", "Upload failed");
    }
  };

  const {
    shownNode,
    selectCheckpoint,
    viewCheckpoint,
    deleteNode,
    editAndRebranch,
    moveNode,
    applyLayout,
    branch,
    resetToLatest,
    branchFrom,
  } = useTreeActions({
    threadId,
    nodes,
    edges,
    setNodes,
    chosen,
    setChosen,
    head,
    shown,
    fetchHistory,
    fetchThreads,
    clearChatMessages,
    setInput,
    setShowTree,
    confirm: showConfirm,
    pushToast,
    continueFrom: reply.continueFrom,
  });

  // Deliberately does not call setShowTree. Sending used to yank you out of the
  // tree; the view now changes only when you change it.
  const send = useCallback(
    (text: string, deliberate: boolean) => {
      sendInteractiveMessage(text, deliberate, continuesDebate).then((sent) => {
        if (!sent) return;
        setInput("");
        if (continuesDebate) markFollowedUp();
      });
    },
    [sendInteractiveMessage, continuesDebate, markFollowedUp],
  );
  const handleSendMessage = useCallback((text: string) => send(text, false), [send]);
  const handleDeliberate = useCallback((text: string) => send(text, true), [send]);
  const { redirect: debateRedirect, switchTo: debateSwitchTo } = debate;
  const handleDebateRedirect = useCallback(
    (text: string) => {
      debateRedirect(text).then((redirected) => {
        if (redirected) setInput("");
      });
    },
    [debateRedirect],
  );

  const answerChoice = useMemo(
    () =>
      reply.replyModel && reply.canAskAll
        ? { replyModel: reply.replyModel, askAll: reply.askAll, selected: selectedModels, onChange: reply.setAskAll }
        : null,
    [reply.replyModel, reply.canAskAll, reply.askAll, reply.setAskAll, selectedModels],
  );
  const chatMessages = useMemo(
    () => (inDebate && debateHasTranscript ? [...debate.messages, ...afterDebateRecord(messages)] : messages),
    [inDebate, debateHasTranscript, debate.messages, messages],
  );
  const { setOpen: setSidebarOpen } = layout.sidebar;
  const { setOpen: setPanelOpen } = layout.panel;
  const closeSidebar = useCallback(() => setSidebarOpen(false), [setSidebarOpen]);
  const closePanel = useCallback(() => setPanelOpen(false), [setPanelOpen]);
  const { reset: resetReply } = reply;
  const switchDebate = useCallback(
    (id: string) => {
      resetReply();
      return debateSwitchTo(id);
    },
    [resetReply, debateSwitchTo],
  );

  return (
    <Box
      sx={{
        display: "flex",
        height: "100dvh",
        width: "100vw",
        overflow: "hidden",
        bgcolor: "background.default",
        transition: "background-color 0.7s",
        py: { xs: 0, md: 2 },
      }}
    >
      <Sidebar
        threads={threads}
        threadId={threadId}
        onStartNewExperiment={startNewExperiment}
        onSwitchThread={switchThread}
        onDeleteThread={deleteThread}
        onRenameThread={renameThread}
        onSwitchCheckpoint={selectCheckpoint}
        debateSessions={debate.sessions}
        activeDebateSessionId={debate.activeSessionId}
        activeDebateStatus={inDebate ? debate.status : null}
        modelLabel={modelLabel}
        onDeleteDebateSession={debate.remove}
        onSwitchDebateSession={switchDebate}
        mode={layout.sidebar.mode}
        open={layout.sidebar.open}
        onClose={closeSidebar}
        collapsed={layout.sidebar.collapsed}
        onCollapsedChange={layout.sidebar.setCollapsed}
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
          // Edge to edge on narrow screens, where the side panels are drawers.
          borderRadius: { xs: 0, md: "40px" },
          mx: { xs: 0, md: 2 },
          bgcolor: "background.paper",
          border: { xs: "none", md: "1px solid" },
          borderColor: "divider",
          backdropFilter: "blur(16px)",
          zIndex: 10,
        }}
      >
        <AppHeader
          connection={connection}
          selectedModels={reply.responders}
          showTree={showTree}
          onShowTreeChange={setShowTree}
          onHome={() => switchThread("")}
          modelLabel={modelLabel}
          onOpenSessions={layout.compact ? () => layout.sidebar.setOpen(true) : undefined}
          onOpenSettings={layout.compact ? () => layout.panel.setOpen(true) : undefined}
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
                  <div className="w-full h-full flex flex-col">
                    {debateBanner && <DebateBanner {...debateBanner} />}
                    <div className="flex-1 min-h-0 relative">
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
                    </div>
                  </div>
                ) : (
                  <TreeCanvas
                    key={threadId}
                    nodes={nodes}
                    edges={edges}
                    activeNodeId={shown || undefined}
                    onNodeClick={selectCheckpoint}
                    onNodeDragStop={moveNode}
                    onLayoutPositions={applyLayout}
                    onDeleteNode={deleteNode}
                    onBranchNode={branchFrom}
                    answering={isLoading}
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
                  messages={chatMessages}
                  nodes={nodes}
                  edges={edges}
                  isLoading={isLoading || isHistoryLoading}
                  input={input}
                  setInput={setInput}
                  onSendMessage={handleSendMessage}
                  onViewReply={viewCheckpoint}
                  onContinueReply={selectCheckpoint}
                  onSynthesize={synthesizeBranches}
                  synthesizerOptions={availableModelIds}
                  onDeliberate={handleDeliberate}
                  stopStreaming={stopStreaming}
                  setShowTree={setShowTree}
                  documents={documents}
                  setDocuments={setDocuments}
                  shownCheckpoint={shown}
                  onEditAndRebranch={editAndRebranch}
                  onFileUpload={handleFileUpload}
                  showEditButton={!inDebate && shownNode?.metadata?.role === "user"}
                  selectedModels={selectedModels}
                  respondingModels={reply.responders}
                  onDebateOpen={debate.openDialog}
                  onDebateInject={inDebate && debate.controls.inject ? debate.inject : undefined}
                  onDebateRedirect={inDebate && debate.controls.redirect ? handleDebateRedirect : undefined}
                  debateBanner={inDebate && debateHasTranscript ? debateBanner : null}
                  modelLabel={modelLabel}
                  modelErrors={inDebate ? [] : modelErrors}
                  onRetryModel={retryModel}
                  onDismissModelError={dismissModelError}
                  branchPoint={inDebate ? null : branch}
                  onResetBranch={resetToLatest}
                  answerChoice={answerChoice}
                  replyTexts={replyTexts}
                  liveTurn={liveTurn}
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
        activeCheckpointLabel={chosen === null ? "Latest turn" : anchorNode?.data?.label || "Start"}
        debateDefaults={debateDefaults}
        setDebateDefaults={setDebateDefaults}
        collapsed={layout.panel.collapsed}
        onCollapsedChange={layout.panel.setCollapsed}
        mode={layout.panel.mode}
        open={layout.panel.open}
        onClose={closePanel}
        summarizerChoice={summarizerChoice}
        summarizer={summarizer}
        defaultSummarizer={defaultSummarizer}
        onSummarizerChange={setSummarizerChoice}
        systemPrompt={systemPromptText}
        onSystemPromptChange={setSystemPromptText}
      />

      <DebateConfigDialog
        open={debate.dialogOpen}
        onClose={debate.closeDialog}
        onStart={(config) => {
          // Turns after the debate continue it with its participants, not a reply clicked before.
          reply.reset();
          // The composer empties once the debate has actually started:
          // cancelling or a refused start keeps what was typed.
          debate
            .start(config, {
              participants: selectedModels,
              toggles,
              documents,
              parentCheckpointId: chosen ?? head,
              summarizer,
              systemPrompt,
            })
            .then((started) => {
              if (started) setInput("");
            });
        }}
        defaults={debateDefaults}
        availableModels={allModelIds.length ? allModelIds : selectedModels}
        modelLabel={modelLabel}
        question={debate.dialogPrompt}
        participants={selectedModels}
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
