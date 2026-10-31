import React from "react";
import { Box, Stack, Typography } from "@mui/material";
import type { ModelFamily } from "@/lib/api";
import { SectionHeader, StatusRow, getModelMetaFromId } from "./primitives";

/** Read-only summary: who answers next, the selection, the branch point, checkpoint count. */
export default function StatusSection({
  isDark,
  families,
  selectedModels,
  respondingModels = selectedModels,
  activeCheckpointLabel,
  messagesCount,
}: {
  isDark: boolean;
  families: ModelFamily[];
  selectedModels: string[];
  /** Who answers the next message: a clicked reply's model, or the selection. */
  respondingModels?: string[];
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
          {respondingModels.join() !== selectedModels.join() && (
            <StatusRow label="Answers next">
              <Typography variant="caption" sx={{ color: "text.primary", fontWeight: 700 }}>
                {respondingModels.map((m) => getModelMetaFromId(m, families, isDark).label).join(", ")}
              </Typography>
              <Typography variant="caption" sx={{ display: "block", color: "text.secondary" }}>
                You are continuing a reply; the branch chip above the composer switches back to every selected model.
              </Typography>
            </StatusRow>
          )}
          <StatusRow label="Selected models">
            <Box sx={{ display: "flex", flexWrap: "wrap", gap: 0.75 }}>
              {selectedModels.map((m) => {
                const meta = getModelMetaFromId(m, families, isDark);
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
                      fontSize: "0.6875rem",
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

          <StatusRow label="Continuing from">
            <Typography
              variant="caption"
              title={activeCheckpointLabel}
              sx={{
                color: "text.secondary",
                display: "-webkit-box",
                WebkitLineClamp: 2,
                WebkitBoxOrient: "vertical",
                overflow: "hidden",
                // Wrap between words; break-all in monospace split words mid-way.
                overflowWrap: "anywhere",
                wordBreak: "normal",
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
              Conversation tree
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
