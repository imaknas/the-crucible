import React from "react";
import { Box, ButtonBase, Tooltip, Typography } from "@mui/material";
import { CornerDownRight, Eraser, RotateCcw, User, Users } from "lucide-react";
import type { BranchPoint } from "@/lib/branching";
import { budgetShare, inheritDetails, inheritLine, type NextTurnContext } from "@/lib/context";

/** Who answers a clicked reply: its model, or every selected model. */
export interface AnswerChoice {
  replyModel: string;
  askAll: boolean;
  /** The Control Panel's selection. */
  selected: string[];
  onChange: (askAll: boolean) => void;
}

/** Each side of the switch: what the button reads, and what clicking it offers. */
function answerLabels({ replyModel, selected }: AnswerChoice, modelLabel: (id: string) => string) {
  const only = modelLabel(replyModel);
  const one = selected.length === 1 ? modelLabel(selected[0]) : null;
  return {
    narrowed: {
      text: `Only ${only}`,
      offer: one ? `Ask ${one} instead` : `Ask all ${selected.length} selected models instead`,
    },
    all: { text: one ? `${one} answers` : `All ${selected.length} answer`, offer: `Ask only ${only} instead` },
  };
}

/**
 * What the next turn inherits: how many messages and roughly how many
 * tokens of the tightest model's budget, whether it answers from a summary,
 * every model's numbers in the tooltip; and "Start fresh", which sends the
 * next message with none of them.
 */
function InheritRow({
  context,
  modelLabel,
  onStartFresh,
}: {
  context: NextTurnContext[] | null;
  modelLabel: (id: string) => string;
  onStartFresh?: () => void;
}) {
  const line = context ? inheritLine(context) : null;
  if (!line && !onStartFresh) return null;
  const share = context ? budgetShare(context) : 0;
  const details = (
    <Box component="span" sx={{ display: "block" }}>
      {context &&
        inheritDetails(context, modelLabel).map((d) => (
          <Box component="span" key={d} sx={{ display: "block" }}>
            {d}
          </Box>
        ))}
      <Box component="span" sx={{ display: "block", mt: 0.5, opacity: 0.8 }}>
        Approximate: one tokenizer for every model, before your message and any attachments.
      </Box>
    </Box>
  );
  return (
    <Box sx={{ display: "flex", alignItems: "center", gap: 1, pl: 2.75, minWidth: 0 }}>
      {line && (
        <Tooltip title={details} describeChild placement="top" enterDelay={300}>
          <Typography
            data-testid="branch-inherits"
            tabIndex={0}
            sx={{
              display: "flex",
              alignItems: "center",
              gap: 0.75,
              fontSize: "0.6875rem",
              color: "text.secondary",
              fontVariantNumeric: "tabular-nums",
              cursor: "help",
              minWidth: 0,
              whiteSpace: "nowrap",
              overflow: "hidden",
              textOverflow: "ellipsis",
            }}
          >
            <Box
              component="span"
              aria-hidden
              sx={{ width: 36, height: 4, borderRadius: 2, bgcolor: "action.selected", flexShrink: 0, overflow: "hidden" }}
            >
              <Box
                component="span"
                sx={{
                  display: "block",
                  height: "100%",
                  width: `${Math.max(share * 100, 3)}%`,
                  bgcolor: share >= 0.8 ? "warning.main" : "primary.main",
                }}
              />
            </Box>
            Sends {line}
          </Typography>
        </Tooltip>
      )}
      {onStartFresh && (
        <ButtonBase
          onClick={onStartFresh}
          title="Send the next message without any earlier messages, as a new branch of this tree"
          sx={{
            display: "flex",
            alignItems: "center",
            gap: 0.5,
            ml: "auto",
            px: 1,
            py: 0.25,
            borderRadius: 1.5,
            fontSize: "0.6875rem",
            fontWeight: 700,
            color: "text.secondary",
            flexShrink: 0,
            "&:hover": { bgcolor: "action.hover", color: "text.primary" },
          }}
        >
          <Eraser width={11} height={11} aria-hidden />
          Start fresh
        </ButtonBase>
      )}
    </Box>
  );
}

/**
 * Above the composer: what the next message continues — the latest turn
 * (every model its own reply there), a node the person chose, or nothing
 * ("Start fresh") — what it inherits from there, who answers it when a
 * model's reply was clicked, and a way back to the latest turn.
 */
export default function BranchChip({
  point,
  onReset,
  modelLabel,
  answer = null,
  context = null,
  onStartFresh,
}: {
  point: BranchPoint;
  onReset: () => void;
  modelLabel: (id: string) => string;
  /** Shown only when asking every selected model would change who answers. */
  answer?: AnswerChoice | null;
  /** What the next turn would send each answering model (useNextTurnContext). */
  context?: NextTurnContext[] | null;
  /** Branch from the thread's empty start instead; ignored when that's where it already is. */
  onStartFresh?: () => void;
}) {
  const meta = point.node.metadata;
  const side = answer ? answerLabels(answer, modelLabel)[answer.askAll ? "all" : "narrowed"] : null;
  const who =
    meta?.role === "user"
      ? "your message"
      : meta?.model_name || (meta?.active_peer ? modelLabel(meta.active_peer) : "a reply");
  return (
    <Box
      data-testid="branch-chip"
      sx={{
        mb: 1,
        px: 1.25,
        py: 0.5,
        borderRadius: 2,
        border: "1px solid",
        borderColor: point.isLatest ? "divider" : "warning.main",
        bgcolor: point.isLatest ? "transparent" : "rgba(245,158,11,0.08)",
        minWidth: 0,
      }}
    >
      <Box sx={{ display: "flex", alignItems: "center", gap: 1, minWidth: 0 }}>
        <CornerDownRight width={14} height={14} style={{ flexShrink: 0, opacity: 0.7 }} />
        <Typography
          title={
            point.fresh
              ? "A new branch from the start of this tree: no earlier messages are sent"
              : point.isLatest
                ? "Each model continues from its own reply in the latest turn"
                : meta?.preview || point.node.data.label
          }
          sx={{
            fontSize: "0.75rem",
            color: "text.secondary",
            flex: 1,
            minWidth: 0,
            whiteSpace: "nowrap",
            overflow: "hidden",
            textOverflow: "ellipsis",
          }}
        >
          {point.fresh ? (
            <>
              <Box component="span" sx={{ fontWeight: 700, color: "text.primary" }}>
                Starting fresh
              </Box>
              : the next message goes without any earlier ones
            </>
          ) : point.isLatest ? (
            <>
              Continuing the{" "}
              <Box component="span" sx={{ fontWeight: 700, color: "text.primary" }}>
                latest turn
              </Box>
            </>
          ) : (
            <>
              Branching from{" "}
              <Box component="span" sx={{ fontWeight: 700, color: "text.primary" }}>
                {who}
              </Box>
              : “{point.preview}”
            </>
          )}
        </Typography>
        {answer && side && (
          <ButtonBase
            onClick={() => answer.onChange(!answer.askAll)}
            aria-label={side.offer}
            title={side.offer}
            sx={{
              display: "flex",
              alignItems: "center",
              gap: 0.5,
              px: 1,
              py: 0.25,
              borderRadius: 1.5,
              fontSize: "0.75rem",
              fontWeight: 700,
              color: "primary.main",
              flexShrink: 0,
              "&:hover": { bgcolor: "action.hover" },
            }}
          >
            {answer.askAll ? <Users width={12} height={12} /> : <User width={12} height={12} />}
            {side.text}
          </ButtonBase>
        )}
        {!point.isLatest && (
          <ButtonBase
            onClick={onReset}
            aria-label="Continue the latest turn instead"
            sx={{
              display: "flex",
              alignItems: "center",
              gap: 0.5,
              px: 1,
              py: 0.25,
              borderRadius: 1.5,
              fontSize: "0.75rem",
              fontWeight: 700,
              color: "warning.main",
              flexShrink: 0,
              "&:hover": { bgcolor: "rgba(245,158,11,0.15)" },
            }}
          >
            <RotateCcw width={12} height={12} />
            Latest
          </ButtonBase>
        )}
      </Box>
      <InheritRow context={context} modelLabel={modelLabel} onStartFresh={point.fresh ? undefined : onStartFresh} />
    </Box>
  );
}
