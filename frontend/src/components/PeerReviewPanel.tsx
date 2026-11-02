import React from "react";
import { Box, Typography } from "@mui/material";
import type { AnswerReview } from "@/lib/types";

/**
 * How the models scored each other's answers: each scored the others,
 * anonymously and never its own. Shown as evidence beside the answers,
 * never as a verdict, so the copy names what was measured and nothing more.
 */
export default function PeerReviewPanel({
  review,
  modelLabel,
}: {
  review: AnswerReview;
  modelLabel: (id: string) => string;
}) {
  const answers = [...review.answers].sort((a, b) => (b.average ?? -1) - (a.average ?? -1));
  return (
    <Box
      component="section"
      aria-label="How the models scored each other's answers"
      sx={{ p: 2, borderRadius: 3, border: "1px solid", borderColor: "divider", bgcolor: "background.paper", display: "grid", gap: 1.5 }}
    >
      <Box>
        <Typography sx={{ fontWeight: 700, fontSize: "0.9rem" }}>How the models scored each other&apos;s answers</Typography>
        <Typography variant="caption" sx={{ color: "text.secondary", display: "block", lineHeight: 1.5 }}>
          Each model scored the other answers from 1 to 10, without knowing who wrote them and never its own. Evidence to
          weigh, not a verdict.
        </Typography>
      </Box>
      {answers.map((a) => (
        <Box key={a.checkpoint_id} sx={{ display: "grid", gap: 0.5 }}>
          <Box sx={{ display: "flex", alignItems: "baseline", gap: 1, flexWrap: "wrap" }}>
            <Typography sx={{ fontWeight: 700, fontSize: "0.85rem" }} title={a.model}>
              {a.model_name}
            </Typography>
            <Typography sx={{ fontSize: "0.85rem", fontVariantNumeric: "tabular-nums" }}>
              {a.average != null ? `${a.average.toFixed(1)} / 10` : "not scored"}
            </Typography>
            <Typography variant="caption" sx={{ color: "text.secondary" }}>
              {a.scores.length} {a.scores.length === 1 ? "review" : "reviews"}
            </Typography>
          </Box>
          {a.scores.map((s) => (
            <Typography key={s.reviewer} variant="caption" sx={{ color: "text.secondary", display: "block", pl: 1.5 }}>
              {s.reviewer_name}: {s.score} — {s.reason}
            </Typography>
          ))}
        </Box>
      ))}
      {Object.entries(review.errors).map(([model, error]) => (
        <Typography key={model} variant="caption" role="note" sx={{ color: "text.primary" }}>
          {modelLabel(model)} couldn&apos;t review: {error}
        </Typography>
      ))}
    </Box>
  );
}
