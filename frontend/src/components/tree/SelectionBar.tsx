import React from "react";
import { Box, ButtonBase, Typography } from "@mui/material";
import { SYNTHESIS_MODES, type SynthesisMode, type SynthesisRequest } from "@/lib/synthesis";

/**
 * Answers picked on the tree (Shift/Cmd-click or a node's Pick), from any
 * branches, and what to do with them: merge, compare, keep parts, or ask a
 * question about them. Picking never moves the branch point.
 */
export default function SelectionBar({
  count,
  onRun,
  onClear,
}: {
  count: number;
  onRun: (request: SynthesisRequest) => void;
  onClear: () => void;
}) {
  const [asking, setAsking] = React.useState(false);
  const [question, setQuestion] = React.useState("");
  const ready = count >= 2;
  const run = (mode: SynthesisMode) => {
    if (mode === "ask") {
      setAsking(true);
      return;
    }
    onRun({ mode });
  };
  return (
    <Box
      role="toolbar"
      aria-label="Picked answers"
      sx={{
        // Top centre: the zoom controls and minimap own the bottom corners,
        // and the newest answers (the ones people pick) grow downwards.
        position: "absolute",
        left: "50%",
        top: 12,
        transform: "translateX(-50%)",
        zIndex: 20,
        maxWidth: "calc(100% - 32px)",
        display: "flex",
        flexWrap: "wrap",
        alignItems: "center",
        gap: 0.75,
        px: 1.5,
        py: 0.75,
        borderRadius: 3,
        bgcolor: "background.paper",
        border: "1px solid",
        borderColor: "divider",
        boxShadow: "0 8px 24px -8px rgba(0,0,0,0.25)",
      }}
    >
      <Typography sx={{ fontSize: "0.8rem", fontWeight: 700 }}>
        {count} {count === 1 ? "answer" : "answers"} picked
      </Typography>
      {!ready && (
        <Typography sx={{ fontSize: "0.75rem", color: "text.secondary" }}>
          Shift-click or Pick another to combine.
        </Typography>
      )}
      {ready &&
        !asking &&
        SYNTHESIS_MODES.map((m) => (
          <ButtonBase
            key={m.mode}
            onClick={() => run(m.mode)}
            title={m.description}
            sx={{ px: 1.25, py: 0.5, borderRadius: 2, border: "1px solid", borderColor: "divider", fontSize: "0.78rem", fontWeight: 600 }}
          >
            {m.action}
          </ButtonBase>
        ))}
      {ready && asking && (
        <Box
          component="form"
          onSubmit={(e: React.FormEvent) => {
            e.preventDefault();
            if (question.trim()) onRun({ mode: "ask", question: question.trim() });
          }}
          sx={{ display: "flex", gap: 1, alignItems: "center" }}
        >
          <Box
            component="input"
            autoFocus
            aria-label="Your question about the picked answers"
            placeholder="Your question about these answers"
            value={question}
            onChange={(e: React.ChangeEvent<HTMLInputElement>) => setQuestion(e.target.value)}
            sx={{ minWidth: 240, px: 1.25, py: 0.5, borderRadius: 2, border: "1px solid", borderColor: "divider", bgcolor: "transparent", color: "text.primary", fontSize: "0.8rem" }}
          />
          <ButtonBase
            type="submit"
            disabled={!question.trim()}
            sx={{ px: 1.25, py: 0.5, borderRadius: 2, bgcolor: "primary.main", color: "primary.contrastText", fontSize: "0.78rem", fontWeight: 700, "&.Mui-disabled": { opacity: 0.5 } }}
          >
            Ask
          </ButtonBase>
        </Box>
      )}
      <ButtonBase onClick={onClear} sx={{ px: 1, py: 0.5, borderRadius: 2, fontSize: "0.78rem", color: "text.secondary" }}>
        Clear
      </ButtonBase>
    </Box>
  );
}
