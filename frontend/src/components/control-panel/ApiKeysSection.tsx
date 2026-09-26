import React, { useEffect, useState } from "react";
import { alpha, Box, Button, ButtonBase, Collapse, IconButton, InputAdornment, Stack, TextField, Typography } from "@mui/material";
import { ChevronDown, ChevronRight, Eye, EyeOff } from "lucide-react";
import { fetchKeyStatus, saveApiKeys, type KeyInfo, type ModelFamily } from "@/lib/api";
import { FAMILY_ENV_KEY, SectionHeader, getFamilyColors } from "./primitives";

/** API key entry per provider family; keys are sent to the backend, never stored here. */
export default function ApiKeysSection({
  families,
  isDark,
  onSaved,
}: {
  families: ModelFamily[];
  isDark: boolean;
  onSaved: () => void;
}) {
  const [keyInputs, setKeyInputs] = useState<Record<string, string>>({});
  const [keyInfo, setKeyInfo] = useState<Record<string, KeyInfo>>({});
  const [keyShowMap, setKeyShowMap] = useState<Record<string, boolean>>({});
  const [expandedKeys, setExpandedKeys] = useState<Set<string>>(new Set());
  const [keySaving, setKeySaving] = useState(false);
  const [keySaved, setKeySaved] = useState(false);
  const [keyError, setKeyError] = useState<string | null>(null);

  const refreshKeyInfo = () => {
    fetchKeyStatus()
      .then(setKeyInfo)
      .catch(() => {});
  };

  useEffect(() => {
    refreshKeyInfo();
  }, []);

  // Auto-expand families with no key on first load
  useEffect(() => {
    const missing = families
      .filter((f) => !f.available && FAMILY_ENV_KEY[f.key])
      .map((f) => f.key);
    if (missing.length > 0)
      setExpandedKeys((prev) => new Set([...prev, ...missing]));
  }, [families]);

  const keyFamilies = families.filter((f) => FAMILY_ENV_KEY[f.key]);
  const hasChanges = Object.values(keyInputs).some((v) => v.trim() !== "");

  const handleSave = async () => {
    const payload: Record<string, string> = {};
    for (const [familyKey, value] of Object.entries(keyInputs)) {
      const envKey = FAMILY_ENV_KEY[familyKey];
      if (envKey && value.trim()) payload[envKey] = value.trim();
    }
    if (!Object.keys(payload).length) return;
    setKeySaving(true);
    setKeyError(null);
    try {
      await saveApiKeys(payload);
      setKeyInputs({});
      setKeySaved(true);
      setTimeout(() => setKeySaved(false), 2000);
      refreshKeyInfo();
      onSaved();
    } catch (e) {
      setKeyError(e instanceof Error ? e.message : "Failed to save API keys");
    } finally {
      setKeySaving(false);
    }
  };

  if (!keyFamilies.length) return null;

  return (
    <Box>
      <SectionHeader label="API Keys" />
      <Stack spacing={1}>
        {keyFamilies.map((family) => {
          const fc = getFamilyColors(family.color);
          const isExpanded = expandedKeys.has(family.key);
          const inputVal = keyInputs[family.key] ?? "";
          const showVal = keyShowMap[family.key];

          return (
            <Box key={family.key}>
              <ButtonBase
                onClick={() =>
                  setExpandedKeys((prev) => {
                    const next = new Set(prev);
                    next.has(family.key)
                      ? next.delete(family.key)
                      : next.add(family.key);
                    return next;
                  })
                }
                sx={{
                  width: "100%",
                  display: "flex",
                  justifyContent: "space-between",
                  alignItems: "center",
                  px: 2,
                  py: 1.25,
                  borderRadius: 2,
                  border: "1px solid",
                  transition: "all 0.2s",
                  borderColor: family.available
                    ? fc.activeBorder
                    : isDark
                      ? "rgba(255,255,255,0.04)"
                      : "divider",
                  bgcolor: family.available
                    ? fc.activeBg
                    : isDark
                      ? "rgba(255,255,255,0.01)"
                      : "background.paper",
                  "&:hover": { borderColor: fc.activeBorder },
                }}
              >
                <Box sx={{ display: "flex", alignItems: "center", gap: 1.5 }}>
                  <Box
                    sx={{
                      width: 8,
                      height: 8,
                      borderRadius: "50%",
                      bgcolor: family.available ? fc.color : "text.disabled",
                      transition: "all 0.3s",
                    }}
                  />
                  <Typography
                    variant="body2"
                    sx={{
                      fontWeight: 700,
                      color: family.available ? fc.color : "text.secondary",
                      fontSize: "0.9375rem",
                    }}
                  >
                    {family.label}
                  </Typography>
                </Box>
                <Box sx={{ display: "flex", alignItems: "center", gap: 0.75 }}>
                  <Box
                    sx={{
                      px: 0.75,
                      py: 0.125,
                      borderRadius: 1,
                      fontSize: "0.6rem",
                      fontWeight: 800,
                      letterSpacing: "0.05em",
                      bgcolor: family.available
                        ? alpha(fc.color, 0.15)
                        : isDark
                          ? "rgba(255,255,255,0.06)"
                          : "rgba(0,0,0,0.04)",
                      color: family.available ? fc.color : "text.disabled",
                    }}
                  >
                    {family.available ? "SET" : "NOT SET"}
                  </Box>
                  {isExpanded ? (
                    <ChevronDown width={14} height={14} />
                  ) : (
                    <ChevronRight width={14} height={14} />
                  )}
                </Box>
              </ButtonBase>

              <Collapse in={isExpanded} timeout="auto">
                <Box sx={{ mt: 0.75, ml: 1.5 }}>
                  {keyInfo[FAMILY_ENV_KEY[family.key]]?.masked && !inputVal && (
                    <Typography
                      variant="caption"
                      sx={{
                        display: "block",
                        mb: 0.75,
                        fontFamily: "monospace",
                        fontSize: "0.72rem",
                        letterSpacing: "0.03em",
                        color: "text.disabled",
                        px: 0.5,
                        overflow: "hidden",
                        textOverflow: "ellipsis",
                        whiteSpace: "nowrap",
                      }}
                    >
                      {keyInfo[FAMILY_ENV_KEY[family.key]].masked}
                    </Typography>
                  )}
                  <TextField
                    fullWidth
                    size="small"
                    type={showVal ? "text" : "password"}
                    placeholder={
                      family.available
                        ? "Enter new key to replace"
                        : `Paste your ${family.label} API key`
                    }
                    value={inputVal}
                    onChange={(e) =>
                      setKeyInputs((prev) => ({
                        ...prev,
                        [family.key]: e.target.value,
                      }))
                    }
                    slotProps={{
                      input: {
                        sx: {
                          fontFamily: "monospace",
                          fontSize: "0.75rem",
                          borderRadius: 1.5,
                        },
                        endAdornment: (
                          <InputAdornment position="end">
                            <IconButton
                              size="small"
                              onClick={() =>
                                setKeyShowMap((prev) => ({
                                  ...prev,
                                  [family.key]: !prev[family.key],
                                }))
                              }
                            >
                              {showVal ? (
                                <EyeOff width={13} height={13} />
                              ) : (
                                <Eye width={13} height={13} />
                              )}
                            </IconButton>
                          </InputAdornment>
                        ),
                      },
                    }}
                  />
                </Box>
              </Collapse>
            </Box>
          );
        })}
      </Stack>

      {hasChanges && (
        <Button
          fullWidth
          size="small"
          variant="contained"
          onClick={handleSave}
          disabled={keySaving || keySaved}
          sx={{ mt: 1.5, borderRadius: 2, fontSize: "0.75rem" }}
        >
          {keySaved ? "Saved!" : keySaving ? "Saving…" : "Save Keys"}
        </Button>
      )}
      {keyError && (
        <Typography
          role="alert"
          variant="caption"
          sx={{ display: "block", mt: 1, color: "error.main", fontSize: "0.7rem" }}
        >
          {keyError}
        </Typography>
      )}
    </Box>
  );
}
