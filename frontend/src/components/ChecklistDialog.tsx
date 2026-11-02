import React from "react";
import {
  Box,
  Button,
  Checkbox,
  CircularProgress,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  FormControlLabel,
  Typography,
} from "@mui/material";
import * as api from "@/lib/api";
import { errorMessage } from "@/lib/errors";

/**
 * Step one of a checklist synthesis: the answers split into parts, each
 * naming the answers that contain it; the person keeps what they want and
 * only those parts are merged. Splitting writes nothing to the thread.
 */
export default function ChecklistDialog({
  open,
  threadId,
  ids,
  model,
  onClose,
  onMerge,
}: {
  open: boolean;
  threadId: string | null;
  ids: string[];
  model: string | null;
  onClose: () => void;
  onMerge: (keep: string[]) => void;
}) {
  const [parts, setParts] = React.useState<{ text: string; sources: string[] }[] | null>(null);
  const [kept, setKept] = React.useState<Set<number>>(new Set());
  const [error, setError] = React.useState<string | null>(null);

  React.useEffect(() => {
    if (!open || !threadId) return;
    let live = true;
    // Mounted fresh for each checklist (the page keys it), so nothing to reset here.
    api
      .listAnswerComponents(threadId, ids, model)
      .then((found) => {
        if (!live) return;
        setParts(found);
        setKept(new Set(found.map((_, i) => i)));
      })
      .catch((e) => live && setError(errorMessage(e, "Couldn't split the answers into parts")));
    return () => {
      live = false;
    };
  }, [open, threadId, ids, model]);

  const toggle = (i: number) =>
    setKept((prev) => {
      const next = new Set(prev);
      if (next.has(i)) next.delete(i);
      else next.add(i);
      return next;
    });

  return (
    <Dialog open={open} onClose={onClose} fullWidth maxWidth="sm" aria-labelledby="checklist-title">
      <DialogTitle id="checklist-title">Pick the parts to keep</DialogTitle>
      <DialogContent>
        <Typography variant="body2" sx={{ color: "text.secondary", mb: 2 }}>
          The answers split into separate claims, steps and caveats. Untick what you don&apos;t want; the rest is merged into
          one answer.
        </Typography>
        {!parts && !error && (
          <Box role="status" sx={{ display: "flex", alignItems: "center", gap: 1.5, py: 2 }}>
            <CircularProgress size={16} />
            <Typography variant="body2">Splitting the answers into parts…</Typography>
          </Box>
        )}
        {error && (
          <Typography role="alert" variant="body2" sx={{ color: "error.main" }}>
            {error}
          </Typography>
        )}
        {parts && (
          <Box sx={{ display: "grid", gap: 0.5 }}>
            {parts.map((part, i) => (
              <FormControlLabel
                key={i}
                control={<Checkbox checked={kept.has(i)} onChange={() => toggle(i)} />}
                label={
                  <Box>
                    <Typography variant="body2">{part.text}</Typography>
                    {part.sources.length > 0 && (
                      <Typography variant="caption" sx={{ color: "text.secondary" }}>
                        In: {part.sources.join(", ")}
                      </Typography>
                    )}
                  </Box>
                }
                sx={{ alignItems: "flex-start", "& .MuiCheckbox-root": { pt: 0.5 } }}
              />
            ))}
          </Box>
        )}
      </DialogContent>
      <DialogActions>
        <Button onClick={onClose}>Cancel</Button>
        <Button
          variant="contained"
          disabled={!parts || kept.size === 0}
          onClick={() => parts && onMerge(parts.filter((_, i) => kept.has(i)).map((p) => p.text))}
        >
          {`Merge ${kept.size} ${kept.size === 1 ? "part" : "parts"}`}
        </Button>
      </DialogActions>
    </Dialog>
  );
}
