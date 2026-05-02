"use client";

import React, { useState, useEffect } from "react";
import {
  Dialog,
  DialogTitle,
  DialogContent,
  DialogActions,
  Button,
  Box,
  Typography,
  TextField,
  IconButton,
  InputAdornment,
  Chip,
  CircularProgress,
} from "@mui/material";
import { Eye, EyeOff, X, KeyRound } from "lucide-react";
import { fetchKeyStatus, saveApiKeys } from "@/lib/api";

interface Provider {
  envKey: string;
  label: string;
  color: string;
  placeholder: string;
}

const PROVIDERS: Provider[] = [
  {
    envKey: "OPENAI_API_KEY",
    label: "OpenAI",
    color: "#10a37f",
    placeholder: "sk-...",
  },
  {
    envKey: "ANTHROPIC_API_KEY",
    label: "Anthropic",
    color: "#d4a574",
    placeholder: "sk-ant-...",
  },
  {
    envKey: "GOOGLE_API_KEY",
    label: "Google",
    color: "#4285f4",
    placeholder: "AIza...",
  },
];

interface SettingsModalProps {
  open: boolean;
  onClose: () => void;
}

export default function SettingsModal({ open, onClose }: SettingsModalProps) {
  const [keyStatus, setKeyStatus] = useState<Record<string, boolean>>({});
  const [inputs, setInputs] = useState<Record<string, string>>({});
  const [showKey, setShowKey] = useState<Record<string, boolean>>({});
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);

  useEffect(() => {
    if (!open) return;
    setLoading(true);
    setSaved(false);
    setInputs({});
    fetchKeyStatus()
      .then(setKeyStatus)
      .finally(() => setLoading(false));
  }, [open]);

  const handleSave = async () => {
    setSaving(true);
    try {
      // Only send keys that have a value entered (to update) or are being cleared
      const payload: Record<string, string> = {};
      for (const p of PROVIDERS) {
        const val = inputs[p.envKey]?.trim();
        if (val !== undefined) {
          payload[p.envKey] = val; // empty string = remove key
        }
      }
      if (Object.keys(payload).length === 0) {
        onClose();
        return;
      }
      await saveApiKeys(payload);
      setSaved(true);
      // Reload after 1s so model availability reflects the new keys
      setTimeout(() => window.location.reload(), 1000);
    } finally {
      setSaving(false);
    }
  };

  const handleClear = (envKey: string) => {
    setInputs((prev) => ({ ...prev, [envKey]: "" }));
  };

  return (
    <Dialog
      open={open}
      onClose={onClose}
      maxWidth="sm"
      fullWidth
      PaperProps={{
        sx: {
          borderRadius: 4,
          border: "1px solid",
          borderColor: "divider",
          backgroundImage: "none",
        },
      }}
    >
      <DialogTitle sx={{ pb: 1 }}>
        <Box sx={{ display: "flex", alignItems: "center", gap: 1.5 }}>
          <Box
            sx={{
              width: 36,
              height: 36,
              borderRadius: 2,
              bgcolor: "primary.dark",
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
            }}
          >
            <KeyRound width={18} height={18} color="white" />
          </Box>
          <Box>
            <Typography variant="h6" fontWeight={800} lineHeight={1.2}>
              API Keys
            </Typography>
            <Typography variant="caption" color="text.secondary">
              Keys are saved to your local{" "}
              <code style={{ fontSize: "0.7rem" }}>.env</code> file
            </Typography>
          </Box>
        </Box>
      </DialogTitle>

      <DialogContent sx={{ pt: 2 }}>
        {loading ? (
          <Box sx={{ display: "flex", justifyContent: "center", py: 4 }}>
            <CircularProgress size={28} />
          </Box>
        ) : (
          <Box sx={{ display: "flex", flexDirection: "column", gap: 2.5 }}>
            {PROVIDERS.map((p) => {
              const isSet = keyStatus[p.envKey];
              const inputVal = inputs[p.envKey];
              const isClearing = inputVal === "";
              const show = showKey[p.envKey];

              return (
                <Box key={p.envKey}>
                  <Box
                    sx={{
                      display: "flex",
                      alignItems: "center",
                      gap: 1,
                      mb: 1,
                    }}
                  >
                    <Box
                      sx={{
                        width: 10,
                        height: 10,
                        borderRadius: "50%",
                        bgcolor: p.color,
                        flexShrink: 0,
                      }}
                    />
                    <Typography variant="body2" fontWeight={700}>
                      {p.label}
                    </Typography>
                    {isSet && !isClearing ? (
                      <Chip
                        label="SET"
                        size="small"
                        sx={{
                          height: 18,
                          fontSize: "0.6rem",
                          fontWeight: 800,
                          letterSpacing: "0.05em",
                          bgcolor: "success.dark",
                          color: "success.contrastText",
                          "& .MuiChip-label": { px: 1 },
                        }}
                      />
                    ) : isClearing ? (
                      <Chip
                        label="WILL REMOVE"
                        size="small"
                        sx={{
                          height: 18,
                          fontSize: "0.6rem",
                          fontWeight: 800,
                          letterSpacing: "0.05em",
                          bgcolor: "error.dark",
                          color: "error.contrastText",
                          "& .MuiChip-label": { px: 1 },
                        }}
                      />
                    ) : (
                      <Chip
                        label="NOT SET"
                        size="small"
                        sx={{
                          height: 18,
                          fontSize: "0.6rem",
                          fontWeight: 800,
                          letterSpacing: "0.05em",
                          "& .MuiChip-label": { px: 1 },
                        }}
                      />
                    )}
                  </Box>

                  <TextField
                    fullWidth
                    size="small"
                    type={show ? "text" : "password"}
                    placeholder={
                      isSet
                        ? "Currently set — leave blank to keep"
                        : p.placeholder
                    }
                    value={inputVal ?? ""}
                    onChange={(e) =>
                      setInputs((prev) => ({
                        ...prev,
                        [p.envKey]: e.target.value,
                      }))
                    }
                    InputProps={{
                      sx: {
                        borderRadius: 2,
                        fontFamily: "monospace",
                        fontSize: "0.8rem",
                      },
                      endAdornment: (
                        <InputAdornment position="end">
                          <IconButton
                            size="small"
                            onClick={() =>
                              setShowKey((prev) => ({
                                ...prev,
                                [p.envKey]: !prev[p.envKey],
                              }))
                            }
                          >
                            {show ? (
                              <EyeOff width={14} height={14} />
                            ) : (
                              <Eye width={14} height={14} />
                            )}
                          </IconButton>
                          {isSet && (
                            <IconButton
                              size="small"
                              title="Remove this key"
                              onClick={() => handleClear(p.envKey)}
                              sx={{ "&:hover": { color: "error.main" } }}
                            >
                              <X width={14} height={14} />
                            </IconButton>
                          )}
                        </InputAdornment>
                      ),
                    }}
                  />
                </Box>
              );
            })}
          </Box>
        )}
      </DialogContent>

      <DialogActions sx={{ px: 3, pb: 2.5, gap: 1 }}>
        <Button onClick={onClose} variant="text" sx={{ borderRadius: 2 }}>
          Cancel
        </Button>
        <Button
          onClick={handleSave}
          variant="contained"
          disabled={saving || saved || loading}
          sx={{ borderRadius: 2, minWidth: 90 }}
        >
          {saved ? "Saved!" : saving ? "Saving…" : "Save"}
        </Button>
      </DialogActions>
    </Dialog>
  );
}
