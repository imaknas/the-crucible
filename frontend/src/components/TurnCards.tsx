import { SYNTHESIS_MODES, type SynthesisMode, type SynthesisRequest } from "@/lib/synthesis";
import PeerReviewPanel from "./PeerReviewPanel";
import type { AnswerReview } from "@/lib/types";
import React from "react";
import { Box, ButtonBase, CircularProgress, Divider, MenuItem, Paper, Select, Stack, Typography } from "@mui/material";
import { AlertTriangle, CheckCircle2, Scale, Sparkles } from "lucide-react";
import { MessageBody, getModelColor } from "./MessageBubble";
import type { TurnCard } from "@/lib/turns";
import type { ModelError } from "@/lib/types";
import { turnTotal } from "@/lib/metrics";
import { ReplyMetricsLine, TurnMetricsLine } from "./ReplyMetrics";

const actionSx = (color: string) => ({
  px: 1,
  py: 0.5,
  borderRadius: 1.5,
  fontSize: "0.7rem",
  fontWeight: 800,
  textTransform: "uppercase" as const,
  letterSpacing: "0.08em",
  color,
  "&:hover": { bgcolor: "action.hover" },
  "&.Mui-disabled": { color: "text.secondary", opacity: 0.6 },
});

interface CardProps {
  card: TurnCard;
  isDark: boolean;
  modelLabel: (id: string) => string;
  onViewReply: (id: string) => void;
  onContinueReply: (id: string) => void;
  /** This model's failure, for Retry. */
  error?: ModelError;
  onRetry?: (errorId: string) => void;
  onDismiss?: (errorId: string) => void;
  retryDisabled?: boolean;
}

/**
 * One model's answer in a turn: streams in place, then stays where it is.
 * The text is the whole reply (rendered like a bubble) once it is known
 * whole, else the tree's excerpt, which Read in full opens.
 */
export const CompareCard = React.memo(function CompareCard({
  card,
  isDark,
  modelLabel,
  onViewReply,
  onContinueReply,
  error,
  onRetry,
  onDismiss,
  retryDisabled,
}: CardProps) {
  const color = getModelColor(card.model, isDark, card.color);
  const label = card.label || modelLabel(card.model);
  // Whole replies start open, excerpts clamped, until the person flips it.
  const [toggled, setToggled] = React.useState<boolean | null>(null);
  const open = toggled ?? card.full;
  const clamp = !card.streaming && !open;
  const failed = !!card.error;

  return (
    <Paper
      component="article"
      aria-label={`${label}'s answer`}
      aria-busy={card.streaming}
      data-state={card.streaming ? "streaming" : failed ? "failed" : card.stopped ? "stopped" : "done"}
      sx={{
        borderRadius: 3,
        overflow: "hidden",
        p: 2.5,
        display: "flex",
        flexDirection: "column",
        minWidth: 0,
        border: "1px solid",
        borderColor: failed ? "error.main" : card.shown ? color.main : isDark ? "rgba(255,255,255,0.08)" : "divider",
        bgcolor: card.shown
          ? isDark
            ? "rgba(139, 92, 246, 0.05)"
            : "rgba(139, 92, 246, 0.03)"
          : isDark
            ? "rgba(255,255,255,0.02)"
            : "background.paper",
        boxShadow: card.shown ? `0 10px 30px -10px ${color.border}` : "none",
      }}
    >
      <Box sx={{ display: "flex", alignItems: "center", gap: 1.25, mb: 1.5, minWidth: 0 }}>
        <Box sx={{ width: 8, height: 8, flexShrink: 0, borderRadius: "50%", bgcolor: color.dot }} />
        <Typography
          variant="overline"
          title={card.model}
          sx={{
            fontSize: "0.75rem",
            fontWeight: 800,
            letterSpacing: "0.1em",
            color: color.text,
            flex: 1,
            minWidth: 0,
            whiteSpace: "nowrap",
            overflow: "hidden",
            textOverflow: "ellipsis",
          }}
        >
          {label}
        </Typography>
        {card.streaming && (
          <Box role="status" sx={{ display: "flex", alignItems: "center", gap: 0.5, fontSize: "0.6875rem", fontWeight: 700, color: "text.secondary" }}>
            <CircularProgress size={10} thickness={6} />
            {card.text ? "Writing…" : "Waiting…"}
          </Box>
        )}
        {card.shown && !card.streaming && (
          <Box
            title="Your next message continues this conversation"
            sx={{ display: "flex", alignItems: "center", gap: 0.5, fontSize: "0.6875rem", fontWeight: 700, color: color.text }}
          >
            <CheckCircle2 width={12} height={12} />
            On screen
          </Box>
        )}
      </Box>

      {failed ? (
        <Box role="alert" sx={{ display: "flex", gap: 1, alignItems: "flex-start", color: "error.main", mb: 1 }}>
          <AlertTriangle width={14} height={14} style={{ flexShrink: 0, marginTop: 2 }} />
          <Typography variant="body2" sx={{ fontSize: "0.8125rem" }}>
            {card.error}
          </Typography>
        </Box>
      ) : null}

      {card.text || !failed ? (
        <Box
          sx={{
            mb: 1,
            minWidth: 0,
            ...(clamp ? { maxHeight: "8.5em", overflow: "hidden", maskImage: "linear-gradient(#000 70%, transparent)" } : {}),
          }}
        >
          {card.full ? (
            <MessageBody
              msg={{ id: card.key, role: "assistant", content: card.text, streaming: card.streaming, stopped: card.stopped }}
              isDark={isDark}
              compact
            />
          ) : (
            <Typography variant="body2" sx={{ lineHeight: 1.6, fontSize: "0.8125rem", color: "text.primary" }}>
              {card.text}
            </Typography>
          )}
        </Box>
      ) : null}

      {!card.streaming && card.text && (
        <ButtonBase
          onClick={() => setToggled(!open)}
          aria-expanded={open}
          sx={{ alignSelf: "flex-start", mb: 1.5, fontSize: "0.75rem", fontWeight: 700, color: color.text }}
        >
          {open ? "Show less" : "Show more"}
        </ButtonBase>
      )}

      {!card.streaming && !failed && (
        <Box sx={{ mb: 1.5 }}>
          <ReplyMetricsLine metrics={card.metrics} />
        </Box>
      )}

      <Box
        sx={{
          mt: "auto",
          pt: 1.5,
          borderTop: "1px solid",
          borderColor: "divider",
          display: "flex",
          flexWrap: "wrap",
          gap: 1,
          justifyContent: "space-between",
        }}
      >
        {failed && error ? (
          <>
            <ButtonBase onClick={() => onRetry?.(error.id)} disabled={retryDisabled} sx={actionSx(color.text)}>
              Retry
            </ButtonBase>
            <ButtonBase onClick={() => onDismiss?.(error.id)} sx={{ ...actionSx("text.secondary"), ml: "auto" }}>
              Dismiss
            </ButtonBase>
          </>
        ) : (
          <>
            {!card.full && card.id && (
              <ButtonBase
                onClick={() => onViewReply(card.id!)}
                title="Show this answer's conversation; who answers next doesn't change"
                sx={actionSx(color.text)}
              >
                Read in full
              </ButtonBase>
            )}
            <ButtonBase
              onClick={() => card.id && onContinueReply(card.id)}
              disabled={!card.id}
              title={
                card.id
                  ? `Continue from this answer: your next message goes to ${label}`
                  : "Available once this answer has finished"
              }
              aria-label={`Continue with ${label}`}
              sx={{ ...actionSx("text.secondary"), ml: "auto" }}
            >
              Continue from this
            </ButtonBase>
          </>
        )}
      </Box>
    </Paper>
  );
});

interface TurnProps {
  cards: TurnCard[];
  isDark: boolean;
  modelLabel: (id: string) => string;
  onViewReply: (id: string) => void;
  onContinueReply: (id: string) => void;
  /** Shown on the latest turn only: merge its answers. */
  synthesis?: {
    ids: string[];
    disabled: boolean;
    options: string[];
    firstSelected: string | null;
    onSynthesize: (ids: string[], model: string | null, request?: SynthesisRequest) => void;
  } | null;
  errors?: ModelError[];
  onRetry?: (errorId: string) => void;
  onDismiss?: (errorId: string) => void;
  retryDisabled?: boolean;
  /** The models score each other's answers (one call per author); its result shows under the cards. */
  review?: { result: AnswerReview | null; running: boolean; disabled: boolean; onRun: () => void } | null;
}

/** One turn's answers side by side, from the first token to the settled tree. */
export default function TurnCards({
  cards,
  isDark,
  modelLabel,
  onViewReply,
  onContinueReply,
  synthesis = null,
  errors = [],
  onRetry,
  onDismiss,
  retryDisabled,
  review = null,
}: TurnProps) {
  // "" = the first selected model, the original behaviour.
  const [synthesizer, setSynthesizer] = React.useState("");
  const [mode, setMode] = React.useState<SynthesisMode>("merge");
  const [question, setQuestion] = React.useState("");
  const action = SYNTHESIS_MODES.find((m) => m.mode === mode) ?? SYNTHESIS_MODES[0];
  const asks = mode === "ask";
  const columns = cards.length === 2 ? "repeat(2, minmax(0, 1fr))" : "repeat(3, minmax(0, 1fr))";
  // Shown once every answer is in (a total of half a turn would read as the
  // whole), under the cards, so its arrival doesn't move them.
  const total = cards.some((c) => c.streaming) ? null : turnTotal(cards.map((c) => c.metrics));
  return (
    <Box data-testid="turn-cards" sx={{ display: "flex", flexDirection: "column", gap: 2, width: "100%" }}>
      <Box sx={{ display: "flex", alignItems: "center", gap: 2 }}>
        <Divider sx={{ flex: 1 }} />
        <Stack alignItems="center" spacing={1}>
          <Box sx={{ display: "flex", alignItems: "center", gap: 1, color: "text.secondary" }}>
            <Scale width={12} height={12} />
            <Typography variant="overline" sx={{ fontSize: "0.6875rem", fontWeight: 800, letterSpacing: "0.2em" }}>
              {cards.length} answers
            </Typography>
          </Box>
          {synthesis && (
            <Box sx={{ display: "flex", flexWrap: "wrap", justifyContent: "center", alignItems: "center", gap: 1 }}>
              <Select
                size="small"
                variant="standard"
                disableUnderline
                value={mode}
                onChange={(e) => setMode(e.target.value as SynthesisMode)}
                inputProps={{ "aria-label": "How to combine the answers" }}
                sx={{ fontSize: "0.75rem", fontWeight: 600 }}
              >
                {SYNTHESIS_MODES.map((m) => (
                  <MenuItem key={m.mode} value={m.mode} sx={{ fontSize: "0.8rem", display: "block" }}>
                    {m.action}
                    <Typography component="span" sx={{ display: "block", fontSize: "0.72rem", color: "text.secondary", whiteSpace: "normal", maxWidth: 320 }}>
                      {m.description}
                    </Typography>
                  </MenuItem>
                ))}
              </Select>
              {asks && (
                <Box
                  component="input"
                  type="text"
                  aria-label="Your question about these answers"
                  placeholder="Your question about these answers"
                  value={question}
                  onChange={(e: React.ChangeEvent<HTMLInputElement>) => setQuestion(e.target.value)}
                  sx={{
                    minWidth: 220,
                    px: 1.25,
                    py: 0.5,
                    borderRadius: 2,
                    border: "1px solid",
                    borderColor: "divider",
                    bgcolor: "transparent",
                    color: "text.primary",
                    fontSize: "0.8rem",
                  }}
                />
              )}
              <ButtonBase
                onClick={() =>
                  synthesis.onSynthesize(synthesis.ids, synthesizer || null, asks ? { mode, question: question.trim() } : { mode })
                }
                disabled={synthesis.disabled || (asks && !question.trim())}
                sx={{
                  px: 2,
                  py: 0.75,
                  borderRadius: 8,
                  border: "1px solid rgba(139, 92, 246, 0.3)",
                  bgcolor: "rgba(139, 92, 246, 0.1)",
                  color: isDark ? "#c4b5fd" : "#6d28d9",
                  fontSize: "0.6875rem",
                  fontWeight: 800,
                  textTransform: "uppercase",
                  letterSpacing: "0.1em",
                  gap: 0.75,
                  "&.Mui-disabled": { opacity: 0.5 },
                }}
              >
                <Sparkles width={12} height={12} />
                {mode === "merge" ? "Synthesize answers" : mode === "compare" ? "Compare answers" : mode === "checklist" ? "Pick parts" : "Ask"}
              </ButtonBase>
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
                sx={{ fontSize: "0.75rem", fontWeight: 600 }}
              >
                <MenuItem value="" sx={{ fontSize: "0.8rem" }}>
                  {synthesis.firstSelected ? `${modelLabel(synthesis.firstSelected)} (first selected)` : "First selected model"}
                </MenuItem>
                {synthesis.options.map((m) => (
                  <MenuItem key={m} value={m} title={m} sx={{ fontSize: "0.8rem" }}>
                    {modelLabel(m)}
                  </MenuItem>
                ))}
              </Select>
            </Box>
          )}
        </Stack>
        <Divider sx={{ flex: 1 }} />
      </Box>
      <Box sx={{ display: "grid", gap: 2, gridTemplateColumns: { xs: "minmax(0, 1fr)", sm: columns } }}>
        {cards.map((card) => (
          <CompareCard
            key={card.key}
            card={card}
            isDark={isDark}
            modelLabel={modelLabel}
            onViewReply={onViewReply}
            onContinueReply={onContinueReply}
            error={errors.find((e) => e.model === card.model)}
            onRetry={onRetry}
            onDismiss={onDismiss}
            retryDisabled={retryDisabled}
          />
        ))}
      </Box>
      <TurnMetricsLine total={total} />
      {review && (
        <Box sx={{ display: "flex", alignItems: "center", gap: 1, flexWrap: "wrap" }}>
          <ButtonBase
            onClick={review.onRun}
            disabled={review.disabled || review.running}
            aria-busy={review.running}
            sx={{
              px: 1.5,
              py: 0.5,
              borderRadius: 2,
              border: "1px solid",
              borderColor: "divider",
              fontSize: "0.75rem",
              fontWeight: 600,
              gap: 0.75,
              "&.Mui-disabled": { opacity: 0.5 },
            }}
          >
            {review.running && <CircularProgress size={10} />}
            {review.result ? "Score each other again" : "Have them score each other"}
          </ButtonBase>
          <Typography variant="caption" sx={{ color: "text.secondary" }}>
            Each model scores the others&apos; answers anonymously, never its own: one call per model.
          </Typography>
        </Box>
      )}
      {review?.result && <PeerReviewPanel review={review.result} modelLabel={modelLabel} />}
    </Box>
  );
}
