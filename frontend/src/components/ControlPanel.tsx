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
} from "@mui/material";
import {
  Settings2,
  Brain,
  BookOpen,
  ChevronDown,
  ChevronRight,
} from "lucide-react";
import { fetchModels, ModelFamily } from "@/lib/api";

interface ControlPanelProps {
  toggles: {
    strict_logic: boolean;
  };
  setToggles: React.Dispatch<
    React.SetStateAction<{
      strict_logic: boolean;
    }>
  >;
  selectedModels: string[];
  setSelectedModels: (models: string[]) => void;
  messagesCount: number;
  threadId: string | null;
  activeCheckpointLabel: string;
}

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

// ─── Main Component ──────────────────────────────────────────────

const ControlPanel: React.FC<ControlPanelProps> = React.memo(
  ({
    toggles,
    setToggles,
    selectedModels,
    setSelectedModels,
    messagesCount,
    threadId,
    activeCheckpointLabel,
  }) => {
    const isDark = useTheme().palette.mode === "dark";
    const [families, setFamilies] = useState<ModelFamily[]>([]);
    const [expandedFamilies, setExpandedFamilies] = useState<Set<string>>(
      new Set(),
    );

    useEffect(() => {
      fetchModels()
        .then((data) => setFamilies(data.families))
        .catch(() => {
          // Fallback to empty — UI will show nothing
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

    return (
      <Drawer
        anchor="right"
        variant="permanent"
        sx={{
          width: 280,
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
            }}
          >
            Control Panel
          </Typography>
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
                <StatusRow label="Active Council">
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
                    Tree Size
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

          {/* Council Selection — Grouped by Family */}
          <Box>
            <SectionHeader label="Council Members" />
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
                label="Strict Logic"
                subtitle="Enables native Extended Thinking / Reasoning for flagship models (Opus, Sonnet, GPT-5)."
                icon={<Brain width={16} height={16} />}
                checked={toggles.strict_logic}
                onChange={() =>
                  setToggles((prev) => ({
                    ...prev,
                    strict_logic: !prev.strict_logic,
                  }))
                }
              />
            </Stack>
          </Box>
        </Stack>
      </Drawer>
    );
  },
);

export default ControlPanel;
