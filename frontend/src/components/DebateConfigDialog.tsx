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
  useTheme,
} from "@mui/material";
import { Swords } from "lucide-react";
import type { DebateDefaults } from "@/lib/types";

interface DebateConfigDialogProps {
  open: boolean;
  onClose: () => void;
  onStart: (config: DebateDefaults) => void;
  defaults: DebateDefaults;
  availableModels: string[];
}

export default function DebateConfigDialog({
  open,
  onClose,
  onStart,
  defaults,
  availableModels,
}: DebateConfigDialogProps) {
  const isDark = useTheme().palette.mode === "dark";
  const [config, setConfig] = useState<DebateDefaults>(defaults);

  // Sync when defaults change (user updates ControlPanel)
  React.useEffect(() => {
    setConfig(defaults);
  }, [defaults, open]);

  const labelSx = { fontSize: "0.8rem", color: "text.secondary", minWidth: 140 };
  const rowSx = { display: "flex", alignItems: "center", gap: 2 };

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
          minWidth: 380,
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
        <Stack spacing={2.5}>
          {/* Max rounds */}
          <Box sx={rowSx}>
            <Typography sx={labelSx}>Max rounds</Typography>
            <Box
              component="input"
              type="number"
              min={1}
              max={20}
              value={config.max_rounds}
              onChange={(e: React.ChangeEvent<HTMLInputElement>) =>
                setConfig((p) => ({
                  ...p,
                  max_rounds: Math.max(1, Math.min(20, parseInt(e.target.value) || 3)),
                }))
              }
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
          </Box>

          {/* Convergence detection */}
          <Box sx={rowSx}>
            <Typography sx={labelSx}>Convergence detection</Typography>
            <Switch
              size="small"
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
              <Typography variant="caption" sx={{ color: "text.disabled" }}>
                threshold {config.convergence_threshold}
              </Typography>
            )}
          </Box>

          {/* LLM Judge */}
          <Box sx={rowSx}>
            <Typography sx={labelSx}>LLM judge</Typography>
            <Select
              size="small"
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
                <MenuItem key={m} value={m}>
                  <Typography variant="caption">{m}</Typography>
                </MenuItem>
              ))}
            </Select>
          </Box>

          {/* Convergence mode */}
          {(config.convergence_threshold !== null || config.llm_judge) && (
            <Box sx={rowSx}>
              <Typography sx={labelSx}>Stop when</Typography>
              <Select
                size="small"
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
            </Box>
          )}

          {/* Auto-synthesize */}
          <Box sx={rowSx}>
            <Typography sx={labelSx}>Auto-synthesize</Typography>
            <Switch
              size="small"
              checked={config.auto_synthesize}
              onChange={() =>
                setConfig((p) => ({ ...p, auto_synthesize: !p.auto_synthesize }))
              }
            />
          </Box>

          {/* Synthesizer model */}
          {config.auto_synthesize && (
            <Box sx={rowSx}>
              <Typography sx={labelSx}>Synthesizer</Typography>
              <Select
                size="small"
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
                  <MenuItem key={m} value={m}>
                    <Typography variant="caption">{m}</Typography>
                  </MenuItem>
                ))}
              </Select>
            </Box>
          )}
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
          onClick={() => onStart(config)}
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
