import React from "react";
import { Box, Stack, Typography } from "@mui/material";
import type { ModelFamily } from "@/lib/api";
import { SectionHeader, StatusRow, getModelMetaFromId } from "./primitives";

/** Read-only summary: selected models, open checkpoint, checkpoint count. */
export default function StatusSection({
  isDark,
  families,
  selectedModels,
  activeCheckpointLabel,
  messagesCount,
}: {
  isDark: boolean;
  families: ModelFamily[];
  selectedModels: string[];
  activeCheckpointLabel: string;
  messagesCount: number;
}) {
  return (
    <Box>
      <SectionHeader label="Status" />
      <Box
        sx={{
          p: 2.5,
          borderRadius: 2.5,
          border: "1px solid",
          borderColor: "divider",
          bgcolor: isDark ? "rgba(255,255,255,0.02)" : "rgba(0,0,0,0.02)",
        }}
      >
        <Stack spacing={2}>
          <StatusRow label="Models in this arena">
            <Box sx={{ display: "flex", flexWrap: "wrap", gap: 0.75 }}>
              {selectedModels.map((m) => {
                const meta = getModelMetaFromId(m, families);
                return (
                  <Box
                    key={m}
                    sx={{
                      display: "flex",
                      alignItems: "center",
                      gap: 0.75,
                      px: 1,
                      py: 0.25,
                      borderRadius: 1.5,
                      fontSize: "0.65rem",
                      fontWeight: 700,
                      letterSpacing: "0.05em",
                      textTransform: "uppercase",
                      border: `1px solid ${meta.activeBorder}`,
                      bgcolor: meta.activeBg,
                      color: meta.color,
                      maxWidth: "100%",
                      overflow: "hidden",
                      textOverflow: "ellipsis",
                      whiteSpace: "nowrap",
                    }}
                  >
                    <Box
                      sx={{
                        width: 5,
                        height: 5,
                        borderRadius: "50%",
                        bgcolor: meta.dotColor,
                        flexShrink: 0,
                      }}
                    />
                    {meta.label}
                  </Box>
                );
              })}
            </Box>
          </StatusRow>

          <StatusRow label="Checkpoint">
            <Typography
              variant="caption"
              sx={{
                fontFamily: "monospace",
                color: "text.secondary",
                display: "block",
                wordBreak: "break-all",
                lineHeight: 1.4,
              }}
            >
              {activeCheckpointLabel || "init"}
            </Typography>
          </StatusRow>

          <Box
            sx={{
              display: "flex",
              justifyContent: "space-between",
              alignItems: "center",
              pt: 1.5,
              borderTop: "1px solid",
              borderColor: "divider",
            }}
          >
            <Typography
              variant="overline"
              sx={{
                fontSize: "0.7rem",
                fontWeight: 700,
                letterSpacing: "0.1em",
                color: "text.secondary",
              }}
            >
              Checkpoints
            </Typography>
            <Box
              sx={{
                px: 1.5,
                py: 0.25,
                borderRadius: 8,
                fontSize: "0.75rem",
                fontWeight: 700,
                bgcolor: isDark
                  ? "rgba(255,255,255,0.08)"
                  : "rgba(0,0,0,0.05)",
                color: "text.secondary",
              }}
            >
              {messagesCount} nodes
            </Box>
          </Box>
        </Stack>
      </Box>
    </Box>
  );
}
