import React, { useRef, useEffect } from "react";
import { Box, Paper, Typography, ButtonBase, CircularProgress, useTheme } from "@mui/material";
import { Sparkles, Network } from "lucide-react";
import { motion } from "framer-motion";
import { ChatInput } from "./ChatInput";
import DebateBanner, { type DebateBannerProps } from "./DebateBanner";
import { MessageBubble } from "./MessageBubble";
import { Message, ModelError } from "@/lib/types";
import ModelErrorBubble from "./ModelErrorBubble";
import BranchChip, { type AnswerChoice } from "./BranchChip";
import type { BranchPoint } from "@/lib/branching";
import { buildTranscript, synthesizableIds, type LiveTurn } from "@/lib/turns";
import TurnCards from "./TurnCards";

interface ChatViewProps {
  messages: Message[];
  nodes: any[];
  edges: any[];
  isLoading: boolean;
  /** The composer's text; the page owns it, so Edit & fork can fill it. */
  input: string;
  setInput: (val: string) => void;
  onSendMessage: (text: string) => void;
  /** Show a reply's path without changing what the next message continues or who answers. */
  onViewReply: (id: string) => void;
  /** Continue from a reply: it becomes the branch point and its model answers. */
  onContinueReply: (id: string) => void;
  /** Merge the answers at these checkpoints; `model` writes it (null = first selected). */
  onSynthesize: (checkpointIds: string[], model?: string | null) => void;
  /** Models a synthesis can be written by (those with a key). */
  synthesizerOptions?: string[];
  onDeliberate: (text: string) => void;
  setShowTree: (val: boolean) => void;
  /** Files attached to the next message, by name. */
  documents: string[];
  onRemoveDocument: (name: string) => void;
  /** The file being uploaded right now, if any. */
  uploading?: string | null;
  onAttach: (file: File) => void;
  onEditAndRebranch: () => void;
  stopStreaming: () => void;
  showEditButton: boolean;
  selectedModels: string[];
  /** Who answers the next message; default: the selection. */
  respondingModels?: string[];
  onDebateOpen?: (prompt: string) => void;
  onDebateInject?: (message: string) => void;
  onDebateRedirect?: (message: string) => void;
  /** The debate on screen (status and its controls), or null. */
  debateBanner?: DebateBannerProps | null;
  /** Display name for a model ID; raw IDs only appear in tooltips. */
  modelLabel: (id: string) => string;
  /** Models that failed in the latest turn, shown inline with a Retry. */
  modelErrors?: ModelError[];
  onRetryModel?: (errorId: string) => void;
  onDismissModelError?: (errorId: string) => void;
  /** The checkpoint the next message branches from (chat only). */
  branchPoint?: BranchPoint | null;
  onResetBranch?: () => void;
  /** Who answers a clicked reply, switchable on the branch chip. */
  answerChoice?: AnswerChoice | null;
  /** The backend's message limit. */
  maxPromptChars?: number;
  /** What else goes with each message (system prompt, web search, document search). */
  contextNotes?: string[];
  /** Full text of replies streamed in this tab, by tree node id. */
  replyTexts?: Record<string, string>;
  /** The multi-model turn streaming (or just streamed) in this tab: it streams into cards. */
  liveTurn?: LiveTurn | null;
}


const EMPTY_TEXTS: Record<string, string> = {};

const ChatViewRaw: React.FC<ChatViewProps> = ({
  messages,
  nodes,
  edges,
  isLoading,
  input,
  setInput,
  onSendMessage,
  onViewReply,
  onContinueReply,
  onSynthesize,
  synthesizerOptions = [],
  onDeliberate,
  setShowTree,
  documents,
  onRemoveDocument,
  uploading = null,
  onAttach,
  onEditAndRebranch,
  showEditButton,
  selectedModels,
  respondingModels,
  stopStreaming,
  onDebateOpen,
  onDebateInject,
  onDebateRedirect,
  debateBanner,
  modelLabel,
  modelErrors = [],
  onRetryModel,
  onDismissModelError,
  branchPoint,
  onResetBranch,
  answerChoice = null,
  maxPromptChars,
  contextNotes,
  replyTexts = EMPTY_TEXTS,
  liveTurn = null,
}) => {
  const scrollRef = useRef<HTMLDivElement>(null);
  const innerContentRef = useRef<HTMLDivElement>(null);
  const messageRefs = useRef<(HTMLDivElement | null)[]>([]);
  const [markerPositions, setMarkerPositions] = React.useState<
    { top: number; isUser: boolean; id: number }[]
  >([]);
  const isScrolledToBottom = useRef(true);
  const isDark = useTheme().palette.mode === "dark";
  const lastUpdate = useRef(0);
  const lastInnerHeight = useRef(0);
  const resizeDebounceRef = useRef<NodeJS.Timeout | null>(null);
  const animationFrameRef = useRef<number | null>(null);
  const messageCount = messages.length;

  // Throttled function to calculate and update marker positions
  const updateMarkers = React.useCallback(
    (force = false) => {
      const now = Date.now();
      const threshold = isLoading ? 1500 : 200; // Increased threshold for background calculations

      if (!force && now - lastUpdate.current < threshold) return;
      lastUpdate.current = now;

      if (!scrollRef.current || !innerContentRef.current) return;

      const currentHeight = innerContentRef.current.scrollHeight;
      const clientHeight = scrollRef.current.clientHeight;

      // Skip if height change is negligible (unless forced)
      if (!force && Math.abs(currentHeight - lastInnerHeight.current) < 8)
        return;
      lastInnerHeight.current = currentHeight;

      const maxScrollTop = currentHeight - clientHeight;
      if (maxScrollTop <= 0) {
        setMarkerPositions([]);
        return;
      }

      const ratio = clientHeight / currentHeight;
      const thumbHeight = Math.max(clientHeight * ratio, 30);
      const travelRange = clientHeight - thumbHeight;

      const newPositions: { top: number; isUser: boolean; id: number }[] = [];
      for (let i = 0; i < messages.length; i++) {
        const el = messageRefs.current[i];
        if (!el) continue;

        const scrollTop = Math.min(el.offsetTop, maxScrollTop);
        const thumbTop = (scrollTop / maxScrollTop) * travelRange;
        const topPercent = (thumbTop / clientHeight) * 100;

        newPositions.push({
          top: topPercent,
          isUser: messages[i].role === "user" || messages[i].type === "human",
          id: i,
        });
      }

      if (animationFrameRef.current)
        cancelAnimationFrame(animationFrameRef.current);
      animationFrameRef.current = requestAnimationFrame(() => {
        setMarkerPositions(newPositions);
      });
    },
    [messages, isLoading],
  );

  // Use a ref for the update function to stabilize ResizeObserver lifecycle
  const updateMarkersRef = React.useRef(updateMarkers);
  React.useEffect(() => {
    updateMarkersRef.current = updateMarkers;
  }, [updateMarkers]);

  // Update markers on messages change
  React.useEffect(() => {
    // Only update on every message count change immediately
    // For content updates (streaming), the throttle inside updateMarkers handles it.
    updateMarkers();

    // Catch the final state after streaming ends or layout settles
    const timer = setTimeout(() => updateMarkers(true), 500);
    return () => clearTimeout(timer);
  }, [messageCount, updateMarkers]);

  // ResizeObserver for inner content height changes
  React.useEffect(() => {
    const target = innerContentRef.current;
    if (!target) return;

    const observer = new ResizeObserver(() => {
      if (resizeDebounceRef.current) clearTimeout(resizeDebounceRef.current);

      // Debounce the update to prevent pegging CPU during streaming
      resizeDebounceRef.current = setTimeout(() => {
        updateMarkersRef.current();
      }, 100);
    });

    observer.observe(target);
    return () => {
      observer.disconnect();
      if (resizeDebounceRef.current) clearTimeout(resizeDebounceRef.current);
      if (animationFrameRef.current)
        cancelAnimationFrame(animationFrameRef.current);
    };
  }, []); // Empty dependency array = stabilizer observer for component lifetime

  const scrollToMessage = (idx: number) => {
    const el = messageRefs.current[idx];
    if (el && scrollRef.current) {
      // Use offsetTop directly for 1:1 match with marker logic
      scrollRef.current.scrollTo({
        top: el.offsetTop,
        behavior: "smooth",
      });
    }
  };

  const registerMessageRef = React.useCallback(
    (el: HTMLDivElement | null, idx: number) => {
      messageRefs.current[idx] = el;
    },
    [],
  );

  const handleScroll = () => {
    if (scrollRef.current) {
      const { scrollTop, scrollHeight, clientHeight } = scrollRef.current;
      // Less than 50px from the bottom means we are effectively at the bottom
      isScrolledToBottom.current = scrollHeight - scrollTop - clientHeight < 50;
    }
  };

  useEffect(() => {
    if (scrollRef.current && isScrolledToBottom.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [messages, isLoading]);

  // The transcript as bubbles and turn grids: a turn sent to several models
  // streams into cards and stays as them (lib/turns).
  const items = React.useMemo(
    () => buildTranscript({ messages, nodes, edges, selected: selectedModels, replyTexts, live: liveTurn }),
    [messages, nodes, edges, selectedModels, replyTexts, liveTurn],
  );
  const lastTurnKey = React.useMemo(() => {
    const last = items[items.length - 1];
    return last?.kind === "turn" ? last.key : null;
  }, [items]);
  // Failures of the turn on cards show on their card; the rest as bubbles.
  const bubbleErrors = React.useMemo(() => {
    const last = items.find((it) => it.key === lastTurnKey);
    const onCards = new Set(last?.kind === "turn" ? last.cards.map((c) => c.model) : []);
    return modelErrors.filter((e) => !onCards.has(e.model));
  }, [items, lastTurnKey, modelErrors]);

  return (
    <Box
      sx={{
        flex: 1,
        display: "flex",
        flexDirection: "column",
        width: "100%",
        height: "100%",
        bgcolor: "transparent",
      }}
    >
      {debateBanner && <DebateBanner {...debateBanner} />}

      <Box
        sx={{
          flex: 1,
          display: "flex",
          flexDirection: "column",
          position: "relative",
          minHeight: 0,
        }}
      >
        {/* Scrollable message area */}
        <Box
          onScroll={handleScroll}
          ref={scrollRef}
          sx={{
            flex: 1,
            overflowY: "auto",
            minHeight: 0,
            "&::-webkit-scrollbar": {
              width: "8px",
            },
            "&::-webkit-scrollbar-track": {
              background: "transparent",
            },
            "&::-webkit-scrollbar-thumb": {
              background: isDark
                ? "rgba(255,255,255,0.08)"
                : "rgba(0,0,0,0.08)",
              borderRadius: "10px",
            },
            "&::-webkit-scrollbar-thumb:hover": {
              background: isDark
                ? "rgba(255,255,255,0.15)"
                : "rgba(0,0,0,0.15)",
            },
          }}
        >
          <Box
            ref={innerContentRef}
            sx={{
              maxWidth: 800,
              mx: "auto",
              display: "flex",
              flexDirection: "column",
              gap: { xs: 3, sm: 4 },
              px: { xs: 2, sm: 3 },
              pt: { xs: 3, sm: 5 },
              pb: 4, // Reduced from 6 to minimize bottom whitespace
              position: "relative", // Crucial for offsetTop accuracy
            }}
          >
            {/* Tactical Map button */}
            <Box sx={{ alignSelf: "center" }}>
              <ButtonBase
                onClick={() => setShowTree(true)}
                component={motion.button}
                whileHover={{ scale: 1.04 }}
                whileTap={{ scale: 0.96 }}
                sx={{
                  px: 3,
                  py: 1.5,
                  borderRadius: 8,
                  border: "1px solid",
                  fontSize: "0.75rem",
                  fontWeight: 800,
                  textTransform: "uppercase",
                  letterSpacing: "0.15em",
                  borderColor: "divider",
                  bgcolor: isDark
                    ? "rgba(255,255,255,0.03)"
                    : "background.paper",
                  color: "text.secondary",
                  transition: "all 0.2s",
                  "&:hover": {
                    bgcolor: isDark ? "rgba(255,255,255,0.06)" : "action.hover",
                    color: "text.primary",
                  },
                }}
              >
                <Network
                  width={14}
                  height={14}
                  style={{ marginRight: 8, display: "inline" }}
                />
                View conversation tree
              </ButtonBase>
            </Box>

            {/* Loading State (thread is active but messages haven't loaded yet) */}
            {messages.length === 0 && isLoading && (
              <Box
                component={motion.div}
                initial={{ opacity: 0 }}
                animate={{ opacity: 1 }}
                sx={{
                  display: "flex",
                  flexDirection: "column",
                  alignItems: "center",
                  justifyContent: "center",
                  py: 10,
                  gap: 2,
                }}
              >
                <CircularProgress
                  size={28}
                  thickness={4}
                  sx={{ color: isDark ? "primary.light" : "primary.main" }}
                />
                <Typography
                  variant="caption"
                  sx={{
                    fontWeight: 600,
                    color: "text.disabled",
                    letterSpacing: "0.1em",
                    textTransform: "uppercase",
                    fontSize: "0.6875rem",
                  }}
                >
                  Loading conversation…
                </Typography>
              </Box>
            )}

            {/* Empty State (no messages and NOT loading — fresh thread) */}
            {messages.length === 0 && !isLoading && (
              <Box
                component={motion.div}
                initial={{ opacity: 0, y: 20 }}
                animate={{ opacity: 1, y: 0 }}
                sx={{
                  display: "flex",
                  flexDirection: "column",
                  alignItems: "center",
                  justifyContent: "center",
                  py: 10,
                  gap: 3,
                }}
              >
                <Box
                  sx={{
                    width: 64,
                    height: 64,
                    borderRadius: 4,
                    display: "flex",
                    alignItems: "center",
                    justifyContent: "center",
                    bgcolor: isDark
                      ? "rgba(255,255,255,0.03)"
                      : "background.paper",
                    border: "1px solid",
                    borderColor: "divider",
                  }}
                >
                  <Sparkles
                    width={28}
                    height={28}
                    color={
                      isDark
                        ? "rgba(59, 130, 246, 0.4)"
                        : "rgba(59, 130, 246, 0.5)"
                    }
                  />
                </Box>
                <Box sx={{ textAlign: "center" }}>
                  <Typography
                    variant="subtitle2"
                    sx={{
                      fontWeight: 600,
                      mb: 0.5,
                      color: isDark ? "text.secondary" : "text.primary",
                    }}
                  >
                    Ask the arena anything
                  </Typography>
                  <Typography
                    variant="caption"
                    sx={{
                      maxWidth: 280,
                      display: "block",
                      color: "text.disabled",
                    }}
                  >
                    Every selected model answers on its own branch, so you
                    can compare them side by side
                  </Typography>
                </Box>
              </Box>
            )}

            {/* Messages, with each multi-model turn as its cards (lib/turns) */}
            {items.map((item) => {
              if (item.kind === "turn") {
                return (
                  <Box key={item.key} ref={(el: HTMLDivElement | null) => registerMessageRef(el, item.index)}>
                    <TurnCards
                      cards={item.cards}
                      isDark={isDark}
                      modelLabel={modelLabel}
                      onViewReply={onViewReply}
                      onContinueReply={onContinueReply}
                      synthesis={
                        item.key === lastTurnKey
                          ? {
                              ids: synthesizableIds(item.cards, nodes),
                              disabled: isLoading || synthesizableIds(item.cards, nodes).length < 2,
                              options: synthesizerOptions,
                              firstSelected: selectedModels[0] ?? null,
                              onSynthesize,
                            }
                          : null
                      }
                      errors={item.key === lastTurnKey ? modelErrors : []}
                      onRetry={onRetryModel}
                      onDismiss={onDismissModelError}
                      retryDisabled={isLoading}
                    />
                  </Box>
                );
              }
              const { msg, index: i } = item;
              const isUser = msg.role === "user" || msg.type === "human";

              // Debate round separator
              if (msg.type === "round_header") {
                return (
                  <Box
                    key={msg.id}
                    ref={(el) => registerMessageRef(el as HTMLDivElement | null, i)}
                    sx={{ display: "flex", alignItems: "center", gap: 1.5, my: 1 }}
                  >
                    <Box sx={{ flex: 1, height: "1px", bgcolor: "rgba(139,92,246,0.2)" }} />
                    <Typography
                      variant="overline"
                      sx={{ fontSize: "0.6875rem", fontWeight: 800, letterSpacing: "0.15em", color: "rgba(139,92,246,0.7)", flexShrink: 0 }}
                    >
                      {msg.content}
                    </Typography>
                    <Box sx={{ flex: 1, height: "1px", bgcolor: "rgba(139,92,246,0.2)" }} />
                  </Box>
                );
              }

              // Debate inject/redirect marker
              if (msg.type === "inject" || msg.type === "redirect") {
                return (
                  <Box
                    key={msg.id}
                    ref={(el) => registerMessageRef(el as HTMLDivElement | null, i)}
                    sx={{ display: "flex", alignItems: "center", gap: 1, my: 0.5, px: 1 }}
                  >
                    <Box
                      sx={{
                        px: 1.5, py: 0.5, borderRadius: 2,
                        bgcolor: msg.type === "redirect" ? "rgba(245,158,11,0.1)" : "rgba(139,92,246,0.1)",
                        border: "1px solid",
                        borderColor: msg.type === "redirect" ? "rgba(245,158,11,0.3)" : "rgba(139,92,246,0.3)",
                        fontSize: "0.75rem",
                        color: msg.type === "redirect" ? "#f59e0b" : "#a78bfa",
                        fontWeight: 600,
                      }}
                    >
                      {msg.type === "redirect" ? "↩ Redirect: " : "→ Inject: "}
                      <span style={{ color: "inherit", opacity: 0.8 }}>{msg.content}</span>
                    </Box>
                  </Box>
                );
              }

              // Synthesis replies (chat or debate): a loading pill until text
              // arrives, then a bubble that looks like a synthesis.
              if (msg.type === "synthesis" || msg.kind === "synthesis") {
                const hasSynthContent = msg.content && msg.content.trim().length > 0;
                if (!hasSynthContent) {
                  // Still loading
                  return (
                    <Box
                      component={motion.div}
                      key={msg.id || "synthesis-loading"}
                      initial={{ opacity: 0, scale: 0.95 }}
                      animate={{ opacity: 1, scale: 1 }}
                      sx={{
                        display: "flex",
                        justifyContent: "center",
                        width: "100%",
                        my: 2,
                      }}
                    >
                      <Paper
                        sx={{
                          px: 3,
                          py: 1.5,
                          borderRadius: 8,
                          bgcolor: isDark
                            ? "rgba(139, 92, 246, 0.1)"
                            : "rgba(139, 92, 246, 0.05)",
                          border: "1px solid",
                          borderColor: isDark
                            ? "rgba(139, 92, 246, 0.2)"
                            : "rgba(139, 92, 246, 0.15)",
                          display: "flex",
                          alignItems: "center",
                          gap: 2,
                        }}
                      >
                        <Sparkles width={16} height={16} color="#8b5cf6" />
                        <Typography
                          variant="body2"
                          sx={{
                            fontWeight: 600,
                            fontSize: "0.875rem",
                            color: "text.primary",
                            letterSpacing: "0.02em",
                          }}
                        >
                          Synthesizing…
                        </Typography>
                        <CircularProgress
                          size={12}
                          thickness={5}
                          sx={{ color: "#8b5cf6" }}
                        />
                      </Paper>
                    </Box>
                  );
                }
                return (
                  <MessageBubble
                    key={msg.id || `synthesis-${i}`}
                    msg={{ ...msg, role: "assistant" } as Message}
                    isUser={false}
                    isDark={isDark}
                    onMount={registerMessageRef}
                    index={i}
                    modelLabel={modelLabel}
                    variant="synthesis"
                  />
                );
              }

              const stableKey = msg.id || `msg-${i}-${msg.role}`;
              return (
                <MessageBubble
                  key={stableKey}
                  msg={msg}
                  isUser={isUser}
                  isDark={isDark}
                  onMount={registerMessageRef}
                  index={i}
                  modelLabel={modelLabel}
                />
              );
            })}

            {bubbleErrors.map((err) => (
              <ModelErrorBubble
                key={err.id}
                error={err}
                label={modelLabel(err.model)}
                onRetry={(id) => onRetryModel?.(id)}
                onDismiss={(id) => onDismissModelError?.(id)}
                retryDisabled={isLoading}
              />
            ))}

            {/* Loading indicator */}
            {isLoading && (
              <Box
                component={motion.div}
                initial={{ opacity: 0 }}
                animate={{ opacity: 1 }}
                sx={{ display: "flex", alignItems: "center", gap: 1.5, px: 1 }}
              >
                <CircularProgress size={12} thickness={5} />
                <Typography
                  variant="overline"
                  sx={{
                    fontSize: "0.6875rem",
                    fontWeight: 600,
                    letterSpacing: "0.1em",
                    color: "text.secondary",
                  }}
                >
                  Models answering…
                </Typography>
              </Box>
            )}
          </Box>
        </Box>

        {/* Scroll map: one marker per message, buttons so a keyboard can jump too. */}
        <Box
          component="nav"
          aria-label="Jump to a message"
          sx={{
            position: "absolute",
            right: 2,
            top: 0,
            bottom: 0, // Now relative to the shared viewport wrapper
            width: 12,
            zIndex: 100,
            pointerEvents: "none",
            display: messages.length > 5 ? "block" : "none",
          }}
        >
          {/* Alignment box to match innerContentRef bounds visually in the scroll area */}
          <Box
            sx={{
              position: "absolute",
              top: 0,
              bottom: 0,
              width: "100%",
              overflow: "hidden",
            }}
          >
            {markerPositions.map((marker) => (
              <Box
                component="button"
                key={marker.id}
                aria-label={`${marker.isUser ? "Your message" : "Reply"} ${marker.id + 1} of ${messages.length}`}
                onClick={(e: React.MouseEvent) => {
                  e.stopPropagation();
                  scrollToMessage(marker.id);
                }}
                sx={{
                  border: "none",
                  p: 0,
                  position: "absolute",
                  top: `${marker.top}%`,
                  left: 4,
                  width: 6,
                  height: 4,
                  borderRadius: "2px",
                  cursor: "pointer",
                  pointerEvents: "auto",
                  bgcolor: marker.isUser
                    ? "primary.main"
                    : isDark
                      ? "rgba(255,255,255,0.2)"
                      : "rgba(0,0,0,0.15)",
                  transition: "all 0.2s",
                  "&:hover, &:focus-visible": {
                    width: 10,
                    left: 0,
                    bgcolor: marker.isUser
                      ? "primary.light"
                      : isDark
                        ? "rgba(255,255,255,0.4)"
                        : "rgba(0,0,0,0.3)",
                  },
                }}
                title={marker.isUser ? "Your message" : "Reply"}
              />
            ))}
          </Box>
        </Box>
      </Box>

      {/* Input Bar */}
      <ChatInput
        isLoading={isLoading}
        value={input}
        onChange={setInput}
        onSendMessage={onSendMessage}
        onDeliberate={onDeliberate}
        stopStreaming={stopStreaming}
        onAttach={onAttach}
        documents={documents}
        onRemoveDocument={onRemoveDocument}
        uploading={uploading}
        selectedModels={selectedModels}
        respondingModels={respondingModels}
        messages={messages}
        onEditAndRebranch={onEditAndRebranch}
        showEditButton={showEditButton}
        isDark={isDark}
        onDebateOpen={onDebateOpen}
        onDebateInject={onDebateInject}
        onDebateRedirect={onDebateRedirect}
        header={
          branchPoint && !debateBanner ? (
            <BranchChip
              point={branchPoint}
              onReset={() => onResetBranch?.()}
              modelLabel={modelLabel}
              answer={answerChoice}
            />
          ) : undefined
        }
        debateOnScreen={!!debateBanner}
        maxChars={maxPromptChars}
        modelLabel={modelLabel}
        contextNotes={contextNotes}
      />
    </Box>
  );
};

ChatInput.displayName = "ChatInput";
MessageBubble.displayName = "MessageBubble";
ChatViewRaw.displayName = "ChatView";
const ChatView = React.memo(ChatViewRaw);
ChatView.displayName = "ChatView";

export default ChatView;
