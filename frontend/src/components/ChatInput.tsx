import React from "react";
import {
  Box,
  Paper,
  Typography,
  ButtonBase,
  TextField,
  IconButton,
  Tooltip,
  Chip,
} from "@mui/material";
import { Send, FileText, Edit3, Scale, X, StopCircle } from "lucide-react";
import { motion } from "framer-motion";
import { Message } from "@/lib/types";

// ─── ChatInput ────────────────────────────────────────────────────────────────
// Extracted verbatim from ChatView.tsx — zero logic or style changes.

interface ChatInputProps {
  isLoading: boolean;
  onSendMessage: (val: string) => void;
  onDeliberate: (val: string) => void;
  stopStreaming: () => void;
  onFileUpload: (e: React.ChangeEvent<HTMLInputElement>) => void;
  documents: Record<string, any>;
  setDocuments: (docs: Record<string, any>) => void;
  selectedModels: string[];
  messages: Message[];
  onEditAndRebranch: () => void;
  showEditButton: boolean;
  isDark: boolean;
  initialInput?: string;
}

export const ChatInput = React.memo(
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

ChatInput.displayName = "ChatInput";
