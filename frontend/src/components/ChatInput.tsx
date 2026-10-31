import React from "react";
import { Box, Paper, Typography, ButtonBase, TextField, Tooltip, Chip, CircularProgress } from "@mui/material";
import { Send, FileText, Edit3, Scale, X, StopCircle, Swords, CornerUpLeft, Paperclip } from "lucide-react";
import { Message } from "@/lib/types";
import { charsLeft, debateAction, deliberateAction, sendAction, type ComposerAction } from "@/lib/composer";

interface ChatInputProps {
  isLoading: boolean;
  /** The text in the box. The page owns it: Edit & fork fills it, a started debate clears it. */
  value: string;
  onChange: (value: string) => void;
  onSendMessage: (val: string) => void;
  onDeliberate: (val: string) => void;
  stopStreaming: () => void;
  /** Upload a file and attach it to the next message. */
  onAttach: (file: File) => void;
  /** Files attached to the next message, by name. */
  documents: string[];
  onRemoveDocument: (name: string) => void;
  /** The file being uploaded right now, if any. */
  uploading?: string | null;
  /** The Control Panel's selection: a debate's participants. */
  selectedModels: string[];
  /** Who answers Send and Deliberate (lib/replyTarget); default: the selection. */
  respondingModels?: string[];
  messages: Message[];
  onEditAndRebranch: () => void;
  showEditButton: boolean;
  isDark: boolean;
  onDebateOpen?: (prompt: string) => void;
  onDebateInject?: (message: string) => void;
  onDebateRedirect?: (message: string) => void;
  /** A finished debate is on screen: Send continues the regular chat instead. */
  debateOnScreen?: boolean;
  /** Shown above the text box, e.g. which checkpoint the next message branches from. */
  header?: React.ReactNode;
  /** The backend's message limit (GET /models `limits.max_prompt_chars`). */
  maxChars?: number;
  /** Display names, to say who answers next where the composer is (the header hides it on phones). */
  modelLabel?: (id: string) => string;
  /** What else goes with the message: "System prompt", "Web search", "Document search". */
  contextNotes?: string[];
}

/**
 * A labelled secondary action (Deliberate, Debate, Redirect). The label shows
 * at every width (on phones the toolbar wraps instead of hiding it: an icon
 * alone named nothing there); the tooltip says why it is unavailable when it
 * is. Unavailable is `aria-disabled`, not
 * `disabled`: a disabled button can't take focus, so its "why" was
 * mouse-only. The click handlers check the action themselves.
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
    <Tooltip title={action.hint} placement="top" arrow describeChild>
      <span>
        <ButtonBase
          onClick={action.enabled ? onClick : undefined}
          aria-disabled={!action.enabled}
          aria-label={ariaLabel}
          sx={{
            cursor: action.enabled ? "pointer" : "not-allowed",
            display: "flex",
            alignItems: "center",
            gap: 0.75,
            px: { xs: 1, sm: 1.25 },
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
          <Box component="span">{label}</Box>
        </ButtonBase>
      </span>
    </Tooltip>
  );
}

export const ChatInput = React.memo(
  ({
    isLoading,
    value,
    onChange,
    onSendMessage,
    onDeliberate,
    stopStreaming,
    onAttach,
    documents,
    onRemoveDocument,
    uploading = null,
    selectedModels,
    respondingModels = selectedModels,
    messages,
    onEditAndRebranch,
    showEditButton,
    isDark,
    onDebateOpen,
    onDebateInject,
    onDebateRedirect,
    debateOnScreen = false,
    header,
    maxChars,
    modelLabel = (id: string) => id,
    contextNotes = [],
  }: ChatInputProps) => {
    const localInput = value;
    const fileRef = React.useRef<HTMLInputElement>(null);

    const left = maxChars ? charsLeft(localInput.length, maxChars) : null;
    const state = {
      isLoading,
      modelCount: respondingModels.length,
      hasHistory: messages.length > 0,
      hasText: !!localInput.trim(),
      overLimit: left !== null && left < 0 ? maxChars : null,
    };
    const deliberate = deliberateAction(state);
    // A debate is between the selected models, whichever reply is continued.
    const debate = debateAction({ ...state, modelCount: selectedModels.length });
    // Injecting goes to the debate, whichever models are selected.
    const send: ComposerAction = onDebateInject
      ? state.overLimit
        ? sendAction(state)
        : { enabled: state.hasText && !isLoading, hint: "Add to the debate's next round" }
      : sendAction(state);
    const redirect: ComposerAction = {
      enabled: state.hasText && !isLoading && !state.overLimit,
      hint: state.hasText ? "Change the topic and restart the debate" : "Type the new topic first",
    };

    const handleSend = () => {
      if (!send.enabled) return;
      if (onDebateInject) {
        onDebateInject(localInput);
        onChange("");
      } else {
        onSendMessage(localInput);
      }
    };

    const handleRedirect = () => {
      if (!redirect.enabled || !onDebateRedirect) return;
      onDebateRedirect(localInput);
    };

    // The typed text is optional: an empty box asks for a plain review.
    const handleDeliberateClick = () => {
      if (!deliberate.enabled) return;
      onDeliberate(localInput);
    };

    // The text stays until the debate actually starts (the page clears it
    // then), so cancelling the dialog doesn't lose it.
    const handleDebateClick = () => {
      if (!debate.enabled) return;
      onDebateOpen?.(localInput);
    };

    const who =
      respondingModels.length === 1
        ? `${modelLabel(respondingModels[0])} answers`
        : `${respondingModels.length} models answer`;
    const statusText = isLoading
      ? "Processing…"
      : onDebateInject
        ? "Debate · Send adds your message to the next round"
        : debateOnScreen
          ? `Debate over · Send starts a regular chat turn · ${who}`
          : [who, ...contextNotes].join(" · ");
    const statusTitle = onDebateInject
      ? statusText
      : `${respondingModels.map(modelLabel).join(", ")} ${respondingModels.length === 1 ? "answers" : "answer"}${
          contextNotes.length ? `, with ${contextNotes.join(", ").toLowerCase()}` : ""
        }`;
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
            {(documents.length > 0 || uploading) && (
              <Box sx={{ display: "flex", gap: 1, flexWrap: "wrap", alignItems: "center", pt: 1.5, px: 1.5 }}>
                {documents.map((docName) => (
                  <Chip
                    key={docName}
                    label={docName}
                    size="small"
                    onDelete={() => onRemoveDocument(docName)}
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
                {uploading && (
                  <Chip
                    size="small"
                    label={`Uploading ${uploading}…`}
                    icon={<CircularProgress size={10} sx={{ ml: 1 }} />}
                    sx={{ fontSize: "0.75rem", color: "text.secondary" }}
                  />
                )}
                {/* Attachments go with one message; said here because the chips
                    vanishing after Send looked like losing them. */}
                <Typography variant="caption" sx={{ color: "text.secondary", fontSize: "0.75rem" }}>
                  Sent with your next message only
                </Typography>
              </Box>
            )}
            <TextField
              fullWidth
              multiline
              maxRows={6}
              value={localInput}
              onChange={(e) => onChange(e.target.value)}
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

            {/* Toolbar: attach and status on the left, actions on the right, Send
                last and primary. On a phone the status takes its own line and the
                labelled actions wrap below it. */}
            <Box
              data-testid="composer-toolbar"
              sx={{
                display: "flex",
                flexWrap: { xs: "wrap", sm: "nowrap" },
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
                onChange={(e) => {
                  const file = e.target.files?.[0];
                  // Reset, or picking the same file again fires no change.
                  e.target.value = "";
                  if (file) onAttach(file);
                }}
                accept=".pdf,.txt"
                aria-hidden="true"
                tabIndex={-1}
              />
              <Tooltip title="Attach a PDF or text file" placement="top" arrow>
                <span>
                  <ButtonBase
                    aria-label="Attach a document"
                    disabled={!!uploading}
                    onClick={() => fileRef.current?.click()}
                    sx={{
                      display: "flex",
                      alignItems: "center",
                      gap: 0.5,
                      px: 1,
                      py: 0.75,
                      borderRadius: 2,
                      fontSize: "0.8125rem",
                      fontWeight: 700,
                      color: "text.secondary",
                      "&:hover": { bgcolor: "action.hover" },
                      "&.Mui-disabled": { opacity: 0.5 },
                    }}
                  >
                    <Paperclip width={15} height={15} />
                    <Box component="span">Attach</Box>
                  </ButtonBase>
                </span>
              </Tooltip>

              <Box
                sx={{
                  display: "flex",
                  alignItems: "center",
                  gap: 1,
                  flex: 1,
                  minWidth: 0,
                  order: { xs: -1, sm: 0 },
                  flexBasis: { xs: "100%", sm: "auto" },
                }}
              >
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
                  title={statusTitle}
                >
                  {statusText}
                </Typography>
                {left !== null && (
                  <Typography
                    data-testid="chars-left"
                    sx={{ fontSize: "0.75rem", fontWeight: 700, flexShrink: 0, color: left < 0 ? "error.main" : "warning.main" }}
                  >
                    {left < 0 ? `${(-left).toLocaleString()} over the limit` : `${left.toLocaleString()} characters left`}
                  </Typography>
                )}
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

              {/* Send (or Stop) keeps the right edge, also when the row wraps. */}
              <Box sx={{ ml: "auto", flexShrink: 0 }}>
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
                <Tooltip title={send.hint} placement="top" arrow describeChild>
                  <span>
                    <ButtonBase
                      onClick={handleSend}
                      aria-label={onDebateInject ? "Inject into debate" : "Send"}
                      aria-disabled={!send.enabled}
                      sx={{
                        cursor: send.enabled ? "pointer" : "not-allowed",
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
                        "&:hover": send.enabled ? { bgcolor: sendColor ? "#6d28d9" : "primary.dark" } : {},
                      }}
                    >
                      <Send width={16} height={16} />
                      <Box component="span">{onDebateInject ? "Inject" : "Send"}</Box>
                    </ButtonBase>
                  </span>
                </Tooltip>
              )}
              </Box>
            </Box>
          </Paper>
        </Box>
      </Box>
    );
  },
);

ChatInput.displayName = "ChatInput";
