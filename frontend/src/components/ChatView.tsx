import React, { useRef, useEffect } from "react";
import {
  Box,
  Paper,
  Typography,
  ButtonBase,
  Stack,
  Divider,
  CircularProgress,
  Select,
  MenuItem,
  useTheme,
} from "@mui/material";
import { CheckCircle2, Sparkles, Network, Scale, Swords, X as XIcon, Pause, Play } from "lucide-react";
import { motion, AnimatePresence } from "framer-motion";
import { ChatInput } from "./ChatInput";
import DebateBanner, { type DebateBannerProps } from "./DebateBanner";
import { MessageBubble, getModelColor } from "./MessageBubble";
import { Message, ModelError } from "@/lib/types";
import ModelErrorBubble from "./ModelErrorBubble";
import BranchChip, { type AnswerChoice } from "./BranchChip";
import type { BranchPoint } from "@/lib/branching";
import { cardExcerpt, isSynthesisNode, orderSiblings, turnSiblings } from "@/lib/arenaCompare";

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
  documents: Record<string, string>;
  setDocuments: React.Dispatch<React.SetStateAction<Record<string, string>>>;
  /** The checkpoint whose path the transcript shows. */
  shownCheckpoint: string | null;
  onEditAndRebranch: () => void;
  onFileUpload: (e: React.ChangeEvent<HTMLInputElement>) => void;
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
  /** Full text of replies streamed in this tab, by tree node id. */
  replyTexts?: Record<string, string>;
  /** The replies of the turn that just streamed: their cards open in full. */
  liveTurn?: string[];
}


const EMPTY_TEXTS: Record<string, string> = {};

const cardActionSx = (color: string) => ({
  px: 1,
  py: 0.5,
  borderRadius: 1.5,
  fontSize: "0.7rem",
  fontWeight: 800,
  textTransform: "uppercase" as const,
  letterSpacing: "0.08em",
  color,
  "&:hover": { bgcolor: "action.hover" },
});
const EMPTY_TURN: string[] = [];

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
  setDocuments,
  shownCheckpoint,
  onEditAndRebranch,
  onFileUpload,
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
  replyTexts = EMPTY_TEXTS,
  liveTurn = EMPTY_TURN,
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

  // "" = the first selected model, the original behaviour.
  const [synthesizer, setSynthesizer] = React.useState("");

  // The other models' replies to the same message: by turn, on whichever
  // branch each model continued (lib/arenaCompare).
  const siblings = React.useMemo(
    () => orderSiblings(turnSiblings(nodes, edges, shownCheckpoint), selectedModels),
    [nodes, edges, shownCheckpoint, selectedModels],
  );
  // Cards whose open/closed state the person flipped. The turn that just
  // streamed starts open, so its replies stay readable once it settles
  // into cards, as they were while streaming.
  const [toggledCards, setToggledCards] = React.useState<Set<string>>(new Set());
  const isCardOpen = (id: string) => toggledCards.has(id) !== liveTurn.includes(id);
  const toggleCard = React.useCallback((id: string) => {
    setToggledCards((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }, []);

  // Compare only genuine answers, and not while a synthesis is on screen.
  const isArenaActive = React.useMemo(
    () => siblings.length > 1 && !isSynthesisNode(nodes.find((n) => n.id === shownCheckpoint)),
    [siblings, nodes, shownCheckpoint],
  );

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

            {/* Messages */}
            {messages.map((msg, i) => {
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

            {modelErrors.map((err) => (
              <ModelErrorBubble
                key={err.id}
                error={err}
                label={modelLabel(err.model)}
                onRetry={(id) => onRetryModel?.(id)}
                onDismiss={(id) => onDismissModelError?.(id)}
                retryDisabled={isLoading}
              />
            ))}

            {/* Compare footer: sibling answers to the same prompt */}
            {isArenaActive && (
              <Box
                component={motion.div}
                key="arena"
                initial={{ opacity: 0, y: 20 }}
                animate={{ opacity: 1, y: 0 }}
                sx={{
                  display: "flex",
                  flexDirection: "column",
                  gap: 3,
                  width: "100%",
                  mt: 6,
                  mb: 4,
                }}
              >
                {/* Arena Header */}
                <Box sx={{ display: "flex", alignItems: "center", gap: 2 }}>
                  <Divider sx={{ flex: 1 }} />
                  <Stack alignItems="center" spacing={1}>
                    <Box
                      sx={{
                        display: "flex",
                        alignItems: "center",
                        gap: 1.5,
                        px: 2,
                        py: 0.5,
                        borderRadius: "20px",
                        bgcolor: isDark
                          ? "rgba(255,255,255,0.03)"
                          : "rgba(0,0,0,0.02)",
                        border: "1px solid",
                        borderColor: "divider",
                      }}
                    >
                      <Scale width={12} height={12} color="#a78bfa" />
                      <Typography
                        variant="overline"
                        sx={{
                          fontSize: "0.6875rem",
                          fontWeight: 800,
                          letterSpacing: "0.2em",
                          color: "text.secondary",
                        }}
                      >
                        Compare answers
                      </Typography>
                    </Box>
                    <ButtonBase
                      component={motion.button}
                      whileHover={{ scale: 1.03 }}
                      whileTap={{ scale: 0.97 }}
                      onClick={() =>
                        onSynthesize(
                          siblings.map((s) => s.id),
                          synthesizer || null,
                        )
                      }
                      sx={{
                        px: 2.5,
                        py: 0.8,
                        borderRadius: 8,
                        border: "1px solid rgba(139, 92, 246, 0.3)",
                        bgcolor: "rgba(139, 92, 246, 0.1)",
                        color: "#a78bfa",
                        fontSize: "0.6875rem",
                        fontWeight: 800,
                        textTransform: "uppercase",
                        letterSpacing: "0.1em",
                        transition: "all 0.2s",
                        "&:hover": {
                          bgcolor: "rgba(139, 92, 246, 0.2)",
                          boxShadow: "0 0 15px rgba(139, 92, 246, 0.2)",
                        },
                      }}
                    >
                      <Sparkles
                        width={12}
                        height={12}
                        style={{
                          display: "inline",
                          marginRight: 6,
                          marginTop: -2,
                        }}
                      />
                      Synthesize answers
                    </ButtonBase>
                    <Box sx={{ display: "flex", alignItems: "center", gap: 1 }}>
                      <Typography component="label" htmlFor="synthesizer-select" sx={{ fontSize: "0.75rem", color: "text.secondary" }}>
                        written by
                      </Typography>
                      <Select
                        size="small"
                        variant="standard"
                        disableUnderline
                        value={synthesizer}
                        displayEmpty
                        onChange={(e) => setSynthesizer(String(e.target.value))}
                        inputProps={{ id: "synthesizer-select", "aria-label": "Synthesis written by" }}
                        sx={{ fontSize: "0.75rem", fontWeight: 600, color: "#a78bfa" }}
                      >
                        <MenuItem value="" sx={{ fontSize: "0.8rem" }}>
                          {selectedModels[0] ? `${modelLabel(selectedModels[0])} (first selected)` : "First selected model"}
                        </MenuItem>
                        {synthesizerOptions.map((m) => (
                          <MenuItem key={m} value={m} title={m} sx={{ fontSize: "0.8rem" }}>
                            {modelLabel(m)}
                          </MenuItem>
                        ))}
                      </Select>
                    </Box>
                  </Stack>
                  <Divider sx={{ flex: 1 }} />
                </Box>

                {/* Arena Cards */}
                <Box
                  sx={{
                    display: "grid",
                    gap: 2,
                    gridTemplateColumns: {
                      xs: "1fr",
                      sm:
                        siblings.length === 2
                          ? "repeat(2, 1fr)"
                          : "repeat(3, 1fr)",
                      md:
                        siblings.length === 2
                          ? "repeat(2, 1fr)"
                          : "repeat(3, 1fr)",
                    },
                  }}
                >
                  {siblings.map((sib) => {
                    const isActive = sib.id === shownCheckpoint;
                    const sibModel = sib.metadata?.active_peer || "assistant";
                    const sibColor = getModelColor(sibModel);
                    const sibLabel = sib.metadata?.model_name || modelLabel(sibModel);
                    const open = isCardOpen(sib.id);
                    const fullText = replyTexts[sib.id];

                    return (
                      <Paper
                        key={sib.id}
                        component="article"
                        aria-label={`${sibLabel}'s answer`}
                        sx={{
                          borderRadius: 4,
                          overflow: "hidden",
                          transition: "border-color 0.2s",
                          p: 2.5,
                          display: "flex",
                          flexDirection: "column",
                          border: "1px solid",
                          borderColor: isActive
                            ? sibColor.main
                            : isDark
                              ? "rgba(255,255,255,0.06)"
                              : "divider",
                          bgcolor: isActive
                            ? isDark
                              ? "rgba(139, 92, 246, 0.05)"
                              : "rgba(139, 92, 246, 0.03)"
                            : isDark
                              ? "rgba(255,255,255,0.02)"
                              : "background.paper",
                          boxShadow: isActive ? `0 10px 30px -10px ${sibColor.border}` : "none",
                        }}
                      >
                        <Box sx={{ display: "flex", alignItems: "center", gap: 1.5, mb: 2 }}>
                          <Box
                            sx={{
                              width: 8,
                              height: 8,
                              borderRadius: "50%",
                              bgcolor: sibColor.dot,
                              boxShadow: `0 0 8px ${sibColor.dot}`,
                            }}
                          />
                          <Typography
                            variant="overline"
                            title={sibModel}
                            sx={{ fontSize: "0.75rem", fontWeight: 800, letterSpacing: "0.1em", color: sibColor.text, flex: 1 }}
                          >
                            {sibLabel}
                          </Typography>
                          {isActive && (
                            <Box
                              title="This answer is shown in full above"
                              sx={{ display: "flex", alignItems: "center", gap: 0.5, fontSize: "0.6875rem", fontWeight: 700, color: sibColor.text }}
                            >
                              <CheckCircle2 width={12} height={12} />
                              Shown above
                            </Box>
                          )}
                        </Box>
                        <Typography
                          variant="body2"
                          sx={{
                            lineHeight: 1.6,
                            color: "text.primary",
                            whiteSpace: open && fullText ? "pre-wrap" : undefined,
                            ...(open
                              ? {}
                              : {
                                  display: "-webkit-box",
                                  WebkitLineClamp: 5,
                                  WebkitBoxOrient: "vertical",
                                  overflow: "hidden",
                                }),
                            fontSize: "0.8125rem",
                            mb: 1,
                          }}
                        >
                          {open && fullText ? fullText : cardExcerpt(sib)}
                        </Typography>
                        <ButtonBase
                          onClick={() => toggleCard(sib.id)}
                          aria-expanded={open}
                          sx={{ alignSelf: "flex-start", mb: 1.5, fontSize: "0.75rem", fontWeight: 700, color: sibColor.text }}
                        >
                          {open ? "Show less" : "Show more"}
                        </ButtonBase>
                        <Box
                          sx={{
                            mt: "auto",
                            pt: 1.5,
                            borderTop: "1px solid",
                            borderColor: "divider",
                            display: "flex",
                            gap: 1,
                            justifyContent: "space-between",
                          }}
                        >
                          {!isActive && (
                            <ButtonBase
                              onClick={() => onViewReply(sib.id)}
                              title="Show this answer's conversation above; who answers next doesn't change"
                              sx={cardActionSx(sibColor.text)}
                            >
                              Read in full
                            </ButtonBase>
                          )}
                          <ButtonBase
                            onClick={() => onContinueReply(sib.id)}
                            title={`Continue from this answer: your next message goes to ${sibLabel}`}
                            aria-label={`Continue with ${sibLabel}`}
                            sx={{ ...cardActionSx("text.secondary"), ml: "auto" }}
                          >
                            Continue from this
                          </ButtonBase>
                        </Box>
                      </Paper>
                    );
                  })}
                </Box>
              </Box>
            )}

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

        {/* Scroll Navigation Markers (ScrollMap) */}
        <Box
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
                key={marker.id}
                onClick={(e) => {
                  e.stopPropagation();
                  scrollToMessage(marker.id);
                }}
                sx={{
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
                  "&:hover": {
                    width: 10,
                    left: 0,
                    bgcolor: marker.isUser
                      ? "primary.light"
                      : isDark
                        ? "rgba(255,255,255,0.4)"
                        : "rgba(0,0,0,0.3)",
                  },
                }}
                title={marker.isUser ? "User Prompt" : "AI Response"}
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
        onFileUpload={onFileUpload}
        documents={documents}
        setDocuments={setDocuments}
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
