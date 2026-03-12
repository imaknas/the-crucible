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
