"use client";
import React from "react";
import {
  Box,
  Button,
  ButtonBase,
  Checkbox,
  CircularProgress,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  FormControlLabel,
  IconButton,
  Paper,
  Typography,
  useMediaQuery,
  useTheme,
} from "@mui/material";
import { ArrowLeft, RotateCcw, Trash2 } from "lucide-react";
import type { ModelFamily } from "@/lib/api";
import {
  baselineNote,
  defaultReplayModels,
  replayChoices,
  replayDiffSides,
  settingsSummary,
  voteSummary,
  type CaseReplay,
  type CaseSummary,
  type ReplayResult,
  type SavedCase,
} from "@/lib/cases";
import { MessageBody } from "./MessageBubble";
import { ReplyMetricsLine, TurnMetricsLine } from "./ReplyMetrics";
import { DiffView } from "./AnswerDiff";

const when = (iso: string | null | undefined) => (iso ? iso.slice(0, 16).replace("T", " ") : "");

interface Props {
  open: boolean;
  list: CaseSummary[];
  loading: boolean;
  /** The case open in the dialog; null shows the list. */
  current: SavedCase | null;
  replaying: boolean;
  families: ModelFamily[];
  modelLabel: (id: string) => string;
  onClose: () => void;
  onBack: () => void;
  onOpenCase: (caseId: string) => void;
  onDelete: (caseId: string, title: string) => void;
  onReplay: (models: string[]) => void;
}

/** Saved cases: the list, one case with its answers and vote, and replaying it old against new. */
export default function SavedCasesDialog(props: Props) {
  const { open, current, onClose, onBack } = props;
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
      aria-labelledby="saved-cases-title"
      PaperProps={{ sx: { borderRadius: phone ? 0 : 3 } }}
    >
      <DialogTitle
        id="saved-cases-title"
        sx={{ fontSize: "1rem", fontWeight: 700, display: "flex", alignItems: "center", gap: 1 }}
      >
        {current && (
          <IconButton aria-label="Back to saved cases" onClick={onBack} size="small">
            <ArrowLeft width={16} height={16} />
          </IconButton>
        )}
        <Box component="span" sx={{ minWidth: 0, overflow: "hidden", textOverflow: "ellipsis" }}>
          {current ? current.title : "Saved cases"}
        </Box>
      </DialogTitle>
      <DialogContent dividers>
        {current ? (
          <CaseView key={current.case_id} {...props} current={current} isDark={theme.palette.mode === "dark"} />
        ) : (
          <CaseList {...props} />
        )}
      </DialogContent>
      <DialogActions>
        <Button onClick={onClose}>Close</Button>
      </DialogActions>
    </Dialog>
  );
}

function CaseList({ list, loading, onOpenCase, onDelete }: Props) {
  if (!list.length) {
    return loading ? (
      <Box role="status" sx={{ display: "flex", alignItems: "center", gap: 1, color: "text.secondary" }}>
        <CircularProgress size={14} thickness={6} />
        <Typography variant="body2">Loading saved cases…</Typography>
      </Box>
    ) : (
      <Typography variant="body2" sx={{ color: "text.secondary" }}>
        No saved cases yet. Under a finished turn&apos;s answers, &quot;Save as a case&quot; keeps its question,
        context, answers and your vote, so you can ask newer or cheaper models the same thing later.
      </Typography>
    );
  }
  return (
    <Box component="ul" aria-label="Saved cases" sx={{ listStyle: "none", m: 0, p: 0, display: "grid", gap: 1 }}>
      {list.map((c) => (
        <Box component="li" key={c.case_id} sx={{ display: "flex", alignItems: "stretch", gap: 0.5 }}>
          <ButtonBase
            onClick={() => onOpenCase(c.case_id)}
            sx={{
              flex: 1,
              minWidth: 0,
              justifyContent: "flex-start",
              textAlign: "left",
              px: 1.5,
              py: 1,
              borderRadius: 2,
              border: "1px solid",
              borderColor: "divider",
              "&:hover": { borderColor: "primary.main" },
            }}
          >
            <Box sx={{ minWidth: 0 }}>
              <Typography sx={{ fontWeight: 700, fontSize: "0.9rem" }} noWrap>
                {c.title}
              </Typography>
              <Typography variant="caption" sx={{ color: "text.secondary", display: "block" }}>
                {c.model_names.join(", ")}
                {c.voted ? " · voted" : ""} · {c.replay_count} replay{c.replay_count === 1 ? "" : "s"} · saved{" "}
                {when(c.created_at)}
              </Typography>
            </Box>
          </ButtonBase>
          <IconButton aria-label={`Delete case ${c.title}`} onClick={() => onDelete(c.case_id, c.title)}>
            <Trash2 width={16} height={16} />
          </IconButton>
        </Box>
      ))}
    </Box>
  );
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <Box component="section" aria-label={title} sx={{ display: "grid", gap: 1 }}>
      <Typography
        variant="overline"
        sx={{ fontWeight: 800, color: "text.secondary", fontSize: "0.6875rem", letterSpacing: "0.1em" }}
      >
        {title}
      </Typography>
      {children}
    </Box>
  );
}

function Answer({
  label,
  model,
  text,
  metrics,
  note,
  isDark,
  children,
}: {
  label: string;
  model: string;
  text: string;
  metrics: ReplayResult["metrics"];
  note?: string;
  isDark: boolean;
  children?: React.ReactNode;
}) {
  return (
    <Paper
      component="article"
      aria-label={`${label}'s answer`}
      variant="outlined"
      sx={{ p: 1.5, borderRadius: 3, minWidth: 0 }}
    >
      <Typography title={model} sx={{ fontWeight: 700, fontSize: "0.85rem", mb: 0.5 }}>
        {label}
      </Typography>
      {text ? (
        <Box sx={{ maxHeight: "16em", overflow: "auto", mb: 1 }}>
          <MessageBody msg={{ id: `${model}-${label}`, role: "assistant", content: text }} isDark={isDark} compact />
        </Box>
      ) : null}
      <ReplyMetricsLine metrics={metrics} />
      {note && (
        <Typography variant="body2" sx={{ mt: 0.5, fontSize: "0.8rem" }}>
          {note}
        </Typography>
      )}
      {children}
    </Paper>
  );
}

const grid = {
  display: "grid",
  gap: 1.5,
  gridTemplateColumns: { xs: "minmax(0, 1fr)", md: "repeat(2, minmax(0, 1fr))" },
};

function CaseView({
  current,
  families,
  modelLabel,
  replaying,
  onReplay,
  onDelete,
  isDark,
}: Props & { current: SavedCase; isDark: boolean }) {
  const caseModels = React.useMemo(() => current.answers.map((a) => a.model), [current.answers]);
  const choices = React.useMemo(() => replayChoices(families, caseModels), [families, caseModels]);
  // The case's own models until the person picks: the catalogue may load after the dialog opens.
  const [picked, setPicked] = React.useState<string[] | null>(null);
  const chosen = picked ?? defaultReplayModels(caseModels, choices);
  const toggle = (id: string) => setPicked(chosen.includes(id) ? chosen.filter((m) => m !== id) : [...chosen, id]);
  const settings = settingsSummary(current.settings, modelLabel);
  const vote = voteSummary(current, modelLabel);
  const earlier = current.history.filter((m) => m.kind !== "summary").length;
  const context = [
    earlier
      ? `${earlier} earlier message${earlier === 1 ? "" : "s"}${current.summarized ? " (summarized)" : ""}`
      : "no earlier messages",
    current.documents.length ? `documents: ${current.documents.map((d) => d.name).join(", ")}` : null,
    settings.length ? settings.join(", ") : null,
  ].filter(Boolean);

  return (
    <Box sx={{ display: "grid", gap: 3 }}>
      <Box sx={{ display: "grid", gap: 0.75 }}>
        <Typography sx={{ fontWeight: 700, whiteSpace: "pre-wrap" }}>{current.question}</Typography>
        <Typography variant="caption" sx={{ color: "text.secondary" }}>
          Saved {when(current.created_at)} · {context.join(" · ")}
        </Typography>
        {vote && <Typography variant="body2">Your vote: {vote}</Typography>}
        <Box>
          <ButtonBase
            onClick={() => onDelete(current.case_id, current.title)}
            sx={{
              fontSize: "0.75rem",
              fontWeight: 600,
              color: "error.main",
              px: 1,
              py: 0.25,
              borderRadius: 1.5,
              gap: 0.5,
            }}
          >
            <Trash2 width={12} height={12} /> Delete this case
          </ButtonBase>
        </Box>
      </Box>

      <Section title="The case's answers">
        <Box sx={grid}>
          {current.answers.map((a) => (
            <Answer
              key={a.checkpoint_id}
              label={a.model_name || modelLabel(a.model)}
              model={a.model}
              text={a.content}
              metrics={a.metrics}
              isDark={isDark}
              note={
                current.best_model === a.model && current.vote?.outcome === "best" ? "You voted this best." : undefined
              }
            />
          ))}
        </Box>
        <TurnMetricsLine total={current.total} />
      </Section>

      <Section title="Replay on">
        {choices.length ? (
          <Box role="group" aria-label="Models to replay on" sx={{ display: "flex", flexWrap: "wrap", columnGap: 2 }}>
            {choices.map((id) => (
              <FormControlLabel
                key={id}
                title={id}
                control={<Checkbox size="small" checked={chosen.includes(id)} onChange={() => toggle(id)} />}
                label={modelLabel(id)}
                sx={{ "& .MuiFormControlLabel-label": { fontSize: "0.85rem" } }}
              />
            ))}
          </Box>
        ) : (
          <Typography variant="body2" sx={{ color: "text.secondary" }}>
            No model has a key. Add one in the Control Panel&apos;s API Keys.
          </Typography>
        )}
        <Box sx={{ display: "flex", alignItems: "center", gap: 1.5, flexWrap: "wrap" }}>
          <Button
            variant="contained"
            size="small"
            onClick={() => onReplay(chosen)}
            disabled={!chosen.length || replaying}
            startIcon={
              replaying ? <CircularProgress size={12} color="inherit" /> : <RotateCcw width={14} height={14} />
            }
          >
            {replaying ? "Replaying…" : `Replay on ${chosen.length} model${chosen.length === 1 ? "" : "s"}`}
          </Button>
          <Typography variant="caption" sx={{ color: "text.secondary" }}>
            Each model answers once, at its provider&apos;s price, in a new thread with this case&apos;s context. The
            thread it came from isn&apos;t touched.
          </Typography>
        </Box>
      </Section>

      {current.replays.map((r) => (
        <ReplayView key={r.replay_id} replay={r} current={current} modelLabel={modelLabel} isDark={isDark} />
      ))}
    </Box>
  );
}

function ReplayView({
  replay,
  current,
  modelLabel,
  isDark,
}: {
  replay: CaseReplay;
  current: SavedCase;
  modelLabel: (id: string) => string;
  isDark: boolean;
}) {
  const [showing, setShowing] = React.useState<string | null>(null);
  return (
    <Section title={`Replay · ${when(replay.created_at)}`}>
      <Box sx={grid}>
        {replay.results.map((r) => {
          const sides = replayDiffSides(current, r);
          const label = r.model_name || modelLabel(r.model);
          return (
            <Answer
              key={r.model}
              label={label}
              model={r.model}
              text={r.content ?? ""}
              metrics={r.metrics}
              note={baselineNote(r)}
              isDark={isDark}
            >
              {sides && (
                <ButtonBase
                  onClick={() => setShowing((s) => (s === r.model ? null : r.model))}
                  aria-pressed={showing === r.model}
                  sx={{
                    mt: 1,
                    fontSize: "0.8rem",
                    fontWeight: 600,
                    color: "primary.main",
                    px: 1,
                    py: 0.5,
                    borderRadius: 1.5,
                  }}
                >
                  {showing === r.model ? "Hide changes" : "Show changes"}
                </ButtonBase>
              )}
            </Answer>
          );
        })}
      </Box>
      <TurnMetricsLine total={replay.total} />
      {replay.results.map((r) => {
        const sides = showing === r.model ? replayDiffSides(current, r) : null;
        return sides ? (
          <Paper key={`diff-${r.model}`} variant="outlined" sx={{ p: 1.5, borderRadius: 3 }}>
            <DiffView a={sides.a} b={sides.b} />
          </Paper>
        ) : null;
      })}
    </Section>
  );
}
