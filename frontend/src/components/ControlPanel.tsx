import React from "react";
import { Box, Drawer, IconButton, Stack, Tooltip, Typography, useTheme } from "@mui/material";
import { PanelLeftClose, PanelLeftOpen, Settings2 } from "lucide-react";
import type { ModelFamily } from "@/lib/api";
import type { DebateDefaults, Toggles } from "@/lib/types";
import type { CatalogStatus } from "@/hooks/useModelCatalog";
import { modelFamilyColor } from "@/lib/colors";
import StatusSection from "./control-panel/StatusSection";
import ModelPickerSection from "./control-panel/ModelPickerSection";
import ParametersSection from "./control-panel/ParametersSection";
import DebateDefaultsSection from "./control-panel/DebateDefaultsSection";
import ApiKeysSection from "./control-panel/ApiKeysSection";

interface ControlPanelProps {
  toggles: Toggles;
  setToggles: React.Dispatch<React.SetStateAction<Toggles>>;
  families: ModelFamily[];
  modelsStatus: CatalogStatus;
  onReloadModels: () => void;
  selectedModels: string[];
  setSelectedModels: (models: string[]) => void;
  messagesCount: number;
  activeCheckpointLabel: string;
  debateDefaults: DebateDefaults;
  setDebateDefaults: (next: DebateDefaults | ((prev: DebateDefaults) => DebateDefaults)) => void;
  collapsed: boolean;
  onCollapsedChange: (collapsed: boolean) => void;
}

/** Width of the collapsed rail. */
export const RAIL_WIDTH = 44;

/**
 * The right-hand settings panel: a shell (collapsed rail or full drawer) that
 * lays out one component per section from ./control-panel/.
 */
const ControlPanel: React.FC<ControlPanelProps> = React.memo(
  ({
    toggles,
    setToggles,
    families,
    modelsStatus,
    onReloadModels,
    selectedModels,
    setSelectedModels,
    messagesCount,
    activeCheckpointLabel,
    debateDefaults,
    setDebateDefaults,
    collapsed,
    onCollapsedChange,
  }) => {
    const isDark = useTheme().palette.mode === "dark";

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
          <StatusSection
            isDark={isDark}
            families={families}
            selectedModels={selectedModels}
            activeCheckpointLabel={activeCheckpointLabel}
            messagesCount={messagesCount}
          />
          <ModelPickerSection
            isDark={isDark}
            families={families}
            status={modelsStatus}
            onRetry={onReloadModels}
            selectedModels={selectedModels}
            setSelectedModels={setSelectedModels}
          />
          <ParametersSection isDark={isDark} toggles={toggles} setToggles={setToggles} />
          <DebateDefaultsSection
            isDark={isDark}
            debateDefaults={debateDefaults}
            setDebateDefaults={setDebateDefaults}
          />
          <ApiKeysSection families={families} isDark={isDark} onSaved={onReloadModels} />
        </Stack>
      </Drawer>
    );
  },
);
ControlPanel.displayName = "ControlPanel";

export default ControlPanel;
