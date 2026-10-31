"use client";

import React from "react";
import { Dialog, DialogTitle, DialogContent, DialogActions, Button, Typography } from "@mui/material";
import { MessageBody } from "@/components/MessageBubble";
import { useThemeMode } from "@/components/ThemeRegistry";
import { debateReplyTitle } from "@/lib/debateTranscript";
import type { DebateLane, Message, TreeNode } from "@/lib/types";

/**
 * One debate reply in full, opened from its tree node, which shows a
 * 400-character excerpt at most. The text is the transcript's, rendered as
 * the transcript renders it; the tree stays where it was underneath.
 */
export default function DebateReplyDialog({
  reading,
  lanes,
  onClose,
}: {
  reading: { node: TreeNode; reply: Message | null } | null;
  lanes?: DebateLane[];
  onClose: () => void;
}) {
  const { isDark } = useThemeMode();
  if (!reading) return null;
  const { node, reply } = reading;
  return (
    <Dialog open onClose={onClose} maxWidth="md" fullWidth scroll="paper" aria-labelledby="debate-reply-title">
      <DialogTitle id="debate-reply-title" sx={{ fontSize: "1rem", fontWeight: 700 }}>
        {debateReplyTitle(node, lanes)}
      </DialogTitle>
      <DialogContent dividers>
        {reply ? (
          <MessageBody msg={reply} isDark={isDark} />
        ) : (
          <>
            <Typography variant="body2" sx={{ whiteSpace: "pre-wrap", mb: 2 }}>
              {node.metadata?.preview || node.data.label}
            </Typography>
            <Typography variant="caption" color="text.secondary">
              This is an excerpt: the full reply shows once the transcript has loaded.
            </Typography>
          </>
        )}
      </DialogContent>
      <DialogActions>
        <Button onClick={onClose}>Close</Button>
      </DialogActions>
    </Dialog>
  );
}
