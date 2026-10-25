import React from "react";
import { Box, Button, IconButton, Paper, Typography } from "@mui/material";
import { AlertTriangle, RotateCcw, X } from "lucide-react";
import type { ModelError } from "@/lib/types";

/**
 * One model's failed turn, in line with the replies that did arrive: who
 * failed, the error text, and a Retry that asks that model again from the
 * same parent. Replaces the blocking modal per failed model.
 */
export default function ModelErrorBubble({
  error,
  label,
  onRetry,
  onDismiss,
  retryDisabled,
}: {
  error: ModelError;
  label: string;
  onRetry: (id: string) => void;
  onDismiss: (id: string) => void;
  retryDisabled?: boolean;
}) {
  return (
    <Paper
      role="alert"
      data-testid="model-error"
      sx={{
        p: 2.5,
        borderRadius: 2.5,
        border: "1px solid",
        borderColor: "error.main",
        bgcolor: (t) => (t.palette.mode === "dark" ? "rgba(239,68,68,0.08)" : "rgba(239,68,68,0.04)"),
      }}
    >
      <Box sx={{ display: "flex", alignItems: "center", gap: 1, mb: 1, color: "error.main" }}>
        <AlertTriangle width={14} height={14} />
        <Typography
          variant="overline"
          title={error.model}
          sx={{ fontSize: "0.7rem", fontWeight: 800, letterSpacing: "0.15em", lineHeight: 1, flex: 1 }}
        >
          {label} didn&apos;t answer
        </Typography>
        <IconButton size="small" aria-label={`Dismiss ${label} error`} onClick={() => onDismiss(error.id)}>
          <X width={14} height={14} />
        </IconButton>
      </Box>
      <Typography
        component="pre"
        sx={{
          fontFamily: "monospace",
          fontSize: "0.8125rem",
          whiteSpace: "pre-wrap",
          wordBreak: "break-word",
          color: "text.secondary",
          m: 0,
          mb: 1.5,
          maxHeight: 160,
          overflow: "auto",
        }}
      >
        {error.message}
      </Typography>
      <Button
        size="small"
        variant="outlined"
        color="error"
        startIcon={<RotateCcw width={14} height={14} />}
        onClick={() => onRetry(error.id)}
        disabled={retryDisabled}
        sx={{ textTransform: "none", fontWeight: 700 }}
      >
        Retry {label}
      </Button>
    </Paper>
  );
}
