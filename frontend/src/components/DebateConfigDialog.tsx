"use client";

import React, { useState } from "react";
import {
  Dialog,
  DialogTitle,
  DialogContent,
  DialogActions,
  Button,
  Box,
  Typography,
  Switch,
  Stack,
  Select,
  MenuItem,
  Chip,
  useTheme,
} from "@mui/material";
import { Swords } from "lucide-react";
import type { DebateDefaults, PeerLabels } from "@/lib/types";
import { MAX_DEBATE_ROUNDS, clampRounds } from "@/hooks/useDebateDefaults";
import { debateCallEstimate } from "@/lib/debateTranscript";

interface DebateConfigDialogProps {
  open: boolean;
  onClose: () => void;
  onStart: (config: DebateDefaults) => void;
  defaults: DebateDefaults;
  availableModels: string[];
  /** Display name for a model ID; the ID itself goes in a tooltip. */
  modelLabel: (id: string) => string;
  /** The question the models will debate, shown so you know what you're starting. */
  question: string;
  participants: string[];
  /** The backend's round limit (GET /models `limits.max_debate_rounds`). */
  maxRounds?: number;
}

/**
 * One setting: its label and control on a line, and what it does in a short
 * line under them. The explanations used to live only in `title` tooltips,
 * which keyboard and touch never see; the control points at its line with
 * aria-describedby.
 */
function Setting({ help, helpId, children }: { help: string; helpId: string; children: React.ReactNode }) {
  return (
    <Box>
      <Box sx={{ display: "flex", alignItems: "center", flexWrap: "wrap", columnGap: 2, rowGap: 0.5 }}>{children}</Box>
      <Typography id={helpId} variant="caption" sx={{ display: "block", mt: 0.25, color: "text.secondary", lineHeight: 1.4 }}>
        {help}
      </Typography>
    </Box>
  );
}

export default function DebateConfigDialog({
  open,
  onClose,
  onStart,
  defaults,
  availableModels,
  modelLabel,
  question,
  participants,
  maxRounds = MAX_DEBATE_ROUNDS,
}: DebateConfigDialogProps) {
  const isDark = useTheme().palette.mode === "dark";
  const [config, setConfig] = useState<DebateDefaults>(defaults);
  // The field's raw text: clamped on blur and on start, not per keystroke.
  const [roundsText, setRoundsText] = useState(String(defaults.max_rounds));

  // Each opening starts from the current defaults (the Control Panel's).
  const [syncedFor, setSyncedFor] = useState({ defaults, open });
  if (syncedFor.defaults !== defaults || syncedFor.open !== open) {
    setSyncedFor({ defaults, open });
    setConfig(defaults);
    setRoundsText(String(defaults.max_rounds));
  }

  const commitRounds = () => {
    // Clamped here, on blur and on start, never per keystroke: clamping while
    // typing turned a cleared field into "3" and made two-digit counts
    // impossible to type. An empty or invalid field keeps the last value.
    const typed = Number.parseInt(roundsText.trim(), 10);
    const max_rounds = Number.isFinite(typed) ? clampRounds(typed, maxRounds) : config.max_rounds;
    setRoundsText(String(max_rounds));
    setConfig((p) => ({ ...p, max_rounds }));
    return max_rounds;
  };

  const typedRounds = Number.parseInt(roundsText.trim(), 10);
  const estimate = debateCallEstimate({
    rounds: Number.isFinite(typedRounds) ? clampRounds(typedRounds, maxRounds) : config.max_rounds,
    participants: participants.length,
    judge: !!config.llm_judge,
    synthesize: config.auto_synthesize,
  });

  const labelSx = { fontSize: "0.8rem", color: "text.primary", fontWeight: 600, minWidth: 140 };

  return (
    <Dialog
      open={open}
      onClose={onClose}
      PaperProps={{
        sx: {
          borderRadius: 3,
          bgcolor: isDark ? "#111827" : "#fff",
          border: "1px solid",
          borderColor: isDark ? "rgba(255,255,255,0.08)" : "divider",
          minWidth: { xs: "auto", sm: 380 },
          width: { xs: "calc(100% - 32px)", sm: "auto" },
          maxWidth: 520,
          backgroundImage: "none",
        },
      }}
      slotProps={{
        backdrop: { sx: { backdropFilter: "blur(4px)", bgcolor: "rgba(0,0,0,0.5)" } },
      }}
    >
      <DialogTitle
        sx={{
          display: "flex",
          alignItems: "center",
          gap: 1.5,
          fontWeight: 800,
          fontSize: "1rem",
          pb: 0.5,
        }}
      >
        <Swords width={18} height={18} color="#8b5cf6" />
        Configure Debate Session
      </DialogTitle>

      <DialogContent sx={{ pt: 2 }}>
        <Stack spacing={1.75}>
          <Typography
            data-testid="debate-purpose"
            sx={{ fontSize: "0.8rem", color: "text.secondary", lineHeight: 1.5 }}
          >
            Models argue over several rounds so you can see the strongest arguments and where they
            disagree. Agreement after debating isn&apos;t evidence: for an answer you can rely on,
            compare independent answers in Arena and synthesize.
          </Typography>
          <Box>
            <Typography sx={{ ...labelSx, mb: 0.5 }}>Question</Typography>
            <Typography
              data-testid="debate-question"
              sx={{
                fontSize: "0.9rem",
                color: "text.primary",
                whiteSpace: "pre-wrap",
                maxHeight: 120,
                overflow: "auto",
                p: 1.25,
                borderRadius: 1.5,
                border: "1px solid",
                borderColor: "divider",
              }}
            >
              {question}
            </Typography>
          </Box>
          <Box>
            <Typography sx={{ ...labelSx, mb: 0.5 }}>Participants</Typography>
            <Box sx={{ display: "flex", flexWrap: "wrap", gap: 0.75 }}>
              {participants.map((m) => (
                <Chip key={m} size="small" label={modelLabel(m)} title={m} />
              ))}
            </Box>
            <Typography variant="caption" sx={{ display: "block", mt: 0.75, color: "text.secondary" }}>
              The models selected in the Control Panel. Change the selection there to debate with others.
            </Typography>
          </Box>

          {/* Max rounds */}
          <Setting help="Every participant answers once per round." helpId="debate-rounds-help">
            <Typography sx={labelSx}>Max rounds</Typography>
            <Box
              component="input"
              type="number"
              aria-label="Max rounds"
              aria-describedby="debate-rounds-help"
              min={1}
              max={maxRounds}
              value={roundsText}
              onChange={(e: React.ChangeEvent<HTMLInputElement>) => setRoundsText(e.target.value)}
              onBlur={commitRounds}
              sx={{
                width: 64,
                px: 1.5,
                py: 0.75,
                borderRadius: 1.5,
                border: "1px solid",
                borderColor: "divider",
                bgcolor: "transparent",
                color: "text.primary",
                fontSize: "0.85rem",
                outline: "none",
                textAlign: "center",
                "&:focus": { borderColor: "primary.main" },
              }}
            />
          </Setting>

          {/* Stop on stability: answers stopped changing (not agreement) */}
          <Setting
            help="Stops once each model's answer barely changes from its own last one. Opposed models stop changing too: this is stability, not agreement."
            helpId="debate-stability-help"
          >
            <Typography sx={labelSx}>Stop when answers stop changing</Typography>
            <Switch
              size="small"
              slotProps={{
                input: { "aria-label": "Stop when answers stop changing", "aria-describedby": "debate-stability-help" },
              }}
              checked={config.convergence_threshold !== null}
              onChange={() =>
                setConfig((p) => ({
                  ...p,
                  convergence_threshold: p.convergence_threshold !== null ? null : 0.92,
                }))
              }
              sx={{ "& .MuiSwitch-track": { bgcolor: "rgba(139,92,246,0.4)" } }}
            />
            {config.convergence_threshold !== null && (
              <Typography variant="caption" sx={{ color: "text.secondary" }}>
                similarity {config.convergence_threshold}
              </Typography>
            )}
          </Setting>

          {/* LLM Judge */}
          <Setting
            help="A model reads each round's answers by participant label and stops the debate once they agree. Agreement reached by debating isn't evidence by itself."
            helpId="debate-judge-help"
          >
            <Typography sx={labelSx}>Agreement judge</Typography>
            <Select
              size="small"
              inputProps={{ "aria-label": "Agreement judge" }}
              SelectDisplayProps={{ "aria-describedby": "debate-judge-help" } as React.HTMLAttributes<HTMLDivElement>}
              value={config.llm_judge ?? "__none__"}
              onChange={(e) =>
                setConfig((p) => ({
                  ...p,
                  llm_judge: e.target.value === "__none__" ? null : e.target.value,
                }))
              }
              sx={{ fontSize: "0.8rem", minWidth: 160 }}
            >
              <MenuItem value="__none__">
                <Typography variant="caption" sx={{ color: "text.secondary" }}>
                  None
                </Typography>
              </MenuItem>
              {availableModels.map((m) => (
                <MenuItem key={m} value={m} title={m}>
                  <Typography variant="caption">{modelLabel(m)}</Typography>
                </MenuItem>
              ))}
            </Select>
          </Setting>

          {/* How the two stop conditions combine; meaningless with only one */}
          {config.convergence_threshold !== null && config.llm_judge && (
            <Setting help="Any: either condition ends the debate. All: both must hold at once." helpId="debate-mode-help">
              <Typography sx={labelSx}>Stop when</Typography>
              <Select
                size="small"
                inputProps={{ "aria-label": "Stop when" }}
                SelectDisplayProps={{ "aria-describedby": "debate-mode-help" } as React.HTMLAttributes<HTMLDivElement>}
                value={config.mode}
                onChange={(e) =>
                  setConfig((p) => ({ ...p, mode: e.target.value as "any" | "all" }))
                }
                sx={{ fontSize: "0.8rem", minWidth: 160 }}
              >
                <MenuItem value="any">
                  <Typography variant="caption">Any condition met</Typography>
                </MenuItem>
                <MenuItem value="all">
                  <Typography variant="caption">All conditions met</Typography>
                </MenuItem>
              </Select>
            </Setting>
          )}

          {/* How debaters see each other */}
          <Setting
            help="Anonymous, a reply is weighed by its argument, not by which model wrote it. The banner always shows you who is who."
            helpId="debate-peers-help"
          >
            <Typography sx={labelSx}>Models see each other</Typography>
            <Select
              size="small"
              value={config.peer_labels}
              inputProps={{ "aria-label": "How models see each other" }}
              SelectDisplayProps={{ "aria-describedby": "debate-peers-help" } as React.HTMLAttributes<HTMLDivElement>}
              onChange={(e) =>
                setConfig((p) => ({ ...p, peer_labels: e.target.value as PeerLabels }))
              }
              sx={{ fontSize: "0.8rem", minWidth: 160 }}
            >
              <MenuItem value="anonymous">
                <Typography variant="caption">As Participant A, B…</Typography>
              </MenuItem>
              <MenuItem value="named">
                <Typography variant="caption">By model name</Typography>
              </MenuItem>
            </Select>
          </Setting>

          {/* Auto-synthesize */}
          <Setting
            help="When it ends, map the arguments: the positions, their best evidence, who changed and why, what is unresolved. It picks no winner."
            helpId="debate-synthesis-help"
          >
            <Typography sx={labelSx}>Auto-synthesize</Typography>
            <Switch
              size="small"
              slotProps={{ input: { "aria-label": "Auto-synthesize", "aria-describedby": "debate-synthesis-help" } }}
              checked={config.auto_synthesize}
              onChange={() =>
                setConfig((p) => ({ ...p, auto_synthesize: !p.auto_synthesize }))
              }
            />
          </Setting>

          {/* Synthesizer model */}
          {config.auto_synthesize && (
            <Setting help="The model that writes the map." helpId="debate-synthesizer-help">
              <Typography sx={labelSx}>Synthesizer</Typography>
              <Select
                size="small"
                inputProps={{ "aria-label": "Synthesizer" }}
                SelectDisplayProps={{ "aria-describedby": "debate-synthesizer-help" } as React.HTMLAttributes<HTMLDivElement>}
                value={config.synthesizer_model ?? "__none__"}
                onChange={(e) =>
                  setConfig((p) => ({
                    ...p,
                    synthesizer_model:
                      e.target.value === "__none__" ? null : e.target.value,
                  }))
                }
                sx={{ fontSize: "0.8rem", minWidth: 160 }}
              >
                <MenuItem value="__none__">
                  <Typography variant="caption" sx={{ color: "text.secondary" }}>
                    First participant
                  </Typography>
                </MenuItem>
                {availableModels.map((m) => (
                  <MenuItem key={m} value={m} title={m}>
                    <Typography variant="caption">{modelLabel(m)}</Typography>
                  </MenuItem>
                ))}
              </Select>
            </Setting>
          )}
          <Typography data-testid="debate-cost" variant="caption" sx={{ color: "text.secondary" }}>
            Up to {estimate.calls} model calls ({estimate.breakdown}); stopping early makes fewer.
          </Typography>
        </Stack>
      </DialogContent>

      <DialogActions sx={{ px: 3, pb: 2.5, gap: 1 }}>
        <Button
          onClick={onClose}
          size="small"
          sx={{ textTransform: "none", fontWeight: 600, color: "text.secondary" }}
        >
          Cancel
        </Button>
        <Button
          onClick={() => onStart({ ...config, max_rounds: commitRounds() })}
          variant="contained"
          size="small"
          sx={{
            textTransform: "none",
            fontWeight: 700,
            background: "linear-gradient(135deg, #7c3aed, #2563eb)",
            "&:hover": { background: "linear-gradient(135deg, #6d28d9, #1d4ed8)" },
          }}
        >
          Start Debate
        </Button>
      </DialogActions>
    </Dialog>
  );
}
