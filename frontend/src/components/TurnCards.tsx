import { SYNTHESIS_MODES, type SynthesisMode, type SynthesisRequest } from "@/lib/synthesis";
import PeerReviewPanel from "./PeerReviewPanel";
import type { AnswerReview } from "@/lib/types";
import React from "react";
import { Box, Button, ButtonBase, CircularProgress, Divider, Menu, MenuItem, Paper, Select, Tooltip, Typography } from "@mui/material";
import { RADIUS } from "@/theme";
import { AlertTriangle, CheckCircle2, Scale, Sparkles } from "lucide-react";
import { MessageBody, getModelColor } from "./MessageBubble";
import type { TurnCard } from "@/lib/turns";
import type { ModelError } from "@/lib/types";
import { turnTotal } from "@/lib/metrics";
import { ReplyMetricsLine, TurnMetricsLine } from "./ReplyMetrics";
import { ReplyContextNote } from "./ContextNotes";
import { AddModelMenu, ContinueAllButton, NextHereMark } from "./TurnActions";

/**
 * A card's actions: sentence case and at least 28px tall. They were 11px
 * spaced capitals, read as captions ("COMPARE WITH…" looked like "SELECTED
 * MODELS") and were under the 24px target size.
 */
const actionSx = (color: string) => ({
  px: 1,
  minHeight: 28,
  borderRadius: 1.5,
  fontSize: "0.8125rem",
  fontWeight: 600,
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
  /** Every card of the turn: "Compare with…" offers the others. */
  peers?: TurnCard[];
  /** Show what differs between this answer and another (the diff dialog). */
  onCompare?: (card: TurnCard, other: TurnCard) => void;
  /** This reply is the branch point: the next message continues it. */
  primary?: boolean;
  /** Who answers the next message, in words, for the mark's tooltip. */
  answerers?: string;
  /** Make this reply the branch point with every selected model answering; absent when that is only its own model. */
  onContinueAll?: (id: string) => void;
  /** How many models are selected: "Continue with all 3". */
  selectedCount?: number;
  /** A blind comparison: no model colour or id anywhere on the card (its label is "Answer A"). */
  blind?: boolean;
}

/** A finished answer whose whole text can be had: shown in full, or read from its node. */
function comparable(card: TurnCard): boolean {
  return !card.streaming && !card.error && !!card.text && (card.full || !!card.id);
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
  peers = [],
  onCompare,
  primary = false,
  answerers = "",
  onContinueAll,
  selectedCount = 0,
  blind = false,
}: CardProps) {
  const color = getModelColor(blind ? "" : card.model, isDark, card.color);
  const label = card.label || modelLabel(card.model);
  // Whole replies start open, excerpts clamped, until the person flips it.
  const [toggled, setToggled] = React.useState<boolean | null>(null);
  const open = toggled ?? card.full;
  const clamp = !card.streaming && !open;
  const failed = !!card.error;
  const [compareAnchor, setCompareAnchor] = React.useState<HTMLElement | null>(null);
  const others = onCompare && comparable(card) ? peers.filter((p) => p.key !== card.key && comparable(p)) : [];
  const menuId = `compare-menu-${card.key}`;

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
        // A failed card is as tall as its message, not stretched to its row.
        alignSelf: failed ? "start" : undefined,
        border: "1px solid",
        borderColor: failed ? "error.main" : card.shown ? color.main : isDark ? "rgba(255,255,255,0.08)" : "divider",
        // The card on screen is tinted in its own model's colour (it was violet
        // for every model, the colour Google and syntheses also use).
        bgcolor: card.shown ? color.bg : isDark ? "rgba(255,255,255,0.02)" : "background.paper",
        boxShadow: card.shown ? `0 10px 30px -10px ${color.border}` : "none",
      }}
    >
      <Box sx={{ display: "flex", alignItems: "center", gap: 1.25, mb: 1.5, minWidth: 0 }}>
        <Box sx={{ width: 8, height: 8, flexShrink: 0, borderRadius: "50%", bgcolor: color.dot }} />
        {/* The model's name as it is written (in capitals, "GPT-6.2 Sol" read as an acronym and was cut short). */}
        <Typography
          component="h3"
          title={blind ? undefined : card.model}
          sx={{
            fontSize: "0.875rem",
            fontWeight: 700,
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
        {primary && card.id && !card.streaming ? (
          <NextHereMark answerers={answerers} color={color.text} />
        ) : (
          card.shown &&
          !card.streaming && (
            <Box
              title="This answer's conversation is the one on screen"
              sx={{ display: "flex", alignItems: "center", gap: 0.5, fontSize: "0.6875rem", fontWeight: 700, color: color.text }}
            >
              <CheckCircle2 width={12} height={12} />
              On screen
            </Box>
          )
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
          <ReplyContextNote context={card.context} modelLabel={modelLabel} />
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
            <ButtonBase
              onClick={() => onDismiss?.(error.id)}
              title="Remove this card; the other answers stay"
              sx={{ ...actionSx("text.secondary"), ml: "auto" }}
            >
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
            {others.length > 0 && (
              <>
                <ButtonBase
                  onClick={(e) => setCompareAnchor(e.currentTarget)}
                  aria-haspopup="menu"
                  aria-expanded={!!compareAnchor}
                  aria-controls={compareAnchor ? menuId : undefined}
                  title={`Show what differs between ${label}'s answer and another one`}
                  sx={actionSx(color.text)}
                >
                  Compare with…
                </ButtonBase>
                <Menu
                  id={menuId}
                  anchorEl={compareAnchor}
                  open={!!compareAnchor}
                  onClose={() => setCompareAnchor(null)}
                  slotProps={{ list: { "aria-label": `Compare ${label}'s answer with` } }}
                >
                  {others.map((other) => (
                    <MenuItem
                      key={other.key}
                      title={blind ? undefined : other.model}
                      onClick={() => {
                        setCompareAnchor(null);
                        onCompare?.(card, other);
                      }}
                      sx={{ fontSize: "0.85rem" }}
                    >
                      {other.label || modelLabel(other.model)}
                    </MenuItem>
                  ))}
                </Menu>
              </>
            )}
            {/* Who answers the next message, said by the button: this
                model alone, or every selected model from this answer. */}
            <Box sx={{ ml: "auto", display: "flex", flexWrap: "wrap", gap: 0.5, justifyContent: "flex-end" }}>
              <Tooltip
                title={
                  card.id
                    ? `Your next message continues this answer, and only ${label} answers it`
                    : card.stopped
                      ? "This answer was stopped before it finished, so there is nothing to continue"
                      : "Available once this answer has finished"
                }
                describeChild
              >
                <span>
                  <ButtonBase
                    onClick={() => card.id && onContinueReply(card.id)}
                    disabled={!card.id}
                    aria-label={`Continue with ${label}`}
                    sx={actionSx(color.text)}
                  >
                    Continue with {label}
                  </ButtonBase>
                </span>
              </Tooltip>
              {onContinueAll && card.id && (
                <ContinueAllButton onClick={() => onContinueAll(card.id!)} label={label} count={selectedCount} />
              )}
            </Box>
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
  /** "Compare with…" on a card: show what differs between two of the turn's answers. */
  onCompare?: (card: TurnCard, other: TurnCard) => void;
  /** The branch point, when one is chosen: its card says the next message continues it. */
  primaryId?: string | null;
  /** Who answers the next message, in words (the mark's tooltip). */
  answerers?: string;
  /** "Everyone continues from here" on a card: its reply, every selected model answering. */
  onContinueAll?: (id: string) => void;
  /** The Control Panel's selection: the action above is offered on a card only if it adds models. */
  selectedModels?: string[];
  /** "+ Add a model": ask one more model this turn's question. */
  addModel?: { options: string[]; disabled: boolean; onAdd: (model: string) => void; groupOf?: (id: string) => string } | null;
  /** A blind comparison (lib/blind): lettered cards, nothing that names a model until the vote. */
  blind?: boolean;
  /** "Save as a case": keep this turn to replay on other models later. */
  saveCase?: { disabled: boolean; saving: boolean; onSave: () => void } | null;
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
  onCompare,
  primaryId = null,
  answerers = "",
  onContinueAll,
  selectedModels = [],
  addModel = null,
  blind = false,
  saveCase = null,
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
  // Hidden while blind: time and cost fingerprint a model.
  const total = blind || cards.some((c) => c.streaming) ? null : turnTotal(cards.map((c) => c.metrics));
  const streaming = cards.some((c) => c.streaming);
  const failedCount = cards.filter((c) => c.error).length;
  const synthLabel =
    mode === "merge" ? "Synthesize answers" : mode === "compare" ? "Compare answers" : mode === "checklist" ? "Pick parts" : "Ask";
  return (
    <Box data-testid="turn-cards" sx={{ display: "flex", flexDirection: "column", gap: 2, width: "100%" }}>
      <Box sx={{ display: "flex", alignItems: "center", gap: 2 }}>
        <Divider sx={{ flex: 1 }} />
        {/* As tall from the first token as once "Add a model" appears (when
            the turn settles), so the cards below don't move. */}
        <Box sx={{ display: "flex", alignItems: "center", gap: 1, color: "text.secondary", minHeight: 28 }}>
          <Scale width={12} height={12} aria-hidden />
          <Typography component="h2" sx={{ fontSize: "0.8125rem", fontWeight: 600 }}>
            {cards.length} answers
          </Typography>
          {addModel && (
            <AddModelMenu
              id={cards.map((c) => c.key).join("-")}
              options={addModel.options}
              modelLabel={modelLabel}
              groupOf={addModel.groupOf}
              disabled={addModel.disabled || streaming}
              onAdd={addModel.onAdd}
            />
          )}
        </Box>
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
            peers={cards}
            onCompare={onCompare}
            primary={!!primaryId && card.id === primaryId}
            answerers={blind ? "" : answerers}
            blind={blind}
            selectedCount={selectedModels.length}
            onContinueAll={
              onContinueAll && selectedModels.some((m) => m !== card.model) ? onContinueAll : undefined
            }
          />
        ))}
      </Box>
      <TurnMetricsLine total={total} answered={streaming ? null : cards.length - failedCount} asked={cards.length} />
      {/* What to do with the answers, once they are in: under them, in one
          row. Combining sat above the cards and was offered while they were
          still streaming, before anyone had read them. */}
      {!streaming && (synthesis || review || saveCase) && (
        <Box
          data-testid="turn-tools"
          sx={{ display: "flex", flexWrap: "wrap", alignItems: "center", justifyContent: "center", gap: 1 }}
        >
          {synthesis && (
            <>
              <Select
                size="small"
                value={mode}
                onChange={(e) => setMode(e.target.value as SynthesisMode)}
                // The closed select shows the action alone; its description
                // is in the menu (it used to wrap the row onto two lines).
                renderValue={(v) => SYNTHESIS_MODES.find((m) => m.mode === v)?.action ?? v}
                inputProps={{ "aria-label": "How to combine the answers" }}
                sx={{ fontSize: "0.8125rem", minHeight: 32, "& .MuiSelect-select": { py: 0.5 } }}
              >
                {SYNTHESIS_MODES.map((m) => (
                  <MenuItem key={m.mode} value={m.mode} sx={{ fontSize: "0.8125rem", display: "block" }}>
                    {m.action}
                    <Typography component="span" sx={{ display: "block", fontSize: "0.75rem", color: "text.secondary", whiteSpace: "normal", maxWidth: 320 }}>
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
                    minHeight: 32,
                    px: 1.25,
                    borderRadius: `${RADIUS.md}px`,
                    border: "1px solid",
                    borderColor: "divider",
                    bgcolor: "transparent",
                    color: "text.primary",
                    fontSize: "0.8125rem",
                  }}
                />
              )}
              <Typography component="label" htmlFor="synthesizer-select" sx={{ fontSize: "0.8125rem", color: "text.secondary" }}>
                by
              </Typography>
              <Select
                size="small"
                value={synthesizer}
                displayEmpty
                onChange={(e) => setSynthesizer(String(e.target.value))}
                inputProps={{ id: "synthesizer-select", "aria-label": "Synthesis written by" }}
                sx={{ fontSize: "0.8125rem", minHeight: 32, "& .MuiSelect-select": { py: 0.5 } }}
              >
                <MenuItem value="" sx={{ fontSize: "0.8125rem" }}>
                  {synthesis.firstSelected ? `${modelLabel(synthesis.firstSelected)} (first selected)` : "First selected model"}
                </MenuItem>
                {synthesis.options.map((m) => (
                  <MenuItem key={m} value={m} title={m} sx={{ fontSize: "0.8125rem" }}>
                    {modelLabel(m)}
                  </MenuItem>
                ))}
              </Select>
              <Button
                variant="contained"
                size="small"
                disableElevation
                startIcon={<Sparkles width={14} height={14} aria-hidden />}
                onClick={() =>
                  synthesis.onSynthesize(synthesis.ids, synthesizer || null, asks ? { mode, question: question.trim() } : { mode })
                }
                disabled={synthesis.disabled || (asks && !question.trim())}
                title={action.description}
                sx={{ minHeight: 32 }}
              >
                {synthLabel}
              </Button>
            </>
          )}
          {review && (
            <Button
              variant="outlined"
              size="small"
              onClick={review.onRun}
              disabled={review.disabled || review.running}
              aria-busy={review.running}
              title="Each model scores the others' answers anonymously, never its own: one call per model"
              startIcon={review.running ? <CircularProgress size={10} /> : undefined}
              sx={{ minHeight: 32 }}
            >
              {review.result ? "Score each other again" : "Have them score each other"}
            </Button>
          )}
          {saveCase && (
            <Button
              variant="outlined"
              size="small"
              onClick={saveCase.onSave}
              disabled={saveCase.disabled || saveCase.saving}
              aria-busy={saveCase.saving}
              title="Keep this turn's question, context, answers and your vote, to replay on other models later"
              startIcon={saveCase.saving ? <CircularProgress size={10} /> : undefined}
              sx={{ minHeight: 32 }}
            >
              Save as a case
            </Button>
          )}
        </Box>
      )}
      {review?.result && <PeerReviewPanel review={review.result} modelLabel={modelLabel} />}
    </Box>
  );
}
