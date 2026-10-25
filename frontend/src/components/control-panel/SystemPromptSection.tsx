import React from "react";
import { Box, TextField, Typography } from "@mui/material";
import { MAX_SYSTEM_PROMPT_CHARS } from "@/hooks/useSystemPrompt";
import { SectionHeader } from "./primitives";

/** The person's own system prompt. Empty by default: models answer as they ship. */
export default function SystemPromptSection({
  value,
  onChange,
}: {
  value: string;
  onChange: (value: string) => void;
}) {
  const nearLimit = value.length > MAX_SYSTEM_PROMPT_CHARS * 0.9;
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
        slotProps={{ htmlInput: { "aria-label": "System prompt", maxLength: MAX_SYSTEM_PROMPT_CHARS } }}
        sx={{ "& textarea": { fontSize: "0.8125rem" } }}
      />
      <Typography variant="caption" sx={{ display: "block", mt: 0.75, color: "text.secondary" }}>
        Sent to every model before the conversation. Leave empty to use each model&apos;s default behaviour.
        {nearLimit ? ` ${value.length.toLocaleString()} / ${MAX_SYSTEM_PROMPT_CHARS.toLocaleString()} characters.` : ""}
      </Typography>
    </Box>
  );
}
