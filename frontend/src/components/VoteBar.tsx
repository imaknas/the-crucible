import React, { useState } from "react";
import { Box, Button, ButtonBase, MenuItem, Select, TextField, Typography } from "@mui/material";
import { Vote } from "lucide-react";
import { TASK_TYPES } from "@/lib/blind";
import type { TurnCard } from "@/lib/turns";
import type { AnswerVote } from "@/lib/types";
import type { VoteInput } from "@/hooks/useVotes";
import { RADIUS } from "@/theme";

type Choice = { outcome: "best"; id: string } | { outcome: "tie" | "all_bad" };

const choiceSx = (on: boolean) => ({
  px: 1.25,
  py: 0.5,
  borderRadius: `${RADIUS.sm}px`,
  border: "1px solid",
  borderColor: on ? "primary.main" : "divider",
  bgcolor: on ? "primary.main" : "transparent",
  color: on ? "primary.contrastText" : "text.primary",
  fontSize: "0.75rem",
  fontWeight: 700,
});

function describe(vote: AnswerVote): string {
  if (vote.outcome === "tie") return "a tie";
  if (vote.outcome === "all_bad") return "all bad";
  const best = vote.answers.find((a) => a.checkpoint_id === vote.winner_checkpoint_id);
  return best ? `${best.model_name} best${vote.blind ? ` (it was Answer ${best.letter})` : ""}` : "best";
}

/**
 * Under a finished turn: which answer is better — one of them, a tie, or
 * all bad — with the kind of task and an optional reason. Read blind, the
 * vote is what reveals who wrote which answer. One vote per turn; it can
 * be changed.
 */
export default function VoteBar({
  cards,
  blind,
  vote,
  lastTask,
  onVote,
}: {
  /** The turn's cards as shown (lettered when blind); every one finished. */
  cards: TurnCard[];
  blind: boolean;
  vote: AnswerVote | null;
  lastTask: string;
  onVote: (input: VoteInput) => Promise<boolean>;
}) {
  const [editing, setEditing] = useState(false);
  const [choice, setChoice] = useState<Choice | null>(null);
  const [task, setTask] = useState(vote?.task_type ?? lastTask);
  const [reason, setReason] = useState(vote?.reason ?? "");
  const [sending, setSending] = useState(false);

  if (vote && !editing) {
    return (
      <Box data-testid="vote-summary" sx={{ display: "flex", alignItems: "center", gap: 1, mt: 1, flexWrap: "wrap" }}>
        <Vote width={13} height={13} aria-hidden />
        <Typography sx={{ fontSize: "0.75rem", color: "text.secondary" }}>
          You voted {describe(vote)} · {vote.task_type}
          {vote.reason ? ` · “${vote.reason}”` : ""}
        </Typography>
        <ButtonBase
          onClick={() => setEditing(true)}
          sx={{ fontSize: "0.75rem", fontWeight: 700, color: "primary.main", px: 0.5, borderRadius: 1 }}
        >
          Change vote
        </ButtonBase>
      </Box>
    );
  }

  const submit = async () => {
    if (!choice) return;
    setSending(true);
    const ok = await onVote({
      outcome: choice.outcome,
      best: choice.outcome === "best" ? choice.id : null,
      reason: reason.trim() || null,
      taskType: task,
      blind,
    });
    setSending(false);
    if (ok) {
      setEditing(false);
      setChoice(null);
    }
  };
  const on = (c: Choice) =>
    !!choice &&
    choice.outcome === c.outcome &&
    (c.outcome !== "best" || (choice.outcome === "best" && choice.id === c.id));

  return (
    <Box
      data-testid="vote-bar"
      role="group"
      aria-label="Vote on these answers"
      sx={{
        mt: 1.5,
        p: 1.5,
        borderRadius: `${RADIUS.lg}px`,
        border: "1px dashed",
        borderColor: "divider",
        display: "flex",
        flexDirection: "column",
        gap: 1,
      }}
    >
      <Typography sx={{ fontSize: "0.8125rem", fontWeight: 700 }}>
        {blind ? "Which answer is better? Voting reveals who wrote each." : "Which answer is better?"}
      </Typography>
      <Box sx={{ display: "flex", gap: 0.75, flexWrap: "wrap" }}>
        {cards.map((c) => (
          <ButtonBase
            key={c.key}
            aria-pressed={on({ outcome: "best", id: c.id! })}
            onClick={() => setChoice({ outcome: "best", id: c.id! })}
            sx={choiceSx(on({ outcome: "best", id: c.id! }))}
          >
            {c.label} is best
          </ButtonBase>
        ))}
        <ButtonBase
          aria-pressed={on({ outcome: "tie" })}
          onClick={() => setChoice({ outcome: "tie" })}
          sx={choiceSx(on({ outcome: "tie" }))}
        >
          Tie
        </ButtonBase>
        <ButtonBase
          aria-pressed={on({ outcome: "all_bad" })}
          onClick={() => setChoice({ outcome: "all_bad" })}
          sx={choiceSx(on({ outcome: "all_bad" }))}
        >
          All bad
        </ButtonBase>
      </Box>
      <Box sx={{ display: "flex", gap: 1, alignItems: "center", flexWrap: "wrap" }}>
        <Select
          size="small"
          value={task}
          onChange={(e) => setTask(e.target.value)}
          inputProps={{ "aria-label": "Kind of task" }}
          sx={{ fontSize: "0.75rem", minWidth: 120 }}
        >
          {TASK_TYPES.map((t) => (
            <MenuItem key={t} value={t} sx={{ fontSize: "0.8rem" }}>
              {t}
            </MenuItem>
          ))}
        </Select>
        <TextField
          size="small"
          placeholder="Why (optional)"
          value={reason}
          onChange={(e) => setReason(e.target.value.slice(0, 500))}
          inputProps={{ "aria-label": "Why (optional)" }}
          sx={{ flex: 1, minWidth: 160, "& input": { fontSize: "0.8rem" } }}
        />
        <Button size="small" variant="contained" disabled={!choice || sending} onClick={submit}>
          {blind ? "Vote and reveal" : "Vote"}
        </Button>
        {vote && (
          <Button size="small" onClick={() => setEditing(false)}>
            Cancel
          </Button>
        )}
      </Box>
    </Box>
  );
}
