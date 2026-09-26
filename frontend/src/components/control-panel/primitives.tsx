import React from "react";
import { alpha, Box, Switch, Typography } from "@mui/material";
import type { ModelFamily } from "@/lib/api";

/** Shared building blocks for the Control Panel sections. */

export function getFamilyColors(familyColor: string) {
  return {
    color: familyColor,
    dotColor: familyColor,
    activeBg: alpha(familyColor, 0.1),
    activeBorder: alpha(familyColor, 0.3),
  };
}

export function getModelMetaFromId(model: string, families: ModelFamily[]) {
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

/** Mirrors backend FAMILY_META env_key: which API key each family needs. */
export const FAMILY_ENV_KEY: Record<string, string> = {
  openai: "OPENAI_API_KEY",
  anthropic: "ANTHROPIC_API_KEY",
  google: "GOOGLE_API_KEY",
};

export function SectionHeader({ label }: { label: string }) {
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

export function StatusRow({
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

export function ToggleRow({
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
