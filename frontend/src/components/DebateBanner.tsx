import React from "react";
import { Box, ButtonBase, Typography, useTheme } from "@mui/material";
import { Pause, Play, Sparkles, Swords, X as XIcon } from "lucide-react";
import type { DebateUiStatus } from "@/lib/types";

export interface DebateBannerState {
  round: number;
  maxRounds: number;
  status: DebateUiStatus;
  convergenceScore?: number;
}

const DEBATE_STATUS_STYLE: Record<DebateUiStatus, { bg: string; fg: string }> = {
  running: { bg: "rgba(16,185,129,0.2)", fg: "#10b981" },
  pausing: { bg: "rgba(245,158,11,0.2)", fg: "#f59e0b" },
  paused: { bg: "rgba(245,158,11,0.2)", fg: "#f59e0b" },
  converged: { bg: "rgba(139,92,246,0.2)", fg: "#a78bfa" },
  completed: { bg: "rgba(100,116,139,0.2)", fg: "text.secondary" },
  interrupted: { bg: "rgba(100,116,139,0.2)", fg: "text.secondary" },
};

/**
 * The strip above a debate transcript: round, convergence, status and the
 * controls that apply right now. Which controls exist is decided by the
 * caller (debateControls in lib/debateTranscript); absent handlers hide them.
 */
export default function DebateBanner({
  state,
  onPause,
  onResume,
  onSynthesize,
  onClose,
}: {
  state: DebateBannerState;
  onPause?: () => void;
  onResume?: () => void;
  onSynthesize?: () => void;
  onClose?: () => void;
}) {
  const isDark = useTheme().palette.mode === "dark";
  return (
    <Box
      sx={{
        flexShrink: 0,
        px: 3,
        py: 1,
        display: "flex",
        alignItems: "center",
        gap: 1.5,
        bgcolor: isDark ? "rgba(109,40,217,0.12)" : "rgba(109,40,217,0.07)",
        borderBottom: "1px solid rgba(139,92,246,0.25)",
      }}
    >
      <Swords width={13} height={13} color="#8b5cf6" />
      <Typography
        variant="overline"
        sx={{ fontSize: "0.65rem", fontWeight: 800, letterSpacing: "0.12em", color: "#8b5cf6" }}
      >
        DEBATE · ROUND {state.round + 1}/{state.maxRounds}
      </Typography>
      {state.convergenceScore != null && (
        <Typography variant="caption" sx={{ color: "text.secondary", fontSize: "0.7rem" }}>
          convergence {(state.convergenceScore * 100).toFixed(0)}%
        </Typography>
      )}
      <Box
        sx={{
          px: 1,
          py: 0.25,
          borderRadius: 1,
          bgcolor: DEBATE_STATUS_STYLE[state.status].bg,
          color: DEBATE_STATUS_STYLE[state.status].fg,
          fontSize: "0.6rem",
          fontWeight: 700,
          letterSpacing: "0.08em",
          textTransform: "uppercase",
        }}
      >
        {state.status === "pausing" ? "pausing after this round" : state.status}
      </Box>
      <Box sx={{ flex: 1 }} />
      {(onPause || onResume) && (
        <ButtonBase
          onClick={onPause ?? onResume}
          aria-label={onPause ? "Pause debate" : "Resume debate"}
          title={onPause ? "Pause after the current round" : "Resume"}
          sx={{
            display: "flex",
            alignItems: "center",
            gap: 0.5,
            px: 1.25,
            py: 0.5,
            borderRadius: 1.5,
            fontSize: "0.65rem",
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
            fontSize: "0.65rem",
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
          title="Close debate (stops it if running)"
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
