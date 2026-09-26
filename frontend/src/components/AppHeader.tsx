import React from "react";
import { motion } from "framer-motion";
import { Box, ButtonBase, IconButton, Typography } from "@mui/material";
import { Layers, MessagesSquare, Moon, Sun, Zap } from "lucide-react";
import { useThemeMode } from "@/components/ThemeRegistry";
import { modelFamilyColor } from "@/lib/colors";
import type { ConnectionTone } from "@/hooks/useBackendStatus";

/**
 * Top bar of the main pane: title (which returns to the landing view), the
 * real connection/key status, the selected models, the Tree/Arena view switch
 * and the theme toggle.
 */
export default function AppHeader({
  connection,
  selectedModels,
  showTree,
  onShowTreeChange,
  onHome,
}: {
  connection: { tone: ConnectionTone; label: string };
  selectedModels: string[];
  showTree: boolean;
  onShowTreeChange: (tree: boolean) => void;
  onHome: () => void;
}) {
  const { isDark, toggleMode } = useThemeMode();
  return (
    <Box
      component="header"
      sx={{
        px: { xs: 3, md: 5 },
        py: 3,
        display: "flex",
        justifyContent: "space-between",
        alignItems: "center",
        position: "relative",
        zIndex: 20,
        borderBottom: "1px solid",
        borderColor: "divider",
        bgcolor: isDark
          ? "rgba(255, 255, 255, 0.01)"
          : "rgba(255, 255, 255, 0.6)",
        boxShadow: isDark
          ? "0 4px 30px rgba(0, 0, 0, 0.1)"
          : "0 4px 30px rgba(0, 0, 0, 0.03)",
      }}
    >
      <ButtonBase
        onClick={onHome}
        sx={{
          display: "flex",
          alignItems: "center",
          gap: 2,
          textAlign: "left",
          borderRadius: 3,
          p: 0.5,
          ml: -0.5,
          transition: "all 0.2s ease",
          "&:hover": {
            bgcolor: isDark ? "rgba(255,255,255,0.05)" : "rgba(0,0,0,0.03)",
          },
        }}
      >
        <Box
          sx={{
            width: 44,
            height: 44,
            borderRadius: 3.5,
            background: isDark
              ? "linear-gradient(135deg, rgba(37,99,235,0.8), rgba(124,58,237,0.8))"
              : "linear-gradient(135deg, #2563eb, #7c3aed)",
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            boxShadow: isDark
              ? "0 8px 24px -6px rgba(124,58,237,0.4), inset 0 1px 1px rgba(255,255,255,0.2)"
              : "0 8px 24px -6px rgba(37,99,235,0.4), inset 0 1px 1px rgba(255,255,255,0.4)",
          }}
        >
          <Zap width={22} height={22} color="white" />
        </Box>

        <Box>
          <Typography
            variant="h6"
            sx={{
              fontWeight: 900,
              letterSpacing: "0.15em",
              lineHeight: 1.1,
              color: "text.primary",
            }}
          >
            THE CRUCIBLE
          </Typography>
          <Box
            sx={{
              display: "flex",
              alignItems: "center",
              gap: 0.75,
              mt: 0.5,
            }}
          >
            <Box
              sx={{
                width: 6,
                height: 6,
                borderRadius: "50%",
                bgcolor:
                  connection.tone === "ok"
                    ? "success.main"
                    : connection.tone === "warn"
                      ? "warning.main"
                      : "error.main",
                boxShadow:
                  connection.tone === "ok"
                    ? "0 0 8px rgba(16,185,129,0.5)"
                    : "none",
              }}
            />
            <Typography
              variant="overline"
              sx={{
                fontSize: "0.6rem",
                fontWeight: 800,
                letterSpacing: "0.2em",
                color: "text.secondary",
                lineHeight: 1,
              }}
            >
              {connection.label}
            </Typography>
          </Box>
        </Box>
      </ButtonBase>

      <Box sx={{ display: "flex", alignItems: "center", gap: 2 }}>
        <Box
          sx={{
            display: { xs: "none", sm: "flex" },
            alignItems: "center",
            gap: 1.5,
            px: 1.5,
            py: 0.75,
            borderRadius: 1.5,
            border: "1px solid",
            borderColor: "divider",
            bgcolor: isDark ? "rgba(255,255,255,0.03)" : "rgba(0,0,0,0.02)",
          }}
        >
          <Box sx={{ display: "flex", mr: 0.5 }}>
            {selectedModels.map((m, i) => (
              <Box
                key={m}
                sx={{
                  width: 10,
                  height: 10,
                  borderRadius: "50%",
                  ml: i > 0 ? -0.75 : 0,
                  border: "2px solid",
                  borderColor: "background.paper",
                  bgcolor: modelFamilyColor(m),
                  boxShadow: "0 2px 4px rgba(0,0,0,0.1)",
                }}
              />
            ))}
          </Box>
          <Typography
            variant="overline"
            sx={{
              fontSize: "0.6rem",
              fontWeight: 800,
              letterSpacing: "0.1em",
              color: "text.secondary",
              lineHeight: 1,
            }}
          >
            {selectedModels.length === 1
              ? selectedModels[0].split("-")[0].toUpperCase()
              : `${selectedModels.length} models`}
          </Typography>
        </Box>

        {/* Segmented, so the lit half states the CURRENT view. The old
            single button was labelled with its destination, which reads
            both ways and was routinely misread. */}
        <Box
          role="group"
          aria-label="View"
          sx={{
            display: "flex",
            p: 0.375,
            gap: 0.375,
            borderRadius: 2.5,
            border: "1px solid",
            borderColor: "divider",
            bgcolor: isDark ? "rgba(255,255,255,0.03)" : "rgba(0,0,0,0.03)",
          }}
        >
          {(
            [
              { key: "tree", label: "Tree", icon: Layers },
              { key: "arena", label: "Arena", icon: MessagesSquare },
            ] as const
          ).map(({ key, label, icon: Icon }) => {
            const active = key === "tree" ? showTree : !showTree;
            return (
              <ButtonBase
                key={key}
                onClick={() => onShowTreeChange(key === "tree")}
                aria-pressed={active}
                sx={{
                  px: 1.75,
                  py: 0.75,
                  borderRadius: 2,
                  display: "flex",
                  alignItems: "center",
                  gap: 0.75,
                  fontWeight: 800,
                  fontSize: "0.625rem",
                  letterSpacing: "0.14em",
                  textTransform: "uppercase",
                  transition: "background-color .18s ease, color .18s ease",
                  color: active
                    ? isDark
                      ? "primary.light"
                      : "primary.main"
                    : "text.secondary",
                  bgcolor: active
                    ? isDark
                      ? "rgba(37,99,235,0.16)"
                      : "primary.50"
                    : "transparent",
                  "&:hover": {
                    bgcolor: active
                      ? isDark
                        ? "rgba(37,99,235,0.22)"
                        : "primary.100"
                      : isDark
                        ? "rgba(255,255,255,0.05)"
                        : "rgba(0,0,0,0.04)",
                  },
                }}
              >
                <Icon width={13} height={13} />
                {label}
              </ButtonBase>
            );
          })}
        </Box>

        <IconButton
          component={motion.button}
          whileHover={{ scale: 1.1, rotate: 15 }}
          whileTap={{ scale: 0.9 }}
          onClick={toggleMode}
          aria-label={isDark ? "Switch to light theme" : "Switch to dark theme"}
          sx={{
            border: "1px solid",
            borderColor: "divider",
            bgcolor: isDark ? "rgba(255,255,255,0.03)" : "background.paper",
            color: isDark ? "#fbbf24" : "text.secondary",
            "&:hover": {
              bgcolor: isDark ? "rgba(255,255,255,0.08)" : "divider",
            },
          }}
        >
          {isDark ? (
            <Sun width={18} height={18} />
          ) : (
            <Moon width={18} height={18} />
          )}
        </IconButton>
      </Box>
    </Box>
  );
}
