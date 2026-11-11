"use client";

import React from "react";
import {
  Box,
  Button,
  ButtonBase,
  CircularProgress,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  Typography,
  useMediaQuery,
} from "@mui/material";
import { alpha, useTheme, type Theme } from "@mui/material/styles";
import {
  diffAnswers,
  diffSummaryText,
  type DiffRow,
  type DiffSide,
  type Segment,
} from "@/lib/diff";

/**
 * What differs between two answers (lib/diff): side by side from `md` up,
 * stacked below. Marks never rely on colour alone: A's side carries a `−`
 * gutter and struck-through removed words, B's a `+` gutter and underlined
 * added words, and screen readers hear which answer each line is from.
 */

/**
 * Read by screen readers, not shown. Sizes are strings: in `sx` a number up to
 * 1 is a fraction, so `height: 1` made each label as tall as the transcript
 * around it and left thousands of blank pixels below a debate's diff.
 */
const visuallyHidden = {
  position: "absolute",
  width: "1px",
  height: "1px",
  overflow: "hidden",
  clip: "rect(0 0 0 0)",
  whiteSpace: "nowrap",
  border: 0,
  p: 0,
  m: -0.25,
} as const;

const removedBg = (t: Theme) =>
  alpha(t.palette.error.main, t.palette.mode === "dark" ? 0.28 : 0.14);
const addedBg = (t: Theme) =>
  alpha(t.palette.success.main, t.palette.mode === "dark" ? 0.28 : 0.16);
const onlyABg = (t: Theme) =>
  alpha(t.palette.error.main, t.palette.mode === "dark" ? 0.1 : 0.05);
const onlyBBg = (t: Theme) =>
  alpha(t.palette.success.main, t.palette.mode === "dark" ? 0.1 : 0.06);

function Words({ segments, side }: { segments: Segment[]; side: "a" | "b" }) {
  return (
    <>
      {segments.map((s, i) => {
        if (s.op === "same")
          return <React.Fragment key={i}>{s.text}</React.Fragment>;
        if (side === "a" && s.op === "removed")
          return (
            <Box
              key={i}
              component="del"
              sx={{
                bgcolor: removedBg,
                textDecorationLine: "line-through",
                textDecorationThickness: "2px",
                textDecorationColor: (t) => t.palette.error.main,
                borderRadius: 0.5,
                color: "inherit",
              }}
            >
              {s.text}
            </Box>
          );
        if (side === "b" && s.op === "added")
          return (
            <Box
              key={i}
              component="ins"
              sx={{
                bgcolor: addedBg,
                textDecorationLine: "underline",
                textDecorationThickness: "2px",
                textUnderlineOffset: "3px",
                textDecorationColor: (t) => t.palette.success.main,
                borderRadius: 0.5,
                color: "inherit",
              }}
            >
              {s.text}
            </Box>
          );
        return null;
      })}
    </>
  );
}

function Cell({
  side,
  row,
  children,
  spoken,
}: {
  side: "a" | "b" | "both";
  row: DiffRow;
  children: React.ReactNode;
  spoken: string;
}) {
  const code = row.kind !== "sentence";
  const gutter = side === "a" ? "−" : side === "b" ? "+" : "";
  return (
    <Box
      data-side={side}
      data-op={row.op}
      sx={{
        display: "flex",
        gap: 1,
        minWidth: 0,
        px: 1,
        py: 0.5,
        borderRadius: 1.5,
        gridColumn: side === "both" ? "1 / -1" : undefined,
        bgcolor:
          row.op === "only_a"
            ? onlyABg
            : row.op === "only_b"
              ? onlyBBg
              : undefined,
        color: row.op === "same" ? "text.secondary" : "text.primary",
      }}
    >
      <Box
        component="span"
        aria-hidden
        sx={{
          flexShrink: 0,
          width: "1ch",
          fontWeight: 800,
          fontFamily: "ui-monospace, SFMono-Regular, Menlo, monospace",
          color: side === "a" ? "error.main" : "success.main",
        }}
      >
        {gutter}
      </Box>
      <Typography
        component="span"
        variant="body2"
        sx={{
          minWidth: 0,
          fontSize: code ? "0.8125rem" : "0.875rem",
          lineHeight: 1.6,
          whiteSpace: code ? "pre-wrap" : "normal",
          overflowWrap: "anywhere",
          fontFamily: code
            ? "ui-monospace, SFMono-Regular, Menlo, monospace"
            : undefined,
        }}
      >
        <Box component="span" sx={visuallyHidden}>
          {spoken}
        </Box>
        {children}
      </Typography>
    </Box>
  );
}

/** An empty grid cell beside a line only one answer has (side by side only). */
const Gap = () => (
  <Box aria-hidden sx={{ display: { xs: "none", md: "block" } }} />
);

function Row({ row }: { row: DiffRow }) {
  switch (row.op) {
    case "same":
      return (
        <Cell side="both" row={row} spoken="In both: ">
          {row.text}
        </Cell>
      );
    case "only_a":
      return (
        <>
          <Cell side="a" row={row} spoken="Only in A: ">
            {row.text}
          </Cell>
          <Gap />
        </>
      );
    case "only_b":
      return (
        <>
          <Gap />
          <Cell side="b" row={row} spoken="Only in B: ">
            {row.text}
          </Cell>
        </>
      );
    case "changed":
      return (
        <>
          <Cell side="a" row={row} spoken="Changed, A: ">
            <Words segments={row.segments} side="a" />
          </Cell>
          <Cell side="b" row={row} spoken="Changed, B: ">
            <Words segments={row.segments} side="b" />
          </Cell>
        </>
      );
  }
}

/** One run of rows both answers share, collapsed to a count while unchanged lines are hidden. */
function SameRun({ count }: { count: number }) {
  return (
    <Typography
      variant="caption"
      sx={{
        gridColumn: "1 / -1",
        color: "text.secondary",
        px: 1,
        py: 0.25,
        fontStyle: "italic",
      }}
    >
      … {count} the same
    </Typography>
  );
}

export function DiffView({ a, b }: { a: DiffSide; b: DiffSide }) {
  const diff = React.useMemo(
    () => diffAnswers(a.text, b.text),
    [a.text, b.text],
  );
  const [hideSame, setHideSame] = React.useState(false);
  const sameCount = diff.rows.filter((r) => r.op === "same").length;

  const body: React.ReactNode[] = [];
  let run = 0;
  diff.rows.forEach((row, i) => {
    if (hideSame && row.op === "same") {
      run++;
      return;
    }
    if (run) body.push(<SameRun key={`run-${i}`} count={run} />);
    run = 0;
    body.push(<Row key={i} row={row} />);
  });
  if (run) body.push(<SameRun key="run-end" count={run} />);

  return (
    <Box sx={{ display: "grid", gap: 1.5, minWidth: 0 }}>
      <Box
        sx={{
          display: "flex",
          flexWrap: "wrap",
          alignItems: "center",
          justifyContent: "space-between",
          gap: 1,
        }}
      >
        <Typography
          data-testid="diff-summary"
          sx={{ fontWeight: 700, fontSize: "0.875rem" }}
        >
          {diffSummaryText(diff.summary)}
        </Typography>
        {sameCount > 0 && !diff.identical && (
          <ButtonBase
            onClick={() => setHideSame((v) => !v)}
            aria-pressed={hideSame}
            sx={{
              fontSize: "0.8rem",
              fontWeight: 600,
              color: "primary.main",
              px: 1,
              py: 0.5,
              borderRadius: 1.5,
            }}
          >
            Hide unchanged
          </ButtonBase>
        )}
      </Box>
      <Box
        sx={{
          display: "grid",
          gridTemplateColumns: {
            xs: "minmax(0, 1fr)",
            md: "repeat(2, minmax(0, 1fr))",
          },
          columnGap: 1.5,
          rowGap: 0.5,
        }}
      >
        <Legend side="a" label={a.label} model={a.model} />
        <Legend side="b" label={b.label} model={b.model} />
        {body}
      </Box>
    </Box>
  );
}

function Legend({
  side,
  label,
  model,
}: {
  side: "a" | "b";
  label: string;
  model?: string;
}) {
  return (
    <Box
      sx={{
        display: "flex",
        alignItems: "baseline",
        gap: 1,
        px: 1,
        pb: 0.5,
        mb: 0.5,
        borderBottom: "1px solid",
        borderColor: "divider",
        minWidth: 0,
      }}
    >
      <Box
        component="span"
        aria-hidden
        sx={{
          fontWeight: 800,
          color: side === "a" ? "error.main" : "success.main",
        }}
      >
        {side === "a" ? "−" : "+"}
      </Box>
      <Typography
        component="span"
        title={model}
        sx={{ fontWeight: 700, fontSize: "0.85rem", minWidth: 0 }}
        noWrap
      >
        {side.toUpperCase()} · {label}
      </Typography>
      <Typography
        component="span"
        variant="caption"
        sx={{ color: "text.secondary", flexShrink: 0 }}
      >
        {side === "a"
          ? "removed words struck through"
          : "added words underlined"}
      </Typography>
    </Box>
  );
}

/**
 * The diff in a dialog. `a`/`b` null while their text loads; `error` says
 * why one couldn't be read.
 */
export default function AnswerDiffDialog({
  open,
  a,
  b,
  labels,
  error = null,
  onClose,
}: {
  open: boolean;
  a: DiffSide | null;
  b: DiffSide | null;
  /** The two answers' names, shown while their text loads. */
  labels: { a: string; b: string };
  error?: string | null;
  onClose: () => void;
}) {
  const theme = useTheme();
  const phone = useMediaQuery(theme.breakpoints.down("sm"));
  return (
    <Dialog
      open={open}
      onClose={onClose}
      maxWidth="lg"
      fullWidth
      fullScreen={phone}
      scroll="paper"
      aria-labelledby="answer-diff-title"
      PaperProps={{ sx: { borderRadius: phone ? 0 : 3 } }}
    >
      <DialogTitle
        id="answer-diff-title"
        sx={{ fontSize: "1rem", fontWeight: 700 }}
      >
        Compare answers: {labels.a} and {labels.b}
      </DialogTitle>
      <DialogContent dividers>
        {error ? (
          <Typography role="alert" color="error" variant="body2">
            {error}
          </Typography>
        ) : a && b ? (
          <DiffView a={a} b={b} />
        ) : (
          <Box
            role="status"
            sx={{
              display: "flex",
              alignItems: "center",
              gap: 1,
              color: "text.secondary",
            }}
          >
            <CircularProgress size={14} thickness={6} />
            <Typography variant="body2">Loading both answers…</Typography>
          </Box>
        )}
      </DialogContent>
      <DialogActions>
        <Button onClick={onClose}>Close</Button>
      </DialogActions>
    </Dialog>
  );
}
