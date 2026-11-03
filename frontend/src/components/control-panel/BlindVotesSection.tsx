import React from "react";
import { Box, MenuItem, Select, Stack, Typography } from "@mui/material";
import { EyeOff } from "lucide-react";
import { TASK_TYPES } from "@/lib/blind";
import type { VoteStats } from "@/lib/types";
import { SectionHeader, ToggleRow } from "./primitives";

/**
 * Blind comparison and what the votes add up to: each model's win rate,
 * pairwise (a best answer wins over each other answer; "all bad" counted
 * apart), overall or for one kind of task.
 */
export default function BlindVotesSection({
  isDark,
  blind,
  onBlindChange,
  stats,
  taskType,
  onTaskTypeChange,
}: {
  isDark: boolean;
  blind: boolean;
  onBlindChange: (on: boolean) => void;
  stats: VoteStats | null;
  taskType: string;
  onTaskTypeChange: (task: string) => void;
}) {
  const rows = stats?.models ?? [];
  return (
    <Box>
      <SectionHeader label="Your votes" />
      <Stack spacing={1.5}>
        <ToggleRow
          isDark={isDark}
          label="Blind comparison"
          subtitle="Answers show as A, B, C in a shuffled order, without model names, colours or costs, until you vote."
          icon={<EyeOff width={16} height={16} />}
          checked={blind}
          onChange={() => onBlindChange(!blind)}
        />
        <Box sx={{ display: "flex", alignItems: "center", gap: 1 }}>
          <Typography sx={{ fontSize: "0.75rem", color: "text.secondary", flex: 1 }}>
            {stats ? `${stats.votes} vote${stats.votes === 1 ? "" : "s"}` : "Loading…"}
          </Typography>
          <Select
            size="small"
            value={taskType}
            onChange={(e) => onTaskTypeChange(e.target.value)}
            inputProps={{ "aria-label": "Win rates for" }}
            sx={{ fontSize: "0.75rem", minWidth: 130 }}
          >
            <MenuItem value="" sx={{ fontSize: "0.8rem" }}>
              Every task
            </MenuItem>
            {TASK_TYPES.map((t) => (
              <MenuItem key={t} value={t} sx={{ fontSize: "0.8rem" }}>
                {t}
                {stats?.task_types[t] ? ` (${stats.task_types[t]})` : ""}
              </MenuItem>
            ))}
          </Select>
        </Box>
        {rows.length > 0 ? (
          <Box
            component="table"
            data-testid="win-rates"
            sx={{ width: "100%", borderCollapse: "collapse", fontSize: "0.75rem" }}
          >
            <thead>
              <tr>
                {["Model", "Win rate", "W–L–T", "All bad"].map((h) => (
                  <Box
                    component="th"
                    key={h}
                    sx={{ textAlign: "left", fontWeight: 700, color: "text.secondary", pb: 0.5 }}
                  >
                    {h}
                  </Box>
                ))}
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => (
                <tr key={r.model}>
                  <Box component="td" title={r.model} sx={{ py: 0.25, pr: 1 }}>
                    {r.model_name}
                  </Box>
                  <Box component="td" sx={{ fontVariantNumeric: "tabular-nums" }}>
                    {r.win_rate === null ? "—" : `${Math.round(r.win_rate * 100)}%`}
                  </Box>
                  <Box component="td" sx={{ fontVariantNumeric: "tabular-nums" }}>
                    {r.wins}–{r.losses}–{r.ties}
                  </Box>
                  <Box component="td" sx={{ fontVariantNumeric: "tabular-nums" }}>
                    {r.all_bad}
                  </Box>
                </tr>
              ))}
            </tbody>
          </Box>
        ) : (
          stats && (
            <Typography sx={{ fontSize: "0.75rem", color: "text.secondary" }}>
              Vote on a turn&apos;s answers (under the compare cards) and your win rates appear here.
            </Typography>
          )
        )}
      </Stack>
    </Box>
  );
}
