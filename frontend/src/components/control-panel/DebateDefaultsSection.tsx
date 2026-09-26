import React from "react";
import { Box, Stack, Typography } from "@mui/material";
import { Swords } from "lucide-react";
import type { DebateDefaults } from "@/lib/types";
import { SectionHeader, ToggleRow } from "./primitives";

/** Defaults the debate dialog starts from (persisted by useDebateDefaults). */
export default function DebateDefaultsSection({
  isDark,
  debateDefaults,
  setDebateDefaults,
}: {
  isDark: boolean;
  debateDefaults: DebateDefaults;
  setDebateDefaults: (next: DebateDefaults | ((prev: DebateDefaults) => DebateDefaults)) => void;
}) {
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
          <Typography variant="caption" sx={{ color: "text.secondary", minWidth: 80 }}>
            Max rounds
          </Typography>
          <Box
            component="input"
            type="number"
            min={1}
            max={20}
            value={debateDefaults.max_rounds}
            onChange={(e: React.ChangeEvent<HTMLInputElement>) =>
              setDebateDefaults((prev) => ({
                ...prev,
                max_rounds: Math.max(1, Math.min(20, parseInt(e.target.value) || 3)),
              }))
            }
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
          label="Convergence Detection"
          subtitle="Stop early when model responses become semantically similar."
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
