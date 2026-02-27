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
import { Layers, Zap, Sun, Moon } from "lucide-react";
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

import { useThreads } from "@/hooks/useThreads";
import { useHistoryTree } from "@/hooks/useHistoryTree";
import { useChatWebSocket } from "@/hooks/useChatWebSocket";

export default function Home() {
  const [input, setInput] = useState("");
  const [isDark, setIsDark] = useState(true);
  const [editingThreadId, setEditingThreadId] = useState<string | null>(null);
  const [editingTitle, setEditingTitle] = useState("");
  const [selectedModels, setSelectedModels] = useState<string[]>(["gpt-5.2"]);
  const [documents, setDocuments] = useState<Record<string, string>>({});
  const [toggles, setToggles] = useState({ strict_logic: true });
  const [errorModals, setErrorModals] = useState<
    { id: string; title: string; details: string; suggestion?: string }[]
  >([]);
  const [toasts, setToasts] = useState<ToastData[]>([]);

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
    setMessagesRef.current?.(msgs);
  }, []);

  const {
    nodes,
    setNodes,
    edges,
    activeCheckpoint,
    setActiveCheckpoint,
    showTree,
    setShowTree,
    fetchHistory,
    clearTree,
  } = useHistoryTree(handleMessagesLoaded);

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

  // ─── View Effects ────────────────────────────────────────────────
  useEffect(() => {
    const savedDark = localStorage.getItem("crucible_is_dark");
    if (savedDark !== null) {
      // eslint-disable-next-line react-hooks/set-state-in-effect
      setIsDark(JSON.parse(savedDark));
    }
  }, []);

  useEffect(() => {
    localStorage.setItem("crucible_is_dark", JSON.stringify(isDark));
    document.documentElement.setAttribute(
      "data-theme",
      isDark ? "dark" : "light",
    );
    window.dispatchEvent(new Event("themeChange"));
  }, [isDark]);

  // ─── Component Handlers ──────────────────────────────────────────
  const handleFileUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    try {
      const data = await api.uploadFile(file);
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
      const clickedNode = nodes.find((n: any) => n.id === id);
      if (clickedNode?.metadata?.active_peer) {
        setSelectedModels([clickedNode.metadata.active_peer]);
      }
      if (threadId) fetchHistory(threadId, id);
    },
    [nodes, threadId, fetchHistory, setActiveCheckpoint, setSelectedModels],
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

  const handleSendMessage = useCallback(
    (text: string) => {
      sendInteractiveMessage(text, false);
      setInput("");
      setShowTree(false);
    },
    [sendInteractiveMessage, setInput, setShowTree],
  );

  const handleDeliberate = useCallback(
    (text: string) => {
      sendInteractiveMessage(text, true);
      setInput("");
      setShowTree(false);
    },
    [sendInteractiveMessage, setInput, setShowTree],
  );

  const handleSwitchCheckpoint = useCallback(
    (id: string) => {
      setActiveCheckpoint(id);
      const clickedNode = nodes.find((n: any) => n.id === id);
      if (clickedNode?.metadata?.active_peer) {
        setSelectedModels([clickedNode.metadata.active_peer]);
      }
      if (threadId) fetchHistory(threadId, id);
    },
    [nodes, threadId, fetchHistory, setActiveCheckpoint, setSelectedModels],
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
                    bgcolor: "success.main",
                    boxShadow: "0 0 8px rgba(16,185,129,0.5)",
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
                  Quantum Nexus Online
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
                      bgcolor: m.includes("gpt")
                        ? "#34d399"
                        : m.includes("claude")
                          ? "#fbbf24"
                          : m.includes("gemini")
                            ? "#a78bfa"
                            : "#60a5fa",
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
                  : `${selectedModels.length} CORE(s)`}
              </Typography>
            </Box>

            <ButtonBase
              component={motion.button}
              whileHover={{ scale: 1.05 }}
              whileTap={{ scale: 0.95 }}
              onClick={() => setShowTree(!showTree)}
              sx={{
                px: 2.5,
                py: 1,
                borderRadius: 2.5,
                border: "1px solid",
                borderColor: isDark ? "primary.dark" : "primary.light",
                bgcolor: isDark ? "rgba(37,99,235,0.1)" : "primary.50",
                color: isDark ? "primary.light" : "primary.main",
                fontWeight: 800,
                fontSize: "0.625rem",
                letterSpacing: "0.15em",
                textTransform: "uppercase",
                transition: "all 0.2s ease",
                display: "flex",
                alignItems: "center",
                gap: 1,
                "&:hover": {
                  bgcolor: isDark ? "rgba(37,99,235,0.2)" : "primary.100",
                },
              }}
            >
              <Layers width={14} height={14} />
              {showTree ? "Arena Mode" : "Tree View"}
            </ButtonBase>

            <IconButton
              component={motion.button}
              whileHover={{ scale: 1.1, rotate: 15 }}
              whileTap={{ scale: 0.9 }}
              onClick={() => setIsDark(!isDark)}
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
                <LandingView onStartNewExperiment={startNewExperiment} />
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
                <TreeCanvas
                  nodes={nodes}
                  edges={edges}
                  activeNodeId={activeCheckpoint || undefined}
                  onNodeClick={handleNodeClick}
                  onNodeDragStop={handleNodeDragStop}
                  onDeleteNode={deleteNode}
                />
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
                  messages={messages}
                  nodes={nodes}
                  edges={edges}
                  isLoading={isLoading}
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
                    activeCheckpointData?.metadata?.role === "user"
                  }
                  threadId={threadId}
                  selectedModels={selectedModels}
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
