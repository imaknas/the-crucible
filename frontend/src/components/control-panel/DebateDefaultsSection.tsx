import React from "react";
import { Box, Stack, Typography } from "@mui/material";
import { Swords } from "lucide-react";
import type { DebateDefaults } from "@/lib/types";
import { clampRounds } from "@/hooks/useDebateDefaults";
import { SectionHeader, ToggleRow } from "./primitives";

/** Defaults the debate dialog starts from (persisted by useDebateDefaults). */
export default function DebateDefaultsSection({
  isDark,
  debateDefaults,
  setDebateDefaults,
  maxRounds,
}: {
  isDark: boolean;
  debateDefaults: DebateDefaults;
  setDebateDefaults: (next: DebateDefaults | ((prev: DebateDefaults) => DebateDefaults)) => void;
  /** The backend's round limit (GET /models `limits.max_debate_rounds`). */
  maxRounds: number;
}) {
  // The field's raw text, committed on blur or Enter as the debate dialog
  // does: clamping per keystroke turned a cleared field into "3" and made a
  // two-digit count impossible to type.
  const [roundsText, setRoundsText] = React.useState(String(debateDefaults.max_rounds));
  const [seenRounds, setSeenRounds] = React.useState(debateDefaults.max_rounds);
  if (seenRounds !== debateDefaults.max_rounds) {
    setSeenRounds(debateDefaults.max_rounds);
    setRoundsText(String(debateDefaults.max_rounds));
  }
  const commitRounds = () => {
    const typed = Number.parseInt(roundsText.trim(), 10);
    const max_rounds = Number.isFinite(typed) ? clampRounds(typed, maxRounds) : debateDefaults.max_rounds;
    setRoundsText(String(max_rounds));
    if (max_rounds !== debateDefaults.max_rounds) setDebateDefaults((prev) => ({ ...prev, max_rounds }));
  };

  return (
    <Box>
      <SectionHeader label="Debate" />
      <Stack spacing={1.5}>
        <Box sx={{ display: "flex", alignItems: "center", gap: 1.5 }}>
          <Swords width={14} height={14} style={{ color: "#8b5cf6", flexShrink: 0 }} />
          <Typography variant="caption" sx={{ color: "text.secondary", lineHeight: 1.4 }}>
            Default config for autonomous multi-model debates.
          </Typography>
        </Box>
        <Box sx={{ display: "flex", alignItems: "center", gap: 1.5 }}>
          <Typography component="label" htmlFor="default-max-rounds" variant="caption" sx={{ color: "text.secondary", minWidth: 80 }}>
            Max rounds
          </Typography>
          <Box
            component="input"
            id="default-max-rounds"
            type="number"
            min={1}
            max={maxRounds}
            value={roundsText}
            onChange={(e: React.ChangeEvent<HTMLInputElement>) => setRoundsText(e.target.value)}
            onBlur={commitRounds}
            onKeyDown={(e: React.KeyboardEvent<HTMLInputElement>) => {
              if (e.key === "Enter") commitRounds();
            }}
            sx={{
              width: 56,
              px: 1,
              py: 0.5,
              borderRadius: 1.5,
              border: "1px solid",
              borderColor: "divider",
              bgcolor: "transparent",
              color: "text.primary",
              fontSize: "0.8rem",
              outline: "none",
              textAlign: "center",
              "&:focus": { borderColor: "primary.main" },
            }}
          />
        </Box>
        <ToggleRow
          isDark={isDark}
          label="Anonymous Participants"
          subtitle="Models see each other as Participant A, B… instead of by model name, so they weigh arguments rather than brands."
          icon={<Swords width={16} height={16} />}
          checked={debateDefaults.peer_labels === "anonymous"}
          onChange={() =>
            setDebateDefaults((prev) => ({
              ...prev,
              peer_labels: prev.peer_labels === "anonymous" ? "named" : "anonymous",
            }))
          }
        />
        <ToggleRow
          isDark={isDark}
          label="Auto-Synthesize"
          subtitle="Automatically run a synthesis pass after all rounds complete."
          icon={<Swords width={16} height={16} />}
          checked={debateDefaults.auto_synthesize}
          onChange={() =>
            setDebateDefaults((prev) => ({
              ...prev,
              auto_synthesize: !prev.auto_synthesize,
            }))
          }
        />
        <ToggleRow
          isDark={isDark}
          label="Stop When Answers Stop Changing"
          subtitle="Stop early once each model's answer barely changes from its previous round. This is stability, not agreement."
          icon={<Swords width={16} height={16} />}
          checked={debateDefaults.convergence_threshold !== null}
          onChange={() =>
            setDebateDefaults((prev) => ({
              ...prev,
              convergence_threshold:
                prev.convergence_threshold !== null ? null : 0.92,
            }))
          }
        />
      </Stack>
    </Box>
  );
}
