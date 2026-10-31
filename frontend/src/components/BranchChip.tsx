import React from "react";
import { Box, ButtonBase, Typography } from "@mui/material";
import { CornerDownRight, RotateCcw, User, Users } from "lucide-react";
import type { BranchPoint } from "@/lib/branching";

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
 * "Replying from: …" above the composer: the checkpoint the next message
 * branches from, who answers it when a model's reply was clicked, and a way
 * back to the newest node when it isn't that one.
 */
export default function BranchChip({
  point,
  onReset,
  modelLabel,
  answer = null,
}: {
  point: BranchPoint;
  onReset: () => void;
  modelLabel: (id: string) => string;
  /** Shown only when asking every selected model would change who answers. */
  answer?: AnswerChoice | null;
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
        display: "flex",
        alignItems: "center",
        gap: 1,
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
      <CornerDownRight width={14} height={14} style={{ flexShrink: 0, opacity: 0.7 }} />
      <Typography
        title={meta?.preview || point.node.data.label}
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
        {point.isLatest ? "Replying to " : "Branching from "}
        <Box component="span" sx={{ fontWeight: 700, color: "text.primary" }}>
          {who}
        </Box>
        : “{point.preview}”
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
          aria-label="Reply to the latest message instead"
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
  );
}
