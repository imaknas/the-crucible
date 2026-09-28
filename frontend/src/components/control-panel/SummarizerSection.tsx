import React from "react";
import { Box, MenuItem, Select, Typography } from "@mui/material";
import type { ModelFamily } from "@/lib/api";
import { summarizerOptions } from "@/hooks/useSummarizerChoice";
import { SectionHeader } from "./primitives";

/**
 * Which model writes the summary once a conversation outgrows the model's
 * context budget. Automatic follows the server's default for the keys that
 * are set.
 */
export default function SummarizerSection({
  families,
  choice,
  summarizer,
  defaultSummarizer,
  onChange,
}: {
  families: ModelFamily[];
  choice: string;
  summarizer: string | null;
  defaultSummarizer: string | null;
  onChange: (modelId: string) => void;
}) {
  const options = summarizerOptions(families);
  const nameOf = (id: string | null) => options.find((m) => m.id === id)?.name ?? id ?? "";
  const unavailable = !!choice && !summarizer;
  return (
    <Box>
      <SectionHeader label="Summarizer" />
      <Select
        size="small"
        fullWidth
        value={summarizer ?? ""}
        displayEmpty
        onChange={(e) => onChange(String(e.target.value))}
        inputProps={{ "aria-label": "Summarizer model" }}
      >
        <MenuItem value="">
          <Typography variant="caption">
            Automatic{defaultSummarizer ? ` (${nameOf(defaultSummarizer)})` : ""}
          </Typography>
        </MenuItem>
        {options.map((m) => (
          <MenuItem key={m.id} value={m.id} title={m.id} aria-label={`${m.name}, ${m.family.label}`}>
            <Typography variant="caption">
              {m.name} <span style={{ opacity: 0.6 }}>· {m.family.label}</span>
            </Typography>
          </MenuItem>
        ))}
      </Select>
      <Typography variant="caption" sx={{ display: "block", mt: 0.75, color: "text.secondary" }}>
        {unavailable
          ? "The model you picked no longer has an API key, so the automatic choice is used."
          : "Writes the summary once a conversation gets too long for the model; the full history is kept either way."}
      </Typography>
    </Box>
  );
}
