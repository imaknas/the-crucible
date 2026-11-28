import React from "react";
import { Box, MenuItem, Select, Typography } from "@mui/material";
import type { ModelFamily } from "@/lib/api";
import { EFFORT_LABELS, effortGaps } from "@/lib/effort";
import { SectionHeader } from "./primitives";

/**
 * How hard the answering models reason (persisted; "" = each model's
 * default). Each model takes only some levels, so the section names the
 * selected models that won't get the choice and answer at their default.
 */
export default function ReasoningEffortSection({
  choice,
  choices,
  families,
  models,
  onChange,
}: {
  choice: string;
  /** GET /models `reasoning_efforts`, lowest first. */
  choices: string[];
  families: ModelFamily[];
  /** Who answers: the models whose levels matter. */
  models: string[];
  onChange: (choice: string) => void;
}) {
  const info = families.flatMap((f) => f.models).filter((m) => models.includes(m.id));
  const { unverified, lacking } = effortGaps(choice, info);
  return (
    <Box>
      <SectionHeader label="Reasoning effort" />
      <Select
        size="small"
        fullWidth
        value={choice}
        displayEmpty
        onChange={(e) => onChange(String(e.target.value))}
        inputProps={{ "aria-label": "Reasoning effort" }}
      >
        <MenuItem value="">
          <Typography variant="caption">Each model&apos;s default</Typography>
        </MenuItem>
        {choices.map((c) => (
          <MenuItem key={c} value={c}>
            <Typography variant="caption">
              {EFFORT_LABELS[c] ?? c}
              {c === "max" ? " (each model's highest)" : ""}
            </Typography>
          </MenuItem>
        ))}
      </Select>
      <Typography variant="caption" sx={{ display: "block", mt: 0.75, color: "text.secondary" }} data-testid="effort-note">
        {!choice
          ? "Higher effort can help with hard questions; it takes longer and costs more (reasoning is billed as output)."
          : [
              lacking.length ? `${lacking.join(", ")} ${lacking.length === 1 ? "has" : "have"} no such level` : null,
              unverified.length
                ? `${unverified.join(", ")}: levels not verified yet (catalog-sync --probe effort)`
                : null,
            ]
              .filter(Boolean)
              .join("; ") +
            (lacking.length || unverified.length
              ? "; they answer at their default, and the turn says so."
              : "Every model answering takes this level.")}
      </Typography>
    </Box>
  );
}
