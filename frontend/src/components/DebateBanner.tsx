import React from "react";
import { Box, ButtonBase, Typography, useTheme } from "@mui/material";
import { Pause, Play, RotateCw, Sparkles, Swords, X as XIcon } from "lucide-react";
import type { DebateUiStatus } from "@/lib/types";
import type { PeerLegendEntry } from "@/lib/debateTranscript";

export interface DebateBannerState {
  round: number;
  maxRounds: number;
  status: DebateUiStatus;
  convergenceScore?: number;
  /** Which model each anonymous "Participant X" is; empty for named debates. */
  legend?: PeerLegendEntry[];
}

const DEBATE_STATUS_STYLE: Record<DebateUiStatus, { bg: string; fg: string }> = {
  running: { bg: "rgba(16,185,129,0.2)", fg: "#10b981" },
  pausing: { bg: "rgba(245,158,11,0.2)", fg: "#f59e0b" },
  paused: { bg: "rgba(245,158,11,0.2)", fg: "#f59e0b" },
  converged: { bg: "rgba(139,92,246,0.2)", fg: "#a78bfa" },
  stable: { bg: "rgba(100,116,139,0.2)", fg: "text.secondary" },
  completed: { bg: "rgba(100,116,139,0.2)", fg: "text.secondary" },
  interrupted: { bg: "rgba(100,116,139,0.2)", fg: "text.secondary" },
};

const STATUS_LABEL: Partial<Record<DebateUiStatus, string>> = {
  pausing: "pausing after this round",
  interrupted: "interrupted",
  // Agreement reached by reading each other, which is not evidence by itself.
  converged: "models now agree (after debating)",
  stable: "answers stopped changing",
};

/** What a status means, where the label alone doesn't say. */
const STATUS_NOTE: Partial<Record<DebateUiStatus, string>> = {
  paused: "Paused while this tab stays open; leaving it stops the debate.",
  interrupted: "Stopped when the tab running it closed or lost its connection.",
};

export interface DebateBannerProps {
  state: DebateBannerState;
  onPause?: () => void;
  onResume?: () => void;
  /** Run more rounds of a debate that stopped (debate_continue). */
  onContinue?: () => void;
  onSynthesize?: () => void;
  onClose?: () => void;
}

/**
 * The strip above a debate transcript or tree: round, convergence, status and the
 * controls that apply right now. Which controls exist is decided by the
 * caller (debateControls in lib/debateTranscript); absent handlers hide them.
 */
export default function DebateBanner({
  state,
  onPause,
  onResume,
  onContinue,
  onSynthesize,
  onClose,
}: DebateBannerProps) {
  const note = STATUS_NOTE[state.status];
  const resumes = state.status === "interrupted";
  const isDark = useTheme().palette.mode === "dark";
  return (
    <Box
      sx={{
        flexShrink: 0,
        px: { xs: 1.5, sm: 3 },
        py: 1,
        display: "flex",
        flexWrap: "wrap",
        alignItems: "center",
        gap: 1.5,
        bgcolor: isDark ? "rgba(109,40,217,0.12)" : "rgba(109,40,217,0.07)",
        borderBottom: "1px solid rgba(139,92,246,0.25)",
      }}
    >
      <Swords width={13} height={13} color="#8b5cf6" />
      <Typography
        variant="overline"
        sx={{ fontSize: "0.6875rem", fontWeight: 800, letterSpacing: "0.12em", color: "#8b5cf6" }}
      >
        DEBATE · ROUND {state.round + 1}/{state.maxRounds}
      </Typography>
      {state.convergenceScore != null && (
        <Typography
          variant="caption"
          title="How little each model's answer changed from its own previous round. Not agreement between models."
          sx={{ color: "text.secondary", fontSize: "0.7rem" }}
        >
          stability {(state.convergenceScore * 100).toFixed(0)}%
        </Typography>
      )}
      <Box
        sx={{
          px: 1,
          py: 0.25,
          borderRadius: 1,
          bgcolor: DEBATE_STATUS_STYLE[state.status].bg,
          color: DEBATE_STATUS_STYLE[state.status].fg,
          fontSize: "0.6875rem",
          fontWeight: 700,
          letterSpacing: "0.08em",
          textTransform: "uppercase",
        }}
      >
        {STATUS_LABEL[state.status] ?? state.status}
      </Box>
      {note && (
        <Typography variant="caption" sx={{ color: "text.secondary", fontSize: "0.75rem" }}>
          {note}
        </Typography>
      )}
      {state.legend && state.legend.length > 0 && (
        <Box
          aria-label="Who each participant is"
          sx={{ display: "flex", flexWrap: "wrap", alignItems: "center", gap: 1, minWidth: 0 }}
        >
          {state.legend.map((entry) => (
            <Typography
              key={entry.label}
              variant="caption"
              title={entry.modelId}
              sx={{ display: "inline-flex", alignItems: "center", gap: 0.5, fontSize: "0.7rem", color: "text.secondary" }}
            >
              <Box component="span" sx={{ width: 6, height: 6, borderRadius: "50%", bgcolor: entry.color }} />
              {entry.label.replace("Participant ", "")} = {entry.name}
            </Typography>
          ))}
        </Box>
      )}
      <Box sx={{ flex: 1 }} />
      {(onPause || onResume) && (
        <ButtonBase
          onClick={onPause ?? onResume}
          aria-label={onPause ? "Pause debate" : "Resume debate"}
          title={
            onPause
              ? "Pause after the current round. It holds only while this tab stays open."
              : "Resume the paused debate"
          }
          sx={{
            display: "flex",
            alignItems: "center",
            gap: 0.5,
            px: 1.25,
            py: 0.5,
            borderRadius: 1.5,
            fontSize: "0.6875rem",
            fontWeight: 700,
            color: "#f59e0b",
            border: "1px solid rgba(245,158,11,0.35)",
            "&:hover": { bgcolor: "rgba(245,158,11,0.12)" },
          }}
        >
          {onPause ? <Pause width={11} height={11} /> : <Play width={11} height={11} />}
          {onPause ? "Pause" : "Resume"}
        </ButtonBase>
      )}
      {onContinue && (
        <ButtonBase
          onClick={onContinue}
          aria-label={resumes ? "Resume the interrupted debate" : "Run one more round"}
          title={resumes ? "Run the rounds it has left, in this tab" : "Every participant answers once more"}
          sx={{
            display: "flex",
            alignItems: "center",
            gap: 0.5,
            px: 1.25,
            py: 0.5,
            borderRadius: 1.5,
            fontSize: "0.6875rem",
            fontWeight: 700,
            color: "#10b981",
            border: "1px solid rgba(16,185,129,0.35)",
            "&:hover": { bgcolor: "rgba(16,185,129,0.12)" },
          }}
        >
          <RotateCw width={11} height={11} />
          {resumes ? "Resume" : "One more round"}
        </ButtonBase>
      )}
      {onSynthesize && (
        <ButtonBase
          onClick={onSynthesize}
          sx={{
            display: "flex",
            alignItems: "center",
            gap: 0.5,
            px: 1.5,
            py: 0.5,
            borderRadius: 1.5,
            fontSize: "0.6875rem",
            fontWeight: 700,
            color: "#a78bfa",
            border: "1px solid rgba(139,92,246,0.35)",
            bgcolor: "rgba(139,92,246,0.1)",
            "&:hover": { bgcolor: "rgba(139,92,246,0.2)" },
          }}
        >
          <Sparkles width={11} height={11} />
          Synthesize
        </ButtonBase>
      )}
      {onClose && (
        <ButtonBase
          onClick={onClose}
          aria-label="Close debate"
          title="Close the debate (asks first if it is still running)"
          sx={{
            p: 0.5,
            borderRadius: 1,
            color: "text.disabled",
            "&:hover": { color: "error.main" },
          }}
        >
          <XIcon width={14} height={14} />
        </ButtonBase>
      )}
    </Box>
  );
}
