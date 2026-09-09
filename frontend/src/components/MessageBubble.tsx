import React from "react";
import {
  Box,
  Paper,
  Typography,
  Stack,
  Accordion,
  AccordionSummary,
  AccordionDetails,
} from "@mui/material";
import { ChevronDown } from "lucide-react";
import { motion } from "framer-motion";
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
import { Message } from "@/lib/types";

const thinkRegex =
  /<(?:think|thinking)>([\s\S]*?)(?:<\/(?:think|thinking)>|$)/i;
const thinkGlobalRegex = /<(?:think|thinking)>[\s\S]*?<\/(?:think|thinking)>/gi;
const thinkStreamingRegex = /<(?:think|thinking)>[\s\S]*$/gi;
const confidenceCleanupRegex = /\n?\s*confidence:\s*\d+%\.?\s*$/i;

// ─── Helpers ──────────────────────────────────────────────────────────────────
// Extracted verbatim from ChatView.tsx — zero logic or style changes.

export function getModelColor(model?: string): {
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
  if (model === "synthesis")
    return {
      text: "#c4b5fd",
      bg: "rgba(139, 92, 246, 0.12)",
      border: "rgba(139, 92, 246, 0.3)",
      dot: "#8b5cf6",
      main: "#8b5cf6",
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

export function getModelLabel(model?: string): string {
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

// ─── MessageBubble ────────────────────────────────────────────────────────────

interface MessageBubbleProps {
  msg: Message;
  isUser: boolean;
  isDark: boolean;
  onMount: (node: HTMLDivElement | null, idx: number) => void;
  index: number;
}

export const MessageBubble = React.memo(
  ({ msg, isUser, isDark, onMount, index }: MessageBubbleProps) => {
    const modelColor = getModelColor(isUser ? undefined : msg.model);
    const modelLabel = getModelLabel(msg.model);

    // Standardize content string extraction for the whole component
    const rawContent =
      typeof msg.content === "string"
        ? msg.content
        : (msg as any).text ||
          (Array.isArray(msg.content)
            ? JSON.stringify(msg.content)
            : String(msg.content || ""));

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
                fontFamily:
                  "'Fira Code', 'Menlo', 'Monaco', 'Consolas', 'Liberation Mono', 'Courier New', monospace",
                fontSize: "0.85em",
                bgcolor: isDark ? "rgba(255,255,255,0.06)" : "rgba(0,0,0,0.04)",
                px: 0.6,
                py: 0.3,
                borderRadius: 1,
                fontWeight: 500,
              },
              "& pre code": {
                bgcolor: "transparent",
                p: 0,
                fontFamily: "inherit",
              },
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
            {/* Chain of Thought (Thinking Process) Accordion */}
            {(() => {
              // Ensure we use the raw string even if it's arriving as an object/array partially
              const contentStr = rawContent;
              const thinkMatch = contentStr.match(thinkRegex);
              if (!thinkMatch) return null;

              const thinkingProcess = thinkMatch[1].trim();
              // If we are streaming and have at least the <think> tag, or if we have finished and have content
              if (!thinkingProcess && !msg.streaming) return null;

              return (
                <Accordion
                  elevation={0}
                  disableGutters
                  defaultExpanded={true}
                  sx={{
                    mb: 2, // Changed from mt to mb
                    bgcolor: isDark
                      ? "rgba(139, 92, 246, 0.12)"
                      : "rgba(139, 92, 246, 0.08)",
                    borderRadius: 2,
                    border: "1px solid",
                    borderColor: isDark
                      ? "rgba(139, 92, 246, 0.3)"
                      : "rgba(139, 92, 246, 0.2)",
                    "&:before": { display: "none" },
                    overflow: "hidden",
                    boxShadow: isDark
                      ? "0 4px 12px rgba(0,0,0,0.2)"
                      : "0 4px 12px rgba(139, 92, 246, 0.1)",
                  }}
                >
                  <AccordionSummary
                    expandIcon={<ChevronDown size={16} color="#a78bfa" />}
                    sx={{
                      minHeight: "44px",
                      px: 2,
                      ".MuiAccordionSummary-content": { m: 0 },
                    }}
                  >
                    <Stack direction="row" alignItems="center" spacing={1.5}>
                      <Box
                        sx={{
                          display: "flex",
                          alignItems: "center",
                          justifyContent: "center",
                          color: "#a78bfa",
                        }}
                      >
                        {msg.streaming &&
                        !/<\/(think|thinking)>/i.test(contentStr) ? (
                          <Box
                            sx={{
                              width: 14,
                              height: 14,
                              borderRadius: "50%",
                              border: "2px solid",
                              borderTopColor: "transparent",
                              animation: "spin 1s linear infinite",
                              "@keyframes spin": {
                                "0%": { transform: "rotate(0deg)" },
                                "100%": { transform: "rotate(360deg)" },
                              },
                            }}
                          />
                        ) : (
                          <Box
                            sx={{
                              p: 0.5,
                              borderRadius: 1,
                              bgcolor: "rgba(167, 139, 250, 0.1)",
                            }}
                          >
                            <ChevronDown
                              size={14}
                              style={{ transform: "rotate(-90deg)" }}
                            />
                          </Box>
                        )}
                      </Box>
                      <Typography
                        variant="caption"
                        sx={{
                          fontWeight: 800,
                          letterSpacing: "0.1em",
                          color: "text.secondary",
                          textTransform: "uppercase",
                          fontSize: "0.625rem",
                        }}
                      >
                        {msg.streaming &&
                        !/<\/(think|thinking)>/i.test(contentStr)
                          ? "Model Thinking…"
                          : "Thinking Process"}
                      </Typography>
                    </Stack>
                  </AccordionSummary>
                  <AccordionDetails sx={{ px: 2, pb: 2, pt: 0 }}>
                    <Typography
                      variant="body2"
                      sx={{
                        fontSize: "0.85rem",
                        color: "text.secondary",
                        lineHeight: 1.6,
                        whiteSpace: "pre-wrap",
                        fontStyle: "italic",
                        opacity: 0.9,
                        borderLeft: "2px solid",
                        borderColor: "rgba(167, 139, 250, 0.3)",
                        pl: 2,
                        py: 0.5,
                      }}
                    >
                      {thinkingProcess || "Reasoning in progress..."}
                    </Typography>
                  </AccordionDetails>
                </Accordion>
              );
            })()}

            <ReactMarkdown
              remarkPlugins={[remarkGfm, remarkMath]}
              rehypePlugins={[rehypeKatex]}
              components={{
                p: ({ node, children, ...props }: any) => {
                  const contentText = String(children || "");
                  // Detect ASCII art or table indicators to apply monospace font even outside code blocks
                  const needsMonospace = /├|└|─|│|┌|┐|┼|┴|┬|\|/.test(
                    contentText,
                  );
                  return (
                    <p
                      style={{
                        margin: "0.5em 0",
                        fontFamily: needsMonospace
                          ? "'Fira Code', 'Menlo', 'Monaco', 'Consolas', monospace"
                          : "inherit",
                        whiteSpace: "pre-wrap",
                        fontSize: needsMonospace ? "0.9em" : "inherit",
                        letterSpacing: needsMonospace ? "0" : "inherit",
                      }}
                      {...props}
                    >
                      {children}
                    </p>
                  );
                },
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
                        fontFamily:
                          "'Fira Code', 'Menlo', 'Monaco', 'Consolas', 'Liberation Mono', 'Courier New', monospace",
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
                let content = rawContent;

                // Remove <think> and <thinking> blocks for the main Markdown rendering
                content = content.replace(thinkGlobalRegex, "").trim();
                // Handle unclosed tags during streaming
                content = content.replace(thinkStreamingRegex, "").trim();
                // Strip the self-reported confidence score from the visible body
                content = content.replace(confidenceCleanupRegex, "").trim();

                // Only preprocess LaTeX delimiters IF NOT STREAMING.
                // Doing this during streaming can block rehype-katex from rendering the whole paragraph.
                if (!msg.streaming) {
                  content = content
                    .replace(/\\\[/g, "$$")
                    .replace(/\\\]/g, "$$")
                    .replace(/\\\(/g, "$")
                    .replace(/\\\)/g, "$");
                }

                return content;
              })()}
            </ReactMarkdown>
            {msg.sources && msg.sources.length > 0 && (
              <Accordion
                elevation={0}
                sx={{
                  mt: 2,
                  bgcolor: isDark ? "rgba(0,0,0,0.1)" : "rgba(0,0,0,0.02)",
                  borderRadius: 2,
                  "&:before": { display: "none" },
                }}
              >
                <AccordionSummary
                  expandIcon={<ChevronDown size={16} />}
                  sx={{
                    minHeight: "40px",
                    ".MuiAccordionSummary-content": { m: 0 },
                  }}
                >
                  <Typography
                    variant="caption"
                    sx={{ fontWeight: 600, color: "text.secondary" }}
                  >
                    Sources Cited ({msg.sources.length})
                  </Typography>
                </AccordionSummary>
                <AccordionDetails sx={{ pt: 0 }}>
                  <Stack spacing={1.5}>
                    {msg.sources.map((src, i) => (
                      <Box
                        key={i}
                        sx={{
                          p: 1.5,
                          bgcolor: isDark
                            ? "rgba(255,255,255,0.02)"
                            : "rgba(0,0,0,0.02)",
                          borderRadius: 1.5,
                          border: "1px solid",
                          borderColor: "divider",
                        }}
                      >
                        <Typography
                          variant="overline"
                          color="primary.main"
                          fontWeight="bold"
                        >
                          Source {i + 1}: {src.filename}
                        </Typography>
                        <Typography
                          variant="caption"
                          color="text.secondary"
                          sx={{
                            display: "block",
                            mt: 0.5,
                            whiteSpace: "pre-wrap",
                            maxHeight: 150,
                            overflowY: "auto",
                          }}
                        >
                          {src.text}
                        </Typography>
                      </Box>
                    ))}
                  </Stack>
                </AccordionDetails>
              </Accordion>
            )}
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

MessageBubble.displayName = "MessageBubble";
