import React from "react";
import { Box, Button, MenuItem, Select, TextField, Typography } from "@mui/material";
import { SIDE_MAX_CHARS, type StanceChoice } from "@/lib/stances";
import type { StanceMode } from "@/lib/types";

const HELP: Record<StanceMode, string> = {
  open: "Each model says what it thinks; round 1 is its independent answer.",
  sides:
    "Each model argues the side it is given, whatever it thinks, so you see the strongest case for every side and judge it yourself — the setup in which debate measurably helps the person judging. Holding a side, or agreeing, says nothing here.",
  advocate:
    "Everyone answers round 1 for themselves; from round 2 one participant argues against whatever the others agree on. The others aren't told which one it is.",
};

/** The debate dialog's "How they argue": open, assigned sides or a devil's advocate. */
export default function StanceSettings({
  choice,
  onChange,
  participants,
  modelLabel,
  problem,
  labelSx,
}: {
  choice: StanceChoice;
  onChange: (next: StanceChoice) => void;
  participants: string[];
  modelLabel: (id: string) => string;
  /** Why the choice can't start (lib/stances.stanceProblem), or null. */
  problem: string | null;
  labelSx: object;
}) {
  const set = (patch: Partial<StanceChoice>) => onChange({ ...choice, ...patch });
  return (
    <Box>
      <Box sx={{ display: "flex", alignItems: "center", flexWrap: "wrap", columnGap: 2, rowGap: 0.5 }}>
        <Typography sx={labelSx}>How they argue</Typography>
        <Select
          size="small"
          value={choice.mode}
          inputProps={{ "aria-label": "How they argue" }}
          SelectDisplayProps={{ "aria-describedby": "debate-stance-help" } as React.HTMLAttributes<HTMLDivElement>}
          onChange={(e) => set({ mode: e.target.value as StanceMode })}
          sx={{ fontSize: "0.8rem", minWidth: 160 }}
        >
          <MenuItem value="open">
            <Typography variant="caption">Each says what it thinks</Typography>
          </MenuItem>
          <MenuItem value="sides">
            <Typography variant="caption">Assigned sides</Typography>
          </MenuItem>
          <MenuItem value="advocate">
            <Typography variant="caption">With a devil&apos;s advocate</Typography>
          </MenuItem>
        </Select>
      </Box>
      <Typography
        id="debate-stance-help"
        variant="caption"
        sx={{ display: "block", mt: 0.25, color: "text.secondary", lineHeight: 1.4 }}
      >
        {HELP[choice.mode]}
      </Typography>

      {choice.mode === "sides" && (
        <Box sx={{ mt: 1, display: "flex", flexDirection: "column", gap: 1 }}>
          {choice.sides.map((side, i) => (
            <TextField
              key={i}
              size="small"
              label={`Side ${i + 1}`}
              value={side}
              onChange={(e) =>
                set({ sides: choice.sides.map((s, j) => (j === i ? e.target.value.slice(0, SIDE_MAX_CHARS) : s)) })
              }
              inputProps={{ "aria-label": `Side ${i + 1}` }}
              sx={{ "& input": { fontSize: "0.8rem" } }}
            />
          ))}
          {choice.sides.length < participants.length && (
            <Button
              size="small"
              sx={{ alignSelf: "flex-start", textTransform: "none" }}
              onClick={() => set({ sides: [...choice.sides, ""] })}
            >
              Add a side
            </Button>
          )}
          {participants.map((m) => (
            <Box key={m} sx={{ display: "flex", alignItems: "center", gap: 1 }}>
              <Typography variant="caption" title={m} sx={{ minWidth: 140 }}>
                {modelLabel(m)} argues
              </Typography>
              <Select
                size="small"
                value={choice.assignment[m] ?? 0}
                inputProps={{ "aria-label": `${modelLabel(m)} argues` }}
                onChange={(e) => set({ assignment: { ...choice.assignment, [m]: Number(e.target.value) } })}
                sx={{ fontSize: "0.8rem", minWidth: 160 }}
              >
                {choice.sides.map((side, i) => (
                  <MenuItem key={i} value={i}>
                    <Typography variant="caption">{side.trim() || `Side ${i + 1}`}</Typography>
                  </MenuItem>
                ))}
              </Select>
            </Box>
          ))}
        </Box>
      )}

      {choice.mode === "advocate" && (
        <Box sx={{ mt: 1, display: "flex", alignItems: "center", gap: 1 }}>
          <Typography variant="caption" sx={{ minWidth: 140 }}>
            Devil&apos;s advocate
          </Typography>
          <Select
            size="small"
            value={choice.advocate ?? ""}
            inputProps={{ "aria-label": "Devil's advocate" }}
            onChange={(e) => set({ advocate: e.target.value })}
            sx={{ fontSize: "0.8rem", minWidth: 160 }}
          >
            {participants.map((m) => (
              <MenuItem key={m} value={m} title={m}>
                <Typography variant="caption">{modelLabel(m)}</Typography>
              </MenuItem>
            ))}
          </Select>
        </Box>
      )}

      {problem && (
        <Typography
          role="status"
          variant="caption"
          sx={{ display: "block", mt: 0.5, pl: 1, borderLeft: "2px solid", borderColor: "warning.main" }}
        >
          {problem}
        </Typography>
      )}
    </Box>
  );
}
