import React, { useState } from "react";
import { Box, ButtonBase, Typography } from "@mui/material";
import { ChevronDown, History } from "lucide-react";
import { replyContextNote, type ReplyContext } from "@/lib/context";
import { RADIUS } from "@/theme";

/**
 * Under a reply written from a summary, or with excerpts recall brought
 * back: says so, and lists the excerpts. Nothing for a reply that saw the
 * whole history.
 */
export function ReplyContextNote({
  context,
  modelLabel,
}: {
  context?: ReplyContext | null;
  modelLabel: (id: string) => string;
}) {
  const [open, setOpen] = useState(false);
  const note = replyContextNote(context);
  if (!note || !context) return null;
  const recalled = context.recalled ?? [];
  return (
    <Box data-testid="reply-context">
      <ButtonBase
        onClick={() => setOpen((o) => !o)}
        disabled={!recalled.length}
        aria-expanded={recalled.length ? open : undefined}
        sx={{
          display: "flex",
          alignItems: "flex-start",
          gap: 0.5,
          fontSize: "0.6875rem",
          lineHeight: 1.5,
          fontWeight: 500,
          color: "text.secondary",
          textAlign: "left",
          borderRadius: `${RADIUS.sm}px`,
          "&.Mui-disabled": { color: "text.secondary" },
        }}
      >
        <History width={11} height={11} aria-hidden style={{ flexShrink: 0, marginTop: 3 }} />
        {note}
        {recalled.length > 0 && (
          <ChevronDown
            width={11}
            height={11}
            aria-hidden
            style={{
              flexShrink: 0,
              marginTop: 3,
              transform: open ? "rotate(180deg)" : undefined,
            }}
          />
        )}
      </ButtonBase>
      {open && (
        <Box component="ul" sx={{ m: 0, mt: 0.75, pl: 2.5 }}>
          {recalled.map((r, i) => (
            <Typography component="li" key={i} sx={{ fontSize: "0.75rem", color: "text.secondary", mb: 0.5 }}>
              <Box component="span" sx={{ fontWeight: 700 }}>
                {r.role === "user" ? "You" : r.author ? modelLabel(r.author) : "Assistant"}:
              </Box>{" "}
              {r.excerpt}
            </Typography>
          ))}
        </Box>
      )}
    </Box>
  );
}
