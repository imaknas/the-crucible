import React from "react";
import { Box, ButtonBase, Typography } from "@mui/material";
import type { Message } from "@/lib/types";
import type { PeerLegendEntry, PositionShift } from "@/lib/debateTranscript";
import { roundLabel } from "@/lib/debateTranscript";
import { MessageBody } from "./MessageBubble";

/**
 * Each participant's Round 1 answer next to its latest one, shown beside the
 * argument map (lib/debateTranscript.positionShifts). The map says who
 * changed and why; this shows the answers it is about, unparaphrased.
 */
export default function PositionShiftPanel({
  shift,
  legend = [],
  modelLabel,
  isDark,
}: {
  shift: { startRound: number; endRound: number; rows: PositionShift[] };
  legend?: PeerLegendEntry[];
  modelLabel: (id: string) => string;
  isDark: boolean;
}) {
  const [open, setOpen] = React.useState(false);
  const peer = (model: string) => legend.find((l) => l.modelId === model)?.label;
  const first = roundLabel(shift.startRound, "short");
  return (
    <Box
      component="section"
      aria-label="Where each participant started and ended"
      sx={{ my: 2, p: 2, borderRadius: 3, border: "1px solid", borderColor: "divider", bgcolor: "background.paper" }}
    >
      <Box sx={{ display: "flex", alignItems: "baseline", justifyContent: "space-between", gap: 2, flexWrap: "wrap", mb: 1.5 }}>
        <Box>
          <Typography sx={{ fontWeight: 700, fontSize: "0.95rem" }}>Where each participant started and ended</Typography>
          <Typography variant="caption" sx={{ color: "text.secondary", display: "block", lineHeight: 1.5 }}>
            {first} is each answer before seeing the others. Most of what a debate knows is already there; later rounds can
            drift toward agreement without new evidence.
          </Typography>
        </Box>
        <ButtonBase
          onClick={() => setOpen((v) => !v)}
          aria-expanded={open}
          sx={{ fontSize: "0.8rem", fontWeight: 600, color: "primary.main", px: 1, py: 0.5, borderRadius: 1.5 }}
        >
          {open ? "Show excerpts" : "Show both in full"}
        </ButtonBase>
      </Box>
      <Box sx={{ display: "grid", gap: 1.5 }}>
        {shift.rows.map((row) => (
          <Box
            key={row.model}
            sx={{ display: "grid", gap: 0.75, pt: 1.5, borderTop: "1px solid", borderColor: "divider", "&:first-of-type": { borderTop: "none", pt: 0 } }}
          >
            <Typography sx={{ fontWeight: 700, fontSize: "0.85rem" }} title={row.model}>
              {modelLabel(row.model)}
              {peer(row.model) && (
                <Box component="span" sx={{ fontWeight: 500, color: "text.secondary", ml: 1 }}>
                  {peer(row.model)}
                </Box>
              )}
            </Typography>
            <Box sx={{ display: "grid", gridTemplateColumns: { xs: "1fr", md: "1fr 1fr" }, gap: 1.5 }}>
              <Answer heading={first} msg={row.first} open={open} isDark={isDark} />
              {row.last ? (
                <Answer heading={roundLabel(row.last.round ?? shift.endRound)} msg={row.last} open={open} isDark={isDark} />
              ) : (
                <Typography variant="caption" sx={{ color: "text.secondary" }}>
                  No later answer: it failed in the rounds after {first}.
                </Typography>
              )}
            </Box>
          </Box>
        ))}
      </Box>
    </Box>
  );
}

function Answer({ heading, msg, open, isDark }: { heading: string; msg: Message; open: boolean; isDark: boolean }) {
  return (
    <Box sx={{ minWidth: 0 }}>
      <Typography
        variant="overline"
        sx={{ display: "block", fontSize: "0.6875rem", fontWeight: 700, letterSpacing: "0.08em", color: "text.secondary", lineHeight: 1.6 }}
      >
        {heading}
      </Typography>
      <Box
        sx={
          open
            ? undefined
            : { maxHeight: "9.5em", overflow: "hidden", maskImage: "linear-gradient(to bottom, black 70%, transparent)" }
        }
      >
        <MessageBody msg={msg} isDark={isDark} compact />
      </Box>
    </Box>
  );
}
