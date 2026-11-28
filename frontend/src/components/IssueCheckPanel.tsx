import React from "react";
import { Box, Button, CircularProgress, Typography } from "@mui/material";
import type { IssueCheck, IssueVerdict } from "@/lib/types";

export const VERDICT_LABELS: Record<IssueVerdict, string> = {
  holds: "Holds",
  does_not_hold: "Doesn't hold",
  cant_tell: "Can't tell",
};

/**
 * Whether each problem of an issue list holds, as each checker judged it
 * against the question and the attached documents. The verdicts stand side
 * by side, never tallied: a problem they disagree on is the one to read
 * yourself, and a verdict on a problem the checker's own model raised says so.
 */
export function IssueCheckPanel({ check, modelLabel }: { check: IssueCheck; modelLabel: (id: string) => string }) {
  return (
    <Box
      component="section"
      aria-label="Does each problem hold?"
      sx={{ p: 2, borderRadius: 3, border: "1px solid", borderColor: "divider", bgcolor: "background.paper", display: "grid", gap: 1.5 }}
    >
      <Box>
        <Typography sx={{ fontWeight: 700, fontSize: "0.9rem" }}>Does each problem hold?</Typography>
        <Typography variant="caption" sx={{ color: "text.secondary", display: "block", lineHeight: 1.5 }}>
          {check.checkers.map((c) => c.model_name).join(", ")} checked every problem against the question
          {check.documents.length ? ` and ${check.documents.join(", ")}` : ""}, without knowing who raised it. Evidence to
          weigh, not a verdict: read the ones they disagree on yourself.
        </Typography>
      </Box>
      {check.issues.map((issue) => (
        <Box key={issue.number} sx={{ display: "grid", gap: 0.5 }} data-testid="checked-issue">
          <Box sx={{ display: "flex", alignItems: "baseline", gap: 1, flexWrap: "wrap" }}>
            <Typography sx={{ fontWeight: 700, fontSize: "0.85rem" }}>
              {issue.number}. {issue.problem}
            </Typography>
            {issue.disagree && (
              <Typography variant="caption" sx={{ fontWeight: 700, color: "warning.main" }}>
                Checkers disagree
              </Typography>
            )}
          </Box>
          {issue.raised_by && (
            <Typography variant="caption" sx={{ color: "text.secondary", display: "block" }}>
              Raised by {issue.raised_by}
            </Typography>
          )}
          {issue.verdicts.map((v) => (
            <Typography key={v.checker} variant="caption" sx={{ display: "block", pl: 1.5 }}>
              <Box component="span" sx={{ fontWeight: 700 }}>
                {VERDICT_LABELS[v.verdict]}
              </Box>
              <Box component="span" sx={{ color: "text.secondary" }}>
                {" "}
                · {v.checker_name}
                {v.own ? " (its own model raised it)" : ""}: {v.reason}
              </Box>
            </Typography>
          ))}
          {!issue.verdicts.length && (
            <Typography variant="caption" sx={{ color: "text.secondary", display: "block", pl: 1.5 }}>
              No verdicts
            </Typography>
          )}
        </Box>
      ))}
      {check.source_truncated && (
        <Typography variant="caption" role="note">
          The attached documents were too long to show the checkers whole.
        </Typography>
      )}
      {Object.entries(check.errors).map(([model, error]) => (
        <Typography key={model} variant="caption" role="note" sx={{ color: "text.primary" }}>
          {modelLabel(model)} couldn&apos;t check: {error}
        </Typography>
      ))}
    </Box>
  );
}

/** Under an issue list: the button that checks it and, once run, the result. */
export function IssueCheckSection({
  check,
  running,
  busy,
  onRun,
  modelLabel,
}: {
  check: IssueCheck | null;
  running: boolean;
  busy: boolean;
  onRun: () => void;
  modelLabel: (id: string) => string;
}) {
  return (
    <Box sx={{ display: "grid", gap: 1.5, mt: 1, mb: 2 }}>
      <Box>
        <Button
          variant="outlined"
          size="small"
          onClick={onRun}
          disabled={busy}
          aria-busy={running}
          title="Each model that wrote a review checks every problem against the question and its attached documents"
          startIcon={running ? <CircularProgress size={10} /> : undefined}
          sx={{ minHeight: 32 }}
        >
          {check ? "Check each problem again" : "Check each problem"}
        </Button>
      </Box>
      {check && <IssueCheckPanel check={check} modelLabel={modelLabel} />}
    </Box>
  );
}
