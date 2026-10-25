import { useCallback, useState } from "react";
import { useMediaQuery, useTheme } from "@mui/material";
import { useStoredValue, writeStoredValue } from "@/hooks/useStoredValue";

const SIDEBAR_KEY = "crucible_sidebar_collapsed";
const PANEL_KEY = "crucible_panel_collapsed";

/**
 * How the two side panels (sessions on the left, settings on the right) are
 * laid out.
 *
 * Below the md breakpoint there is no room to dock either: both become
 * overlay drawers, closed by default and opened from the header. A fixed
 * 288px sidebar plus a 280px panel left the composer 4px wide at 820px and
 * the app unusable on a phone. On wider screens both dock, and each can be
 * collapsed to a rail (remembered across reloads).
 */
export function useLayoutPanels() {
  const theme = useTheme();
  const compact = useMediaQuery(theme.breakpoints.down("md"));

  const sidebarCollapsed = useStoredValue(SIDEBAR_KEY) === "1";
  const panelCollapsed = useStoredValue(PANEL_KEY) === "1";
  const setSidebarCollapsed = useCallback((next: boolean) => writeStoredValue(SIDEBAR_KEY, next ? "1" : "0"), []);
  const setPanelCollapsed = useCallback((next: boolean) => writeStoredValue(PANEL_KEY, next ? "1" : "0"), []);

  // Overlay drawers only; they start closed on every load.
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const [panelOpen, setPanelOpen] = useState(false);

  return {
    compact,
    sidebar: {
      mode: compact ? ("overlay" as const) : ("docked" as const),
      open: sidebarOpen,
      setOpen: setSidebarOpen,
      collapsed: !compact && sidebarCollapsed,
      setCollapsed: setSidebarCollapsed,
    },
    panel: {
      mode: compact ? ("overlay" as const) : ("docked" as const),
      open: panelOpen,
      setOpen: setPanelOpen,
      collapsed: !compact && panelCollapsed,
      setCollapsed: setPanelCollapsed,
    },
  };
}

export type PanelMode = "docked" | "overlay";
