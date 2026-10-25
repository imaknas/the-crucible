import React from "react";
import { Box, Paper, Typography, ButtonBase, TextField, IconButton, Tooltip, Chip } from "@mui/material";
import { Send, FileText, Edit3, Scale, X, StopCircle, Swords, CornerUpLeft, Paperclip } from "lucide-react";
import { Message } from "@/lib/types";
import { debateAction, deliberateAction, sendAction, type ComposerAction } from "@/lib/composer";

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
  onDebateOpen?: (prompt: string) => void;
  onDebateInject?: (message: string) => void;
  onDebateRedirect?: (message: string) => void;
  /** Clears the composer whenever it changes (e.g. once a debate has started). */
  clearSignal?: number;
  /** A finished debate is on screen: Send continues the regular chat instead. */
  debateOnScreen?: boolean;
  /** Shown above the text box, e.g. which checkpoint the next message branches from. */
  header?: React.ReactNode;
}

/**
 * A labelled secondary action (Deliberate, Debate, Redirect). The label hides
 * on phones, where the tooltip and aria-label still name it; the tooltip says
 * why it is disabled when it is.
 */
function ComposerButton({
  action,
  label,
  ariaLabel,
  icon,
  accent,
  onClick,
}: {
  action: ComposerAction;
  label: string;
  ariaLabel: string;
  icon: React.ReactNode;
  accent: string;
  onClick: () => void;
}) {
  return (
    <Tooltip title={action.hint} placement="top" arrow>
      {/* A span so the tooltip still opens on a disabled button. */}
      <span>
        <ButtonBase
          onClick={onClick}
          disabled={!action.enabled}
          aria-label={ariaLabel}
          sx={{
            display: "flex",
            alignItems: "center",
            gap: 0.75,
            px: 1.25,
            py: 0.75,
            borderRadius: 2,
            fontSize: "0.8125rem",
            fontWeight: 700,
            border: "1px solid",
            borderColor: action.enabled ? `${accent}66` : "divider",
            color: action.enabled ? accent : "text.disabled",
            bgcolor: "transparent",
            transition: "background-color .15s",
            "&:hover": { bgcolor: action.enabled ? `${accent}1f` : "transparent" },
          }}
        >
          {icon}
          <Box component="span" sx={{ display: { xs: "none", sm: "inline" } }}>
            {label}
          </Box>
        </ButtonBase>
      </span>
    </Tooltip>
  );
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
    onDebateOpen,
    onDebateInject,
    onDebateRedirect,
    clearSignal = 0,
    debateOnScreen = false,
    header,
  }: ChatInputProps) => {
    const [localInput, setLocalInput] = React.useState(initialInput);
    const [seenClearSignal, setSeenClearSignal] = React.useState(clearSignal);
    if (clearSignal !== seenClearSignal) {
      setSeenClearSignal(clearSignal);
      setLocalInput("");
    }
    const fileRef = React.useRef<HTMLInputElement>(null);

    React.useEffect(() => {
      setLocalInput(initialInput);
    }, [initialInput]);

    const state = {
      isLoading,
      modelCount: selectedModels.length,
      hasHistory: messages.length > 0,
      hasText: !!localInput.trim(),
    };
    const deliberate = deliberateAction(state);
    const debate = debateAction(state);
    // Injecting goes to the debate, whichever models are selected.
    const send: ComposerAction = onDebateInject
      ? { enabled: state.hasText && !isLoading, hint: "Add to the debate's next round" }
      : sendAction(state);
    const redirect: ComposerAction = {
      enabled: state.hasText && !isLoading,
      hint: state.hasText ? "Change the topic and restart the debate" : "Type the new topic first",
    };

    const handleSend = () => {
      if (!send.enabled) return;
      if (onDebateInject) {
        onDebateInject(localInput);
      } else {
        onSendMessage(localInput);
      }
      setLocalInput("");
    };

    const handleRedirect = () => {
      if (!redirect.enabled || !onDebateRedirect) return;
      onDebateRedirect(localInput);
      setLocalInput("");
    };

    // The typed text is optional: an empty box asks for a plain review.
    const handleDeliberateClick = () => {
      if (!deliberate.enabled) return;
      onDeliberate(localInput);
      setLocalInput("");
    };

    // The text stays until the debate actually starts (clearSignal), so
    // cancelling the dialog doesn't lose it.
    const handleDebateClick = () => {
      if (!debate.enabled) return;
      onDebateOpen?.(localInput);
    };

    const statusText = isLoading
      ? "Processing…"
      : onDebateInject
        ? "Debate · Send adds your message to the next round"
        : debateOnScreen
          ? "Debate over · Send starts a regular chat turn"
          : "Ready";
    const sendColor = onDebateInject ? "#7c3aed" : undefined;

    return (
      <Box
        sx={{
          flexShrink: 0,
          borderTop: "1px solid",
          borderColor: "divider",
          px: { xs: 1.5, sm: 3 },
          py: { xs: 1.5, sm: 2 },
          bgcolor: isDark ? "rgba(10, 15, 30, 0.8)" : "rgba(255, 255, 255, 0.8)",
          backdropFilter: "blur(16px)",
        }}
      >
        <Box sx={{ maxWidth: 800, mx: "auto" }}>
          {header}
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
            {Object.keys(documents).length > 0 && (
              <Box sx={{ display: "flex", gap: 1, flexWrap: "wrap", pt: 1.5, px: 1.5 }}>
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
                    deleteIcon={<X width={12} height={12} aria-label={`Remove ${docName}`} />}
                    sx={{
                      bgcolor: isDark ? "rgba(255,255,255,0.06)" : "action.hover",
                      border: "1px solid",
                      borderColor: "divider",
                      borderRadius: 1.5,
                      fontSize: "0.75rem",
                      fontWeight: 600,
                      color: "text.secondary",
                    }}
                    icon={<FileText width={12} height={12} style={{ marginLeft: 8, color: "inherit" }} />}
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
                if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
                  e.preventDefault();
                  handleSend();
                }
              }}
              placeholder={
                onDebateInject ? "Ask the arena… (goes to the debate's next round)" : "Ask the arena…"
              }
              variant="standard"
              slotProps={{
                htmlInput: { "aria-label": "Message" },
                input: {
                  disableUnderline: true,
                  sx: { px: 2.5, pt: 2, pb: 1, fontSize: "1rem", fontWeight: 500, color: "text.primary" },
                },
              }}
            />

            {/* Toolbar: attach and status on the left, actions on the right, Send last and primary. */}
            <Box
              sx={{
                display: "flex",
                alignItems: "center",
                gap: 1,
                px: 1.25,
                pb: 1.25,
                pt: 0.5,
              }}
            >
              <input
                ref={fileRef}
                type="file"
                hidden
                onChange={onFileUpload}
                accept=".pdf,.txt"
                aria-hidden="true"
                tabIndex={-1}
              />
              <Tooltip title="Attach a PDF or text file" placement="top" arrow>
                <IconButton
                  size="small"
                  aria-label="Attach a document"
                  onClick={() => fileRef.current?.click()}
                  sx={{ color: "text.secondary" }}
                >
                  <Paperclip width={16} height={16} />
                </IconButton>
              </Tooltip>

              <Box sx={{ display: "flex", alignItems: "center", gap: 1, flex: 1, minWidth: 0 }}>
                <Box
                  sx={{
                    width: 6,
                    height: 6,
                    flexShrink: 0,
                    borderRadius: "50%",
                    bgcolor: isLoading ? "primary.main" : "success.main",
                  }}
                />
                <Typography
                  role="status"
                  sx={{
                    fontSize: "0.75rem",
                    fontWeight: 600,
                    color: "text.secondary",
                    whiteSpace: "nowrap",
                    overflow: "hidden",
                    textOverflow: "ellipsis",
                  }}
                  title={statusText}
                >
                  {statusText}
                </Typography>
              </Box>

              {showEditButton && (
                <ComposerButton
                  action={{ enabled: true, hint: "Edit this message and ask again on a new branch" }}
                  label="Edit & fork"
                  ariaLabel="Edit and fork"
                  icon={<Edit3 width={14} height={14} />}
                  accent="#f59e0b"
                  onClick={onEditAndRebranch}
                />
              )}
              <ComposerButton
                action={deliberate}
                label="Deliberate"
                ariaLabel="Deliberate"
                icon={<Scale width={15} height={15} />}
                accent="#a855f7"
                onClick={handleDeliberateClick}
              />
              {onDebateOpen && (
                <ComposerButton
                  action={debate}
                  label="Debate"
                  ariaLabel="Start debate"
                  icon={<Swords width={15} height={15} />}
                  accent="#8b5cf6"
                  onClick={handleDebateClick}
                />
              )}
              {onDebateRedirect && (
                <ComposerButton
                  action={redirect}
                  label="Redirect"
                  ariaLabel="Change topic and restart debate"
                  icon={<CornerUpLeft width={15} height={15} />}
                  accent="#f59e0b"
                  onClick={handleRedirect}
                />
              )}

              {isLoading ? (
                <Tooltip title="Stop generating" placement="top" arrow>
                  <ButtonBase
                    onClick={stopStreaming}
                    aria-label="Stop generating"
                    sx={{
                      p: 1.25,
                      borderRadius: "50%",
                      bgcolor: isDark ? "rgba(239, 68, 68, 0.2)" : "rgba(239, 68, 68, 0.1)",
                      color: "error.main",
                      border: "1px solid",
                      borderColor: "error.main",
                      "&:hover": { bgcolor: "error.main", color: "white" },
                    }}
                  >
                    <StopCircle width={18} height={18} />
                  </ButtonBase>
                </Tooltip>
              ) : (
                <Tooltip title={send.hint} placement="top" arrow>
                  <span>
                    <ButtonBase
                      onClick={handleSend}
                      aria-label={onDebateInject ? "Inject into debate" : "Send"}
                      disabled={!send.enabled}
                      sx={{
                        display: "flex",
                        alignItems: "center",
                        gap: 0.75,
                        px: 1.75,
                        py: 1,
                        borderRadius: 2,
                        fontSize: "0.875rem",
                        fontWeight: 700,
                        color: "white",
                        bgcolor: sendColor ?? "primary.main",
                        opacity: send.enabled ? 1 : 0.45,
                        boxShadow: send.enabled ? "0 4px 12px rgba(37,99,235,0.3)" : "none",
                        transition: "opacity .15s, background-color .15s",
                        "&:hover": { bgcolor: sendColor ? "#6d28d9" : "primary.dark" },
                        "&.Mui-disabled": { color: "white" },
                      }}
                    >
                      <Send width={16} height={16} />
                      <Box component="span" sx={{ display: { xs: "none", sm: "inline" } }}>
                        {onDebateInject ? "Inject" : "Send"}
                      </Box>
                    </ButtonBase>
                  </span>
                </Tooltip>
              )}
            </Box>
          </Paper>
        </Box>
      </Box>
    );
  },
);

ChatInput.displayName = "ChatInput";
