import React, { useState } from "react";
import { Box, ButtonBase, Typography } from "@mui/material";
import { ChevronDown, Layers } from "lucide-react";
import type { Message } from "@/lib/types";
import { RADIUS } from "@/theme";
import { MessageBody } from "./MessageBubble";

/**
 * Where the history was summarized. Replies after it were written from the
 * summary and the latest messages, not from everything above it; the
 * summary itself opens below the marker.
 */
export default function SummaryMarker({ msg, isDark }: { msg: Message; isDark: boolean }) {
  const [open, setOpen] = useState(false);
  return (
    <Box data-testid="summary-marker" sx={{ my: 2 }}>
      <Box sx={{ display: "flex", alignItems: "center", gap: 1.5 }}>
        <Box sx={{ flex: 1, borderTop: "1px dashed", borderColor: "divider" }} />
        <ButtonBase
          onClick={() => setOpen((o) => !o)}
          aria-expanded={open}
          sx={{
            display: "flex",
            alignItems: "center",
            gap: 0.75,
            px: 1.25,
            py: 0.5,
            borderRadius: `${RADIUS.sm}px`,
            fontSize: "0.75rem",
            fontWeight: 600,
            color: "text.secondary",
            "&:hover": { bgcolor: "action.hover" },
          }}
        >
          <Layers width={13} height={13} aria-hidden />
          Earlier messages summarized
          <ChevronDown
            width={13}
            height={13}
            aria-hidden
            style={{
              transform: open ? "rotate(180deg)" : undefined,
              transition: "transform 0.15s",
            }}
          />
        </ButtonBase>
        <Box sx={{ flex: 1, borderTop: "1px dashed", borderColor: "divider" }} />
      </Box>
      {open && (
        <Box
          sx={{
            mt: 1.5,
            px: 2,
            py: 1.5,
            borderRadius: `${RADIUS.lg}px`,
            border: "1px dashed",
            borderColor: "divider",
            bgcolor: "action.hover",
          }}
        >
          <Typography sx={{ fontSize: "0.75rem", color: "text.secondary", mb: 1 }}>
            Replies after this point were written from this summary and the latest messages, not from the whole history
            above.
          </Typography>
          <MessageBody msg={msg} isDark={isDark} compact />
        </Box>
      )}
    </Box>
  );
}
