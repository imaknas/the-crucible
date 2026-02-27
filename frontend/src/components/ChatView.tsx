import React, { useRef, useEffect } from "react";
import {
  Box,
  Paper,
  Typography,
  ButtonBase,
  TextField,
  IconButton,
  Stack,
  Divider,
  CircularProgress,
  useTheme,
  Tooltip,
  Chip,
} from "@mui/material";
import {
  Send,
  FileText,
  Edit3,
  CheckCircle2,
  Sparkles,
  Network,
  Scale,
  X,
  StopCircle,
} from "lucide-react";
import { motion, AnimatePresence } from "framer-motion";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import remarkMath from "remark-math";
import rehypeKatex from "rehype-katex";
import "katex/dist/katex.min.css";
import { Prism as SyntaxHighlighter } from "react-syntax-highlighter";
import {
  vscDarkPlus,
  vs,
} from "react-syntax-highlighter/dist/esm/styles/prism";

interface Message {
  role: string;
  content: string;
  type?: string;
  model?: string;
  streaming?: boolean;
}

interface ChatViewProps {
  messages: Message[];
  nodes: any[];
  edges: any[];
  isLoading: boolean;
  input: string;
  setInput: (val: string) => void;
  onSendMessage: (text: string) => void;
  onSwitchCheckpoint: (id: string) => void;
  onSynthesize: (contents: string[], parentId: string | null) => void;
  onDeliberate: (text: string) => void;
  setShowTree: (val: boolean) => void;
  documents: Record<string, string>;
  setDocuments: React.Dispatch<React.SetStateAction<Record<string, string>>>;
  activeCheckpoint: string | null;
  onDeleteNode: () => void;
  onEditAndRebranch: () => void;
  onFileUpload: (e: React.ChangeEvent<HTMLInputElement>) => void;
  stopStreaming: () => void;
  showEditButton: boolean;
  threadId: string | null;
  selectedModels: string[];
}

function getModelColor(model?: string): {
  text: string;
  bg: string;
  border: string;
  dot: string;
  main: string;
} {
  if (!model)
    return {
      text: "text.secondary",
      bg: "rgba(148, 163, 184, 0.1)",
      border: "rgba(148, 163, 184, 0.2)",
      dot: "#94a3b8",
      main: "#94a3b8",
    };
  const m = model.toLowerCase();
  if (m.includes("gpt"))
    return {
      text: "#34d399",
      bg: "rgba(16, 185, 129, 0.1)",
      border: "rgba(16, 185, 129, 0.25)",
      dot: "#34d399",
      main: "#10b981",
    };
  if (m.includes("claude"))
    return {
      text: "#fbbf24",
      bg: "rgba(245, 158, 11, 0.1)",
      border: "rgba(245, 158, 11, 0.25)",
      dot: "#fbbf24",
      main: "#f59e0b",
    };
  if (m.includes("gemini"))
    return {
      text: "#a78bfa",
      bg: "rgba(139, 92, 246, 0.1)",
      border: "rgba(139, 92, 246, 0.25)",
      dot: "#a78bfa",
      main: "#8b5cf6",
    };
  return {
    text: "#60a5fa",
    bg: "rgba(59, 130, 246, 0.1)",
    border: "rgba(59, 130, 246, 0.25)",
    dot: "#60a5fa",
    main: "#3b82f6",
  };
}

function getModelLabel(model?: string): string {
  if (!model) return "Crucible Core";
  // Capitalize each segment: "gpt-5.2" → "GPT 5.2", "claude-sonnet-4-6" → "Claude Sonnet 4 6"
  return model
    .split("-")
    .map((s, i) => {
      if (i === 0) return s.toUpperCase();
      return s.charAt(0).toUpperCase() + s.slice(1);
    })
    .join(" ");
}

// ─── Sub-components ──────────────────────────────────────────────

interface ChatInputProps {
  isLoading: boolean;
  onSendMessage: (val: string) => void;
  onDeliberate: (val: string) => void;
  stopStreaming: () => void;
  onFileUpload: (e: React.ChangeEvent<HTMLInputElement>) => void;
  documents: Record<string, any>;
  setDocuments: (docs: Record<string, any>) => void;
  selectedModels: string[];
  messages: any[];
  onEditAndRebranch: () => void;
  showEditButton: boolean;
  isDark: boolean;
  initialInput?: string;
}

const ChatInput = React.memo(
  ({
    isLoading,
    onSendMessage,
    onDeliberate,
    stopStreaming,
    onFileUpload,
    documents,
    setDocuments,
    selectedModels,
    messages,
    onEditAndRebranch,
    showEditButton,
    isDark,
    initialInput = "",
  }: ChatInputProps) => {
    const [localInput, setLocalInput] = React.useState(initialInput);

    React.useEffect(() => {
      setLocalInput(initialInput);
    }, [initialInput]);

    const handleSend = () => {
      if (!localInput.trim() || isLoading) return;
      onSendMessage(localInput);
      setLocalInput("");
    };

    const handleDeliberateClick = () => {
      if (!localInput.trim() || isLoading) return;
      onDeliberate(localInput);
      setLocalInput("");
    };

    return (
      <Box
        sx={{
          flexShrink: 0,
          borderTop: "1px solid",
          borderColor: "divider",
          px: 3,
          py: 2,
          bgcolor: isDark
            ? "rgba(10, 15, 30, 0.8)"
            : "rgba(255, 255, 255, 0.8)",
          backdropFilter: "blur(16px)",
        }}
      >
        <Box sx={{ maxWidth: 800, mx: "auto" }}>
          <Paper
            sx={{
              borderRadius: 1.5,
              overflow: "hidden",
              transition: "all 0.3s",
              border: "1px solid",
              borderColor: "divider",
              bgcolor: isDark ? "rgba(255,255,255,0.03)" : "background.paper",
              "&:focus-within": {
                borderColor: "primary.main",
                boxShadow: "0 0 0 1px rgba(59, 130, 246, 0.5)",
              },
            }}
          >
            <Box sx={{ position: "relative" }}>
              {/* Uploaded Documents Indicator */}
              {Object.keys(documents).length > 0 && (
                <Box
                  sx={{
                    display: "flex",
                    gap: 1,
                    flexWrap: "wrap",
                    pt: 1.5,
                    px: 1.5,
                  }}
                >
                  {Object.keys(documents).map((docName) => (
                    <Chip
                      key={docName}
                      label={docName}
                      size="small"
                      onDelete={() => {
                        const newDocs = { ...documents };
                        delete newDocs[docName];
                        setDocuments(newDocs);
                      }}
                      deleteIcon={<X width={12} height={12} />}
                      sx={{
                        bgcolor: isDark
                          ? "rgba(255,255,255,0.06)"
                          : "abstract.paper",
                        border: "1px solid",
                        borderColor: "divider",
                        borderRadius: 1.5,
                        fontSize: "0.7rem",
                        fontWeight: 600,
                        color: "text.secondary",
                      }}
                      icon={
                        <FileText
                          width={12}
                          height={12}
                          style={{ marginLeft: 8, color: "inherit" }}
                        />
                      }
                    />
                  ))}
                </Box>
              )}
              <TextField
                fullWidth
                multiline
                maxRows={6}
                value={localInput}
                onChange={(e) => setLocalInput(e.target.value)}
                onKeyDown={(e) => {
                  if (
                    e.key === "Enter" &&
                    !e.shiftKey &&
                    !e.nativeEvent.isComposing
                  ) {
                    e.preventDefault();
                    handleSend();
                  }
                }}
                placeholder="Ask the Council…"
                variant="standard"
                InputProps={{
                  disableUnderline: true,
                  sx: {
                    pl: 2.5,
                    pr: 18,
                    pt: 2,
                    pb: 2,
                    fontSize: "1rem",
                    fontWeight: 500,
                    color: "text.primary",
                  },
                }}
              />
              <Box
                sx={{
                  position: "absolute",
                  right: 12,
                  bottom: 10,
                  display: "flex",
                  alignItems: "center",
                  gap: 1,
                }}
              >
                <label style={{ cursor: "pointer", display: "flex" }}>
                  <input
                    type="file"
                    style={{ display: "none" }}
                    onChange={onFileUpload}
                    accept=".pdf,.txt"
                  />
                  <IconButton
                    component="span"
                    size="small"
                    sx={{
                      color: "text.secondary",
                      "&:hover": {
                        bgcolor: isDark
                          ? "rgba(255,255,255,0.06)"
                          : "action.hover",
                      },
                    }}
                  >
                    <FileText width={16} height={16} />
                  </IconButton>
                </label>
                <Tooltip
                  title={
                    selectedModels.length === 0
                      ? "Select a model to deliberate"
                      : selectedModels.length > 1
                        ? "Deliberation requires exactly 1 model"
                        : messages.length === 0
                          ? "Need conversation history to deliberate"
                          : "Invite selected model to deliberate on the history"
                  }
                  placement="top"
                  arrow
                >
                  <span>
                    <ButtonBase
                      component={motion.button}
                      whileHover={
                        !(
                          isLoading ||
                          selectedModels.length !== 1 ||
                          messages.length === 0
                        )
                          ? { scale: 1.05 }
                          : {}
                      }
                      whileTap={
                        !(
                          isLoading ||
                          selectedModels.length !== 1 ||
                          messages.length === 0
                        )
                          ? { scale: 0.93 }
                          : {}
                      }
                      onClick={handleDeliberateClick}
                      disabled={
                        isLoading ||
                        selectedModels.length !== 1 ||
                        messages.length === 0
                      }
                      sx={{
                        p: 1.25,
                        borderRadius: 3,
                        transition: "all 0.2s",
                        mx: 0.5,
                        bgcolor:
                          isLoading ||
                          selectedModels.length !== 1 ||
                          messages.length === 0
                            ? isDark
                              ? "rgba(255,255,255,0.04)"
                              : "action.disabledBackground"
                            : "secondary.main",
                        color:
                          isLoading ||
                          selectedModels.length !== 1 ||
                          messages.length === 0
                            ? "text.disabled"
                            : "secondary.contrastText",
                        boxShadow:
                          isLoading ||
                          selectedModels.length !== 1 ||
                          messages.length === 0
                            ? "none"
                            : "0 4px 14px 0 rgba(156, 39, 176, 0.39)",
                        "&:hover": {
                          bgcolor:
                            isLoading ||
                            selectedModels.length !== 1 ||
                            messages.length === 0
                              ? ""
                              : "secondary.dark",
                        },
                      }}
                    >
                      <Scale width={16} height={16} />
                    </ButtonBase>
                  </span>
                </Tooltip>
                {isLoading ? (
                  <ButtonBase
                    component={motion.button}
                    whileHover={{ scale: 1.1 }}
                    whileTap={{ scale: 0.9 }}
                    onClick={stopStreaming}
                    sx={{
                      p: 1.25,
                      borderRadius: "50%",
                      bgcolor: isDark
                        ? "rgba(239, 68, 68, 0.2)"
                        : "rgba(239, 68, 68, 0.1)",
                      color: "error.main",
                      border: "1px solid",
                      borderColor: "error.main",
                      transition: "all 0.2s",
                      "&:hover": {
                        bgcolor: "error.main",
                        color: "white",
                        boxShadow: "0 0 12px rgba(239, 68, 68, 0.4)",
                      },
                    }}
                  >
                    <StopCircle width={18} height={18} />
                  </ButtonBase>
                ) : (
                  <ButtonBase
                    onClick={handleSend}
                    disabled={!localInput.trim()}
                    component={motion.button}
                    whileHover={localInput.trim() ? { scale: 1.05 } : {}}
                    whileTap={localInput.trim() ? { scale: 0.95 } : {}}
                    sx={{
                      p: 1.25,
                      borderRadius: "50%",
                      bgcolor: localInput.trim()
                        ? "primary.main"
                        : "transparent",
                      color: localInput.trim() ? "white" : "text.disabled",
                      border: "1px solid",
                      borderColor: localInput.trim()
                        ? "primary.main"
                        : "divider",
                      transition: "all 0.2s cubic-bezier(0.4, 0, 0.2, 1)",
                      "&:hover": {
                        bgcolor: localInput.trim()
                          ? "primary.dark"
                          : "transparent",
                        boxShadow: localInput.trim()
                          ? "0 4px 12px rgba(37,99,235,0.3)"
                          : "none",
                      },
                      "&:disabled": { cursor: "not-allowed" },
                    }}
                  >
                    <Send width={18} height={18} />
                  </ButtonBase>
                )}
              </Box>
            </Box>

            {/* Status bar */}
            <Box
              sx={{
                px: 2.5,
                py: 1,
                borderTop: "1px solid",
                borderColor: "divider",
                display: "flex",
                alignItems: "center",
                justifyContent: "space-between",
              }}
            >
              <Box sx={{ display: "flex", alignItems: "center", gap: 1 }}>
                <Box
                  sx={{
                    width: 6,
                    height: 6,
                    borderRadius: "50%",
                    bgcolor: isLoading ? "primary.main" : "success.main",
                    animation: isLoading ? "pulse 2s infinite" : "none",
                    boxShadow: isLoading
                      ? "none"
                      : "0 0 6px rgba(16,185,129,0.4)",
                    "@keyframes pulse": {
                      "0%, 100%": { opacity: 1 },
                      "50%": { opacity: 0.5 },
                    },
                  }}
                />
                <Typography
                  variant="overline"
                  sx={{
                    fontSize: "0.7rem",
                    fontWeight: 700,
                    letterSpacing: "0.1em",
                    color: "text.secondary",
                  }}
                >
                  {isLoading ? "Processing…" : "Ready"}
                </Typography>
              </Box>
              {showEditButton && (
                <ButtonBase
                  onClick={onEditAndRebranch}
                  sx={{
                    display: "flex",
                    alignItems: "center",
                    gap: 0.5,
                    px: 1,
                    py: 0.5,
                    borderRadius: 1.5,
                    fontSize: "0.7rem",
                    fontWeight: 800,
                    textTransform: "uppercase",
                    letterSpacing: "0.1em",
                    color: isDark ? "warning.light" : "warning.dark",
                    transition: "all 0.2s",
                    "&:hover": {
                      bgcolor: isDark
                        ? "rgba(245, 158, 11, 0.1)"
                        : "warning.50",
                    },
                  }}
                >
                  <Edit3 width={12} height={12} />
                  Fork
                </ButtonBase>
              )}
            </Box>
          </Paper>
        </Box>
      </Box>
    );
  },
);

const MessageBubble = React.memo(
  ({
    msg,
    isUser,
    isDark,
    onMount,
    index,
  }: {
    msg: Message;
    isUser: boolean;
    isDark: boolean;
    onMount: (node: HTMLDivElement | null, idx: number) => void;
    index: number;
  }) => {
    const modelColor = getModelColor(isUser ? undefined : msg.model);
    const modelLabel = getModelLabel(msg.model);

    return (
      <Box
        ref={(el: HTMLDivElement | null) => onMount(el, index)}
        component={motion.div}
        initial={{ opacity: 0, y: 10 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ type: "spring", damping: 28, stiffness: 220 }}
        sx={{
          display: "flex",
          width: "100%",
          justifyContent: isUser ? "flex-end" : "flex-start",
        }}
      >
        <Paper
          sx={{
            maxWidth: isUser ? "85%" : "100%",
            borderRadius: 2.5,
            transition: "all 0.3s",
            p: 2.5,
            border: "1px solid",
            bgcolor: isUser
              ? isDark
                ? "rgba(37, 99, 235, 0.15)"
                : "primary.50"
              : isDark
                ? "rgba(255,255,255,0.03)"
                : "background.paper",
            borderColor: isUser
              ? isDark
                ? "rgba(59, 130, 246, 0.2)"
                : "primary.200"
              : isDark
                ? "rgba(255,255,255,0.05)"
                : "divider",
            boxShadow: isUser ? "none" : "0 1px 2px 0 rgba(0,0,0,0.05)",
          }}
        >
          <Box
            sx={{
              display: "flex",
              alignItems: "center",
              gap: 1,
              mb: 1,
              color: isUser ? "primary.main" : modelColor.text,
            }}
          >
            {!isUser && (
              <Box
                sx={{
                  width: 6,
                  height: 6,
                  borderRadius: "50%",
                  bgcolor: modelColor.dot,
                }}
              />
            )}
            <Typography
              variant="overline"
              sx={{
                fontSize: "0.7rem",
                fontWeight: 800,
                letterSpacing: "0.15em",
                lineHeight: 1,
              }}
            >
              {isUser ? "You" : modelLabel}
            </Typography>
          </Box>
          <Box
            sx={{
              fontSize: "1rem",
              lineHeight: 1.75,
              color: "text.primary",
              "& p": { mb: 1.5, mt: 0, "&:last-of-type": { mb: 0 } },
              "& pre": {
                p: 1.5,
                my: 1.5,
                borderRadius: 2,
                bgcolor: isDark ? "rgba(0,0,0,0.3)" : "rgba(0,0,0,0.05)",
                overflowX: "auto",
              },
              "& code": {
                fontFamily: "monospace",
                fontSize: "0.9em",
                bgcolor: isDark ? "rgba(0,0,0,0.3)" : "rgba(0,0,0,0.05)",
                px: 0.5,
                py: 0.25,
                borderRadius: 1,
              },
              "& pre code": { bgcolor: "transparent", p: 0 },
              "& ul, & ol": { pl: 3, mb: 1.5, mt: 0 },
              "& li": { mb: 0.5 },
              "& h1, & h2, & h3, & h4, & h5, & h6": {
                fontWeight: 700,
                mt: 2,
                mb: 1,
              },
              "& blockquote": {
                borderLeft: "4px solid",
                borderColor: "divider",
                pl: 2,
                py: 0.5,
                ml: 0,
                my: 1.5,
                color: "text.secondary",
                fontStyle: "italic",
              },
              "& table": {
                width: "100%",
                mb: 1.5,
                borderCollapse: "collapse",
              },
              "& th, & td": {
                border: "1px solid",
                borderColor: "divider",
                p: 1,
              },
              "& th": {
                bgcolor: isDark ? "rgba(255,255,255,0.05)" : "rgba(0,0,0,0.02)",
              },
              "& a": {
                color: "primary.main",
                textDecoration: "none",
                "&:hover": { textDecoration: "underline" },
              },
            }}
          >
            <ReactMarkdown
              remarkPlugins={[remarkGfm, remarkMath]}
              rehypePlugins={[rehypeKatex]}
              components={{
                p: ({ node, ...props }) => (
                  <p style={{ margin: "0.5em 0" }} {...props} />
                ),
                pre: ({ children }) => (
                  <div
                    style={{
                      margin: "1em 0",
                      borderRadius: "8px",
                      overflow: "hidden",
                    }}
                  >
                    {children}
                  </div>
                ),
                code: ({
                  node,
                  inline,
                  className,
                  children,
                  ...props
                }: any) => {
                  const match = /language-(\w+)/.exec(className || "");
                  return !inline && match ? (
                    <SyntaxHighlighter
                      style={isDark ? vscDarkPlus : vs}
                      language={match[1]}
                      PreTag="div"
                      customStyle={{
                        margin: 0,
                        padding: "1.25em",
                        fontSize: "0.9em",
                        background: isDark
                          ? "rgba(0,0,0,0.3)"
                          : "rgba(0,0,0,0.03)",
                      }}
                      {...props}
                    >
                      {String(children).replace(/\n$/, "")}
                    </SyntaxHighlighter>
                  ) : (
                    <code
                      style={{
                        background: "rgba(127,127,127,0.2)",
                        padding: "2px 4px",
                        borderRadius: "4px",
                        fontSize: "0.9em",
                      }}
                      className={className}
                      {...props}
                    >
                      {children}
                    </code>
                  );
                },
              }}
            >
              {(() => {
                const content =
                  typeof msg === "string"
                    ? msg
                    : typeof msg.content === "string"
                      ? msg.content
                      : msg.content
                        ? JSON.stringify(msg.content)
                        : msg.streaming
                          ? ""
                          : "";

                // Preprocess LaTeX delimiters
                return content
                  .replace(/\\\[/g, "$$")
                  .replace(/\\\]/g, "$$")
                  .replace(/\\\(/g, "$")
                  .replace(/\\\)/g, "$");
              })()}
            </ReactMarkdown>
            {msg.streaming && (
              <Box
                component="span"
                sx={{
                  display: "inline-block",
                  width: "2px",
                  height: "1.1em",
                  bgcolor: "text.primary",
                  ml: 0.5,
                  verticalAlign: "text-bottom",
                  animation: "cursorBlink 1s step-end infinite",
                  "@keyframes cursorBlink": {
                    "0%, 100%": { opacity: 1 },
                    "50%": { opacity: 0.5 },
                  },
                }}
              />
            )}
          </Box>
        </Paper>
      </Box>
    );
  },
);

const ChatViewRaw: React.FC<ChatViewProps> = ({
  messages,
  nodes,
  edges,
  isLoading,
  input,
  setInput,
  onSendMessage,
  onSwitchCheckpoint,
  onSynthesize,
  onDeliberate,
  setShowTree,
  documents,
  setDocuments,
  activeCheckpoint,
  onDeleteNode,
  onEditAndRebranch,
  onFileUpload,
  showEditButton,
  threadId,
  selectedModels,
  stopStreaming,
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

      const newPositions = [];
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

      setMarkerPositions(newPositions);
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

  const handleSendMessage = (val: string) => {
    onSendMessage(val);
    setInput("");
  };

  const handleDeliberateClick = (val: string) => {
    onDeliberate(val);
    setInput("");
  };

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

  // Arena Logic
  // Synthesis Detection
  const isSynthesisNode = React.useCallback(
    (node: any) =>
      node?.data?.label === "Consensus Convergence" ||
      node?.data?.label?.includes(
        "Please act as the Crucible Lead. Synthesize these viewpoints",
      ),
    [],
  );

  const parentEdge = React.useMemo(
    () => edges.find((e) => e.target === activeCheckpoint),
    [edges, activeCheckpoint],
  );
  const parentId = parentEdge ? parentEdge.source : null;

  // Filter out synthesis nodes from parallel comparison - synthesis is a resolution, not a competitor
  const siblings = React.useMemo(
    () =>
      parentId
        ? nodes.filter(
            (n) =>
              edges.some((e) => e.source === parentId && e.target === n.id) &&
              !isSynthesisNode(n),
          )
        : [],
    [nodes, edges, parentId, isSynthesisNode],
  );

  // Arena is active only if we have multiple genuine AI responses and we AREN'T currently on a synthesis path
  const isArenaActive = React.useMemo(() => {
    const activeNode = nodes.find((n) => n.id === activeCheckpoint);
    return siblings.length > 1 && !isSynthesisNode(activeNode);
  }, [siblings, nodes, activeCheckpoint, isSynthesisNode]);

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
              gap: 4,
              px: 3,
              pt: 5,
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
                View Decision Tree
              </ButtonBase>
            </Box>

            {/* Empty State */}
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
                    The Council awaits
                  </Typography>
                  <Typography
                    variant="caption"
                    sx={{
                      maxWidth: 280,
                      display: "block",
                      color: "text.disabled",
                    }}
                  >
                    Submit a research question to begin parallel model
                    deliberation
                  </Typography>
                </Box>
              </Box>
            )}

            {/* Messages */}
            <AnimatePresence initial={false}>
              {messages.map((msg, i) => {
                const isUser = msg.role === "user" || msg.type === "human";
                const isLatest = i === messages.length - 1;

                // Skip technical synthesis prompts
                if (
                  msg.type === "synthesis" ||
                  msg.content?.startsWith(
                    "I have received perspectives from multiple models:",
                  )
                ) {
                  if (isLatest && isLoading) {
                    return (
                      <Box
                        component={motion.div}
                        key="synthesis-loading"
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
                            Synthesizing Consensus...
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
                  return null;
                }

                // Standard message bubble (Memoized with primitives)
                return (
                  <MessageBubble
                    key={`${i}-${msg.role}-${msg.model || "user"}`}
                    msg={msg}
                    isUser={isUser}
                    isDark={isDark}
                    onMount={registerMessageRef}
                    index={i}
                  />
                );
              })}
            </AnimatePresence>

            {/* Council Deliberation / Arena Footer */}
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
                          fontSize: "0.5625rem",
                          fontWeight: 800,
                          letterSpacing: "0.2em",
                          color: "text.secondary",
                        }}
                      >
                        Council Deliberation
                      </Typography>
                    </Box>
                    <ButtonBase
                      component={motion.button}
                      whileHover={{ scale: 1.03 }}
                      whileTap={{ scale: 0.97 }}
                      onClick={() =>
                        onSynthesize(
                          siblings.map((s: any) => s.data.label),
                          parentId,
                        )
                      }
                      sx={{
                        px: 2.5,
                        py: 0.8,
                        borderRadius: 8,
                        border: "1px solid rgba(139, 92, 246, 0.3)",
                        bgcolor: "rgba(139, 92, 246, 0.1)",
                        color: "#a78bfa",
                        fontSize: "0.5625rem",
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
                      Synthesize Consensus
                    </ButtonBase>
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
                  {siblings.map((sib: any, sIdx: number) => {
                    const isActive = sib.id === activeCheckpoint;
                    const sibModel = sib.metadata?.active_peer || "assistant";
                    const sibColor = getModelColor(sibModel);
                    const sibLabel = getModelLabel(sibModel);

                    return (
                      <Paper
                        key={sib.id}
                        component={motion.div}
                        whileHover={{ y: -4, borderColor: sibColor.main }}
                        onClick={() => onSwitchCheckpoint(sib.id)}
                        sx={{
                          cursor: "pointer",
                          borderRadius: 4,
                          overflow: "hidden",
                          transition: "all 0.3s",
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
                          boxShadow: isActive
                            ? `0 10px 30px -10px ${sibColor.border}`
                            : "none",
                          opacity: isActive ? 1 : 0.7,
                          "&:hover": {
                            opacity: 1,
                          },
                        }}
                      >
                        <Box
                          sx={{
                            display: "flex",
                            justifyContent: "space-between",
                            alignItems: "center",
                            mb: 2,
                          }}
                        >
                          <Box
                            sx={{
                              display: "flex",
                              alignItems: "center",
                              gap: 1.5,
                            }}
                          >
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
                              sx={{
                                fontSize: "0.75rem",
                                fontWeight: 800,
                                letterSpacing: "0.1em",
                                color: sibColor.text,
                              }}
                            >
                              {sibLabel}
                            </Typography>
                          </Box>
                          {isActive && (
                            <Box
                              sx={{
                                px: 0.8,
                                py: 0.2,
                                borderRadius: 1,
                                bgcolor: sibColor.main,
                                color: "#fff",
                                display: "flex",
                                alignItems: "center",
                              }}
                            >
                              <CheckCircle2
                                width={10}
                                height={10}
                                color="inherit"
                              />
                            </Box>
                          )}
                        </Box>
                        <Typography
                          variant="body2"
                          sx={{
                            lineHeight: 1.6,
                            color: isActive ? "text.primary" : "text.secondary",
                            display: "-webkit-box",
                            WebkitLineClamp: 3,
                            WebkitBoxOrient: "vertical",
                            overflow: "hidden",
                            fontSize: "0.75rem",
                            mb: 2,
                          }}
                        >
                          {sib.data.label.replace("...", "")}
                          {sib.data.label.length > 50 ? "..." : ""}
                        </Typography>
                        <Box
                          sx={{
                            mt: "auto",
                            pt: 1.5,
                            borderTop: "1px solid",
                            borderColor: "divider",
                            textAlign: "center",
                            fontSize: "0.7rem",
                            fontWeight: 800,
                            textTransform: "uppercase",
                            letterSpacing: "0.1em",
                            color: isActive ? sibColor.text : "text.disabled",
                          }}
                        >
                          {isActive ? "Currently Active" : "Review This Path"}
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
                    fontSize: "0.5625rem",
                    fontWeight: 600,
                    letterSpacing: "0.1em",
                    color: "text.secondary",
                  }}
                >
                  Council deliberating…
                </Typography>
                <ButtonBase
                  onClick={stopStreaming}
                  component={motion.button}
                  whileHover={{ scale: 1.05 }}
                  whileTap={{ scale: 0.95 }}
                  sx={{
                    ml: 1,
                    px: 1.5,
                    py: 0.5,
                    borderRadius: 4,
                    border: "1px solid",
                    borderColor: "error.main",
                    color: "error.main",
                    fontSize: "0.625rem",
                    fontWeight: 800,
                    textTransform: "uppercase",
                    letterSpacing: "0.05em",
                    background: isDark
                      ? "rgba(239, 68, 68, 0.1)"
                      : "rgba(239, 68, 68, 0.05)",
                    transition: "all 0.2s",
                    "&:hover": {
                      background: "error.main",
                      color: "white",
                      boxShadow: "0 0 15px rgba(239, 68, 68, 0.4)",
                    },
                  }}
                >
                  Stop
                </ButtonBase>
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
        onSendMessage={handleSendMessage}
        onDeliberate={handleDeliberateClick}
        stopStreaming={stopStreaming}
        onFileUpload={onFileUpload}
        documents={documents}
        setDocuments={setDocuments}
        selectedModels={selectedModels}
        messages={messages}
        onEditAndRebranch={onEditAndRebranch}
        showEditButton={showEditButton}
        isDark={isDark}
        initialInput={input}
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
