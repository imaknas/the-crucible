import React, { useState, useEffect } from "react";
import {
  Box,
  Drawer,
  Typography,
  ButtonBase,
  Switch,
  Stack,
  Divider,
  useTheme,
  Collapse,
  alpha,
  TextField,
  InputAdornment,
  IconButton,
  Button,
  Tooltip,
} from "@mui/material";
import {
  Settings2,
  BookOpen,
  Globe,
  ChevronDown,
  ChevronRight,
  Eye,
  EyeOff,
  Swords,
  PanelLeftOpen,
  PanelLeftClose,
} from "lucide-react";
import type { DebateDefaults } from "@/lib/types";
import { modelFamilyColor } from "@/lib/colors";
import {
  fetchModels,
  fetchKeyStatus,
  saveApiKeys,
  ModelFamily,
  KeyInfo,
} from "@/lib/api";

interface ControlPanelProps {
  toggles: {
    use_rag: boolean;
    use_web_search: boolean;
  };
  setToggles: React.Dispatch<
    React.SetStateAction<{
      use_rag: boolean;
      use_web_search: boolean;
    }>
  >;
  selectedModels: string[];
  setSelectedModels: (models: string[]) => void;
  messagesCount: number;
  threadId: string | null;
  activeCheckpointLabel: string;
  debateDefaults: DebateDefaults;
  setDebateDefaults: React.Dispatch<React.SetStateAction<DebateDefaults>>;
  collapsed: boolean;
  onCollapsedChange: (collapsed: boolean) => void;
}

/** Width of the collapsed rail. */
export const RAIL_WIDTH = 44;

// ─── Color Helpers ───────────────────────────────────────────────

function getFamilyColors(familyColor: string) {
  return {
    color: familyColor,
    dotColor: familyColor,
    activeBg: alpha(familyColor, 0.1),
    activeBorder: alpha(familyColor, 0.3),
  };
}

function getModelMetaFromId(model: string, families: ModelFamily[]) {
  for (const fam of families) {
    const found = fam.models.find((m) => m.id === model);
    if (found) {
      return {
        label: found.name,
        desc: found.desc,
        ...getFamilyColors(fam.color),
      };
    }
  }
  // fallback for unknown models
  return {
    label: model,
    desc: "Model",
    color: "#60a5fa",
    dotColor: "#60a5fa",
    activeBg: "rgba(59,130,246,0.1)",
    activeBorder: "rgba(59,130,246,0.3)",
  };
}

// ─── Constants ───────────────────────────────────────────────────

const FAMILY_ENV_KEY: Record<string, string> = {
  openai: "OPENAI_API_KEY",
  anthropic: "ANTHROPIC_API_KEY",
  google: "GOOGLE_API_KEY",
};

// ─── Sub-components ──────────────────────────────────────────────

function SectionHeader({ label }: { label: string }) {
  return (
    <Typography
      variant="overline"
      sx={{
        display: "block",
        mb: 1.5,
        fontSize: "0.7rem",
        fontWeight: 800,
        letterSpacing: "0.15em",
        color: "text.secondary",
      }}
    >
      {label}
    </Typography>
  );
}

function StatusRow({
  label,
  children,
}: {
  label: string;
  children: React.ReactNode;
}) {
  return (
    <Box>
      <Typography
        variant="overline"
        sx={{
          fontSize: "0.7rem",
          fontWeight: 700,
          letterSpacing: "0.1em",
          color: "text.secondary",
          mb: 0.5,
          display: "block",
        }}
      >
        {label}
      </Typography>
      {children}
    </Box>
  );
}

function ToggleRow({
  isDark,
  label,
  subtitle,
  icon,
  checked,
  onChange,
}: {
  isDark: boolean;
  label: string;
  subtitle?: string;
  icon: React.ReactNode;
  checked: boolean;
  onChange: () => void;
}) {
  return (
    <Box
      onClick={onChange}
      sx={{
        display: "flex",
        justifyContent: "space-between",
        alignItems: "center",
        p: 2,
        borderRadius: 2,
        cursor: "pointer",
        transition: "all 0.2s",
        border: "1px solid",
        borderColor: checked ? "primary.main" : "divider",
        bgcolor: checked
          ? isDark
            ? "rgba(37,99,235,0.05)"
            : "rgba(37,99,235,0.03)"
          : "transparent",
        "&:hover": { borderColor: "primary.main" },
      }}
    >
      <Box
        sx={{
          display: "flex",
          flexDirection: "column",
          gap: 0.5,
          maxWidth: "75%",
        }}
      >
        <Box sx={{ display: "flex", alignItems: "center", gap: 1.5 }}>
          {icon}
          <Typography
            variant="body2"
            sx={{
              fontWeight: 600,
              letterSpacing: "-0.02em",
              color: checked ? "text.primary" : "text.secondary",
            }}
          >
            {label}
          </Typography>
        </Box>
        {subtitle && (
          <Typography
            variant="caption"
            sx={{
              fontSize: "0.75rem",
              color: "text.disabled",
              lineHeight: 1.3,
              display: "block",
            }}
          >
            {subtitle}
          </Typography>
        )}
      </Box>
      <Switch
        size="small"
        checked={checked}
        onClick={(e) => e.stopPropagation()}
        onChange={onChange}
      />
    </Box>
  );
}

function ApiKeysSection({
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
    try {
      await saveApiKeys(payload);
      setKeyInputs({});
      setKeySaved(true);
      setTimeout(() => setKeySaved(false), 2000);
      refreshKeyInfo();
      onSaved();
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
    </Box>
  );
}

// ─── Main Component ──────────────────────────────────────────────

const ControlPanel: React.FC<ControlPanelProps> = React.memo(
  ({
    toggles,
    setToggles,
    selectedModels,
    setSelectedModels,
    messagesCount,
    threadId: _threadId,
    activeCheckpointLabel,
    debateDefaults,
    setDebateDefaults,
    collapsed,
    onCollapsedChange,
  }) => {
    const isDark = useTheme().palette.mode === "dark";
    const [families, setFamilies] = useState<ModelFamily[]>([]);
    const [modelsLoading, setModelsLoading] = useState(true);
    const [modelsError, setModelsError] = useState(false);
    const [expandedFamilies, setExpandedFamilies] = useState<Set<string>>(
      new Set(),
    );

    const loadModels = React.useCallback(() => {
      setModelsLoading(true);
      setModelsError(false);
      fetchModels()
        .then((data) => {
          setFamilies(data.families);
          setModelsLoading(false);
        })
        .catch(() => {
          setModelsLoading(false);
          setModelsError(true);
        });
    }, []);

    useEffect(() => {
      fetchModels()
        .then((data) => {
          setFamilies(data.families);
          setModelsLoading(false);
        })
        .catch(() => {
          setModelsLoading(false);
          setModelsError(true);
        });
    }, []);

    const handleModelToggle = (model: string) => {
      if (selectedModels.includes(model)) {
        if (selectedModels.length > 1)
          setSelectedModels(selectedModels.filter((m) => m !== model));
      } else {
        setSelectedModels([...selectedModels, model]);
      }
    };

    const toggleFamily = (key: string) => {
      setExpandedFamilies((prev) => {
        const next = new Set(prev);
        if (next.has(key)) next.delete(key);
        else next.add(key);
        return next;
      });
    };

    const selectedCount = (familyKey: string) => {
      const fam = families.find((f) => f.key === familyKey);
      if (!fam) return 0;
      return fam.models.filter((m) => selectedModels.includes(m.id)).length;
    };

    // Collapsed, the panel is a 44px rail. On a 1280px viewport that returns
    // ~250px to the canvas — the panel is mostly static readouts and toggles
    // set once per session, so it does not need to hold a third of the window.
    if (collapsed) {
      return (
        <Drawer
          anchor="right"
          variant="permanent"
          sx={{
            width: RAIL_WIDTH,
            flexShrink: 0,
            "& .MuiDrawer-paper": {
              width: RAIL_WIDTH,
              borderLeft: "1px solid",
              borderColor: "divider",
              bgcolor: isDark ? "#0a0f1a" : "#fafbfc",
              backgroundImage: "none",
              display: "flex",
              flexDirection: "column",
              alignItems: "center",
              gap: 2,
              py: 2,
            },
          }}
        >
          <Tooltip title="Show settings" placement="left" arrow>
            <IconButton
              onClick={() => onCollapsedChange(false)}
              aria-label="Show settings panel"
              size="small"
              sx={{ color: "text.secondary" }}
            >
              <PanelLeftOpen width={17} height={17} />
            </IconButton>
          </Tooltip>

          <Settings2 width={15} height={15} opacity={0.45} />

          {/* Selected models stay legible on the rail as family dots. */}
          <Box sx={{ display: "flex", flexDirection: "column", gap: 0.75, mt: 0.5 }}>
            {selectedModels.map((m) => (
              <Tooltip key={m} title={m} placement="left" arrow>
                <Box
                  sx={{
                    width: 9,
                    height: 9,
                    borderRadius: "50%",
                    bgcolor: modelFamilyColor(m),
                  }}
                />
              </Tooltip>
            ))}
          </Box>
        </Drawer>
      );
    }

    return (
      <Drawer
        anchor="right"
        variant="permanent"
        sx={{
          width: 280,
          flexShrink: 0,
          "& .MuiDrawer-paper": {
            width: 280,
            borderLeft: "1px solid",
            borderColor: "divider",
            bgcolor: isDark ? "#0a0f1a" : "#fafbfc",
            backgroundImage: "none",
            display: "flex",
            flexDirection: "column",
          },
        }}
      >
        {/* Header */}
        <Box
          sx={{
            px: 3,
            py: 2.5,
            borderBottom: "1px solid",
            borderColor: "divider",
            display: "flex",
            alignItems: "center",
            gap: 1.5,
          }}
        >
          <Settings2 width={16} height={16} />
          <Typography
            variant="overline"
            sx={{
              fontSize: "0.625rem",
              fontWeight: 900,
              letterSpacing: "0.15em",
              flex: 1,
            }}
          >
            Control Panel
          </Typography>
          <Tooltip title="Hide panel" placement="left" arrow>
            <IconButton
              onClick={() => onCollapsedChange(true)}
              aria-label="Hide settings panel"
              size="small"
              sx={{ color: "text.secondary", mr: -1 }}
            >
              <PanelLeftClose width={16} height={16} />
            </IconButton>
          </Tooltip>
        </Box>

        <Stack
          sx={{
            flex: 1,
            overflow: "auto",
            px: 3,
            py: 3,
            "&::-webkit-scrollbar": { display: "none" },
          }}
          spacing={4}
        >
          {/* Session Status */}
          <Box>
            <SectionHeader label="Status" />
            <Box
              sx={{
                p: 2.5,
                borderRadius: 2.5,
                border: "1px solid",
                borderColor: "divider",
                bgcolor: isDark ? "rgba(255,255,255,0.02)" : "rgba(0,0,0,0.02)",
              }}
            >
              <Stack spacing={2}>
                <StatusRow label="Models in this arena">
                  <Box sx={{ display: "flex", flexWrap: "wrap", gap: 0.75 }}>
                    {selectedModels.map((m) => {
                      const meta = getModelMetaFromId(m, families);
                      return (
                        <Box
                          key={m}
                          sx={{
                            display: "flex",
                            alignItems: "center",
                            gap: 0.75,
                            px: 1,
                            py: 0.25,
                            borderRadius: 1.5,
                            fontSize: "0.65rem",
                            fontWeight: 700,
                            letterSpacing: "0.05em",
                            textTransform: "uppercase",
                            border: `1px solid ${meta.activeBorder}`,
                            bgcolor: meta.activeBg,
                            color: meta.color,
                            maxWidth: "100%",
                            overflow: "hidden",
                            textOverflow: "ellipsis",
                            whiteSpace: "nowrap",
                          }}
                        >
                          <Box
                            sx={{
                              width: 5,
                              height: 5,
                              borderRadius: "50%",
                              bgcolor: meta.dotColor,
                              flexShrink: 0,
                            }}
                          />
                          {meta.label}
                        </Box>
                      );
                    })}
                  </Box>
                </StatusRow>

                <StatusRow label="Checkpoint">
                  <Typography
                    variant="caption"
                    sx={{
                      fontFamily: "monospace",
                      color: "text.secondary",
                      display: "block",
                      wordBreak: "break-all",
                      lineHeight: 1.4,
                    }}
                  >
                    {activeCheckpointLabel || "init"}
                  </Typography>
                </StatusRow>

                <Box
                  sx={{
                    display: "flex",
                    justifyContent: "space-between",
                    alignItems: "center",
                    pt: 1.5,
                    borderTop: "1px solid",
                    borderColor: "divider",
                  }}
                >
                  <Typography
                    variant="overline"
                    sx={{
                      fontSize: "0.7rem",
                      fontWeight: 700,
                      letterSpacing: "0.1em",
                      color: "text.secondary",
                    }}
                  >
                    Checkpoints
                  </Typography>
                  <Box
                    sx={{
                      px: 1.5,
                      py: 0.25,
                      borderRadius: 8,
                      fontSize: "0.75rem",
                      fontWeight: 700,
                      bgcolor: isDark
                        ? "rgba(255,255,255,0.08)"
                        : "rgba(0,0,0,0.05)",
                      color: "text.secondary",
                    }}
                  >
                    {messagesCount} nodes
                  </Box>
                </Box>
              </Stack>
            </Box>
          </Box>

          {/* Model selection — grouped by family */}
          <Box>
            <SectionHeader label="Available models" />
            {modelsLoading && (
              <Typography
                variant="caption"
                sx={{ color: "text.disabled", px: 1 }}
              >
                Loading models…
              </Typography>
            )}
            {modelsError && (
              <Box
                sx={{ display: "flex", alignItems: "center", gap: 1, px: 1 }}
              >
                <Typography
                  variant="caption"
                  sx={{ color: "error.main", flex: 1 }}
                >
                  Failed to load models.
                </Typography>
                <Typography
                  variant="caption"
                  sx={{
                    color: "primary.main",
                    cursor: "pointer",
                    fontWeight: 700,
                  }}
                  onClick={loadModels}
                >
                  Retry
                </Typography>
              </Box>
            )}
            <Stack spacing={1.5}>
              {families.map((family) => {
                const isExpanded = expandedFamilies.has(family.key);
                const count = selectedCount(family.key);
                const fc = getFamilyColors(family.color);

                return (
                  <Box key={family.key}>
                    {/* Family Header — click to expand */}
                    <ButtonBase
                      onClick={() => toggleFamily(family.key)}
                      sx={{
                        width: "100%",
                        display: "flex",
                        justifyContent: "space-between",
                        alignItems: "center",
                        px: 2,
                        py: 1.25,
                        borderRadius: 2,
                        textAlign: "left",
                        border: "1px solid",
                        transition: "all 0.2s",
                        borderColor:
                          count > 0
                            ? fc.activeBorder
                            : isDark
                              ? "rgba(255,255,255,0.04)"
                              : "divider",
                        bgcolor:
                          count > 0
                            ? fc.activeBg
                            : isDark
                              ? "rgba(255,255,255,0.01)"
                              : "background.paper",
                        "&:hover": { borderColor: fc.activeBorder },
                      }}
                    >
                      <Box
                        sx={{ display: "flex", alignItems: "center", gap: 1.5 }}
                      >
                        <Box
                          sx={{
                            width: 8,
                            height: 8,
                            borderRadius: "50%",
                            bgcolor: count > 0 ? fc.color : "text.disabled",
                            transition: "all 0.3s",
                          }}
                        />
                        <Box>
                          <Typography
                            variant="body2"
                            sx={{
                              fontWeight: 700,
                              color: count > 0 ? fc.color : "text.secondary",
                              fontSize: "0.9375rem",
                            }}
                          >
                            {family.label}
                          </Typography>
                          <Typography
                            variant="caption"
                            sx={{ fontSize: "0.7rem", color: "text.disabled" }}
                          >
                            {family.models.length} models
                            {!family.available && " · No API key"}
                          </Typography>
                        </Box>
                      </Box>
                      <Box
                        sx={{ display: "flex", alignItems: "center", gap: 1 }}
                      >
                        {count > 0 && (
                          <Box
                            sx={{
                              px: 0.75,
                              py: 0.125,
                              borderRadius: 1,
                              fontSize: "0.7rem",
                              fontWeight: 800,
                              bgcolor: fc.activeBg,
                              color: fc.color,
                              border: `1px solid ${fc.activeBorder}`,
                            }}
                          >
                            {count}
                          </Box>
                        )}
                        {isExpanded ? (
                          <ChevronDown width={14} height={14} />
                        ) : (
                          <ChevronRight width={14} height={14} />
                        )}
                      </Box>
                    </ButtonBase>

                    {/* Collapsible Model List */}
                    <Collapse in={isExpanded} timeout="auto">
                      <Stack spacing={0.5} sx={{ mt: 0.75, ml: 1.5 }}>
                        {family.models.map((model) => {
                          const isActive = selectedModels.includes(model.id);
                          return (
                            <ButtonBase
                              key={model.id}
                              onClick={() => handleModelToggle(model.id)}
                              disabled={!family.available}
                              sx={{
                                width: "100%",
                                display: "flex",
                                justifyContent: "space-between",
                                alignItems: "center",
                                px: 2,
                                py: 1,
                                borderRadius: 1.5,
                                textAlign: "left",
                                border: "1px solid",
                                transition: "all 0.2s",
                                opacity: family.available ? 1 : 0.4,
                                borderColor: isActive
                                  ? fc.activeBorder
                                  : "transparent",
                                bgcolor: isActive ? fc.activeBg : "transparent",
                                "&:hover": {
                                  bgcolor: isActive
                                    ? fc.activeBg
                                    : isDark
                                      ? "rgba(255,255,255,0.03)"
                                      : "rgba(0,0,0,0.02)",
                                },
                              }}
                            >
                              <Box
                                sx={{
                                  display: "flex",
                                  alignItems: "center",
                                  gap: 1.25,
                                  minWidth: 0,
                                }}
                              >
                                <Box
                                  sx={{
                                    width: 6,
                                    height: 6,
                                    borderRadius: "50%",
                                    flexShrink: 0,
                                    bgcolor: isActive
                                      ? fc.dotColor
                                      : "text.disabled",
                                    transition: "all 0.3s",
                                  }}
                                />
                                <Box sx={{ minWidth: 0 }}>
                                  <Typography
                                    variant="body2"
                                    sx={{
                                      fontWeight: 600,
                                      fontSize: "0.875rem",
                                      color: isActive
                                        ? fc.color
                                        : "text.secondary",
                                      whiteSpace: "nowrap",
                                      overflow: "hidden",
                                      textOverflow: "ellipsis",
                                    }}
                                  >
                                    {model.name}
                                  </Typography>
                                  <Typography
                                    variant="caption"
                                    sx={{
                                      fontSize: "0.65rem",
                                      color: "text.disabled",
                                      fontWeight: 600,
                                      textTransform: "uppercase",
                                      letterSpacing: "0.05em",
                                    }}
                                  >
                                    {model.desc}
                                  </Typography>
                                </Box>
                              </Box>
                              <Box
                                sx={{
                                  width: 14,
                                  height: 14,
                                  borderRadius: 1,
                                  border: "1px solid",
                                  flexShrink: 0,
                                  display: "flex",
                                  alignItems: "center",
                                  justifyContent: "center",
                                  borderColor: isActive
                                    ? fc.activeBorder
                                    : "divider",
                                  bgcolor: isActive
                                    ? fc.activeBg
                                    : "transparent",
                                }}
                              >
                                {isActive && (
                                  <Box
                                    sx={{
                                      width: 7,
                                      height: 7,
                                      borderRadius: 0.5,
                                      bgcolor: fc.dotColor,
                                    }}
                                  />
                                )}
                              </Box>
                            </ButtonBase>
                          );
                        })}
                      </Stack>
                    </Collapse>
                  </Box>
                );
              })}
            </Stack>
          </Box>

          {/* Toggles */}
          <Box>
            <SectionHeader label="Parameters" />
            <Stack spacing={1}>
              <ToggleRow
                isDark={isDark}
                label="Search my documents"
                subtitle="Looks through the documents you've uploaded and pulls in anything relevant before answering."
                icon={<BookOpen width={16} height={16} />}
                checked={toggles.use_rag}
                onChange={() =>
                  setToggles((prev) => ({
                    ...prev,
                    use_rag: !prev.use_rag,
                  }))
                }
              />
              <ToggleRow
                isDark={isDark}
                label="Web Search Grounding"
                subtitle="Allows the model to access the live internet to ground its answers using its native search tool."
                icon={<Globe width={16} height={16} />}
                checked={toggles.use_web_search}
                onChange={() =>
                  setToggles((prev) => ({
                    ...prev,
                    use_web_search: !prev.use_web_search,
                  }))
                }
              />
            </Stack>
          </Box>
          {/* Debate Defaults */}
          <Box>
            <SectionHeader label="Debate" />
            <Stack spacing={1.5}>
              <Box sx={{ display: "flex", alignItems: "center", gap: 1.5 }}>
                <Swords width={14} height={14} style={{ color: "#8b5cf6", flexShrink: 0 }} />
                <Typography variant="caption" sx={{ color: "text.secondary", lineHeight: 1.4 }}>
                  Default config for autonomous multi-model debates.
                </Typography>
              </Box>
              <Box sx={{ display: "flex", alignItems: "center", gap: 1.5 }}>
                <Typography variant="caption" sx={{ color: "text.secondary", minWidth: 80 }}>
                  Max rounds
                </Typography>
                <Box
                  component="input"
                  type="number"
                  min={1}
                  max={20}
                  value={debateDefaults.max_rounds}
                  onChange={(e: React.ChangeEvent<HTMLInputElement>) =>
                    setDebateDefaults((prev) => ({
                      ...prev,
                      max_rounds: Math.max(1, Math.min(20, parseInt(e.target.value) || 3)),
                    }))
                  }
                  sx={{
                    width: 56,
                    px: 1,
                    py: 0.5,
                    borderRadius: 1.5,
                    border: "1px solid",
                    borderColor: "divider",
                    bgcolor: "transparent",
                    color: "text.primary",
                    fontSize: "0.8rem",
                    outline: "none",
                    textAlign: "center",
                    "&:focus": { borderColor: "primary.main" },
                  }}
                />
              </Box>
              <ToggleRow
                isDark={isDark}
                label="Auto-Synthesize"
                subtitle="Automatically run a synthesis pass after all rounds complete."
                icon={<Swords width={16} height={16} />}
                checked={debateDefaults.auto_synthesize}
                onChange={() =>
                  setDebateDefaults((prev) => ({
                    ...prev,
                    auto_synthesize: !prev.auto_synthesize,
                  }))
                }
              />
              <ToggleRow
                isDark={isDark}
                label="Convergence Detection"
                subtitle="Stop early when model responses become semantically similar."
                icon={<Swords width={16} height={16} />}
                checked={debateDefaults.convergence_threshold !== null}
                onChange={() =>
                  setDebateDefaults((prev) => ({
                    ...prev,
                    convergence_threshold:
                      prev.convergence_threshold !== null ? null : 0.92,
                  }))
                }
              />
            </Stack>
          </Box>

          {/* API Keys */}
          <ApiKeysSection
            families={families}
            isDark={isDark}
            onSaved={loadModels}
          />
        </Stack>
      </Drawer>
    );
  },
);
ControlPanel.displayName = "ControlPanel";

export default ControlPanel;
