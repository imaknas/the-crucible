import React from "react";
import { Box, TextField, Typography } from "@mui/material";
import { SectionHeader } from "./primitives";

/** The person's own system prompt. Empty by default: models answer as they ship. */
export default function SystemPromptSection({
  value,
  onChange,
  maxChars,
}: {
  value: string;
  onChange: (value: string) => void;
  /** The backend's limit (GET /models `limits.max_system_prompt_chars`). */
  maxChars: number;
}) {
  const nearLimit = value.length > maxChars * 0.9;
  return (
    <Box>
      <SectionHeader label="System prompt" />
      <TextField
        multiline
        fullWidth
        size="small"
        minRows={3}
        maxRows={10}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        placeholder="None"
        slotProps={{ htmlInput: { "aria-label": "System prompt", maxLength: maxChars } }}
        sx={{ "& textarea": { fontSize: "0.8125rem" } }}
      />
      <Typography variant="caption" sx={{ display: "block", mt: 0.75, color: "text.secondary" }}>
        Sent to every model before the conversation. Leave empty to use each model&apos;s default behaviour.
        {nearLimit ? ` ${value.length.toLocaleString()} / ${maxChars.toLocaleString()} characters.` : ""}
      </Typography>
    </Box>
  );
}
