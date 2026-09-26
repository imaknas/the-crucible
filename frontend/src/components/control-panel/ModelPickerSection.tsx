import React, { useState } from "react";
import { Box, ButtonBase, Collapse, Stack, Typography } from "@mui/material";
import { ChevronDown, ChevronRight } from "lucide-react";
import type { ModelFamily } from "@/lib/api";
import type { CatalogStatus } from "@/hooks/useModelCatalog";
import { SectionHeader, getFamilyColors } from "./primitives";

/** The arena's model selection, grouped by provider family. At least one model stays selected. */
export default function ModelPickerSection({
  isDark,
  families,
  status,
  onRetry,
  selectedModels,
  setSelectedModels,
}: {
  isDark: boolean;
  families: ModelFamily[];
  status: CatalogStatus;
  onRetry: () => void;
  selectedModels: string[];
  setSelectedModels: (models: string[]) => void;
}) {
  const [expandedFamilies, setExpandedFamilies] = useState<Set<string>>(new Set());

  const handleModelToggle = (model: string) => {
    if (selectedModels.includes(model)) {
      if (selectedModels.length > 1) setSelectedModels(selectedModels.filter((m) => m !== model));
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
    return fam ? fam.models.filter((m) => selectedModels.includes(m.id)).length : 0;
  };

  return (
    <Box>
      <SectionHeader label="Available models" />
      {status === "loading" && (
        <Typography
          variant="caption"
          sx={{ color: "text.disabled", px: 1 }}
        >
          Loading models…
        </Typography>
      )}
      {status === "error" && (
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
            onClick={onRetry}
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
  );
}
