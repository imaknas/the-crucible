"use client";
import { createTheme } from "@mui/material/styles";

/**
 * Corner radii in px, for values set outside MUI's `sx` (inline styles, React
 * Flow nodes, globals.css). Inside `sx`, `borderRadius: n` means n ×
 * `shape.borderRadius` (4px): 1.5 = 6, 2 = 8, 3 = 12, 4 = 16.
 */
export const RADIUS = {
  /** chips, badges */
  sm: 6,
  /** buttons, inputs, small controls */
  md: 8,
  /** cards, tree nodes, message bubbles */
  lg: 12,
  /** the app's outer panels */
  panel: 16,
} as const;

const baseTheme = {
  typography: {
    fontFamily: "var(--font-inter), sans-serif",
    fontSize: 16,
    h1: { fontSize: "2.5rem" },
    h2: { fontSize: "2rem" },
    h3: { fontSize: "1.75rem" },
    h4: { fontSize: "1.5rem" },
    h5: { fontSize: "1.25rem" },
    h6: { fontSize: "1.125rem" },
    body1: { fontSize: "1.1rem" },
    body2: { fontSize: "1rem" },
    button: {
      textTransform: "none" as const,
      fontWeight: 600,
      fontSize: "0.9375rem",
    },
    caption: { fontSize: "0.875rem" },
    overline: { fontSize: "0.75rem" },
  },
  shape: {
    borderRadius: 4,
  },
};

export const darkTheme = createTheme({
  ...baseTheme,
  palette: {
    mode: "dark",
    // Blue is text as well as fills (theme.test.ts measures both): blue-400
    // reads 7.5:1 on the dark background, and filled buttons carry dark text
    // (7.4:1); blue-500 was 4.3:1 on the tinted rows and 3.7:1 under white.
    primary: {
      main: "#60a5fa", // blue-400
      light: "#93c5fd", // blue-300
      dark: "#3b82f6", // blue-500
      contrastText: "#0b1220",
    },
    background: {
      default: "#0a0f1e", // Very dark blue/black
      paper: "rgba(255, 255, 255, 0.03)", // Glassmorphic base
    },
    divider: "rgba(255, 255, 255, 0.06)",
    text: {
      primary: "#f1f5f9", // slate-100
      secondary: "#94a3b8", // slate-400
    },
  },
  components: {
    MuiCssBaseline: {
      styleOverrides: {
        body: {
          backgroundColor: "#0a0f1e",
          backgroundImage:
            "radial-gradient(ellipse at 50% -20%, rgba(59, 130, 246, 0.15), transparent 60%)",
          backgroundAttachment: "fixed",
        },
      },
    },
    MuiPaper: {
      styleOverrides: {
        root: {
          backdropFilter: "blur(16px)",
          border: "1px solid rgba(255, 255, 255, 0.06)",
          backgroundImage: "none", // Remove MUI default overlay
        },
      },
    },
    MuiButton: {
      styleOverrides: {
        root: {
          borderRadius: RADIUS.md,
        },
      },
    },
  },
});

export const lightTheme = createTheme({
  ...baseTheme,
  palette: {
    mode: "light",
    // blue-600 is 5.2:1 on white, as text and under white text; blue-500
    // (3.7:1) failed both wherever the app used `primary`.
    primary: {
      main: "#2563eb", // blue-600
      light: "#3b82f6", // blue-500: decoration only, never text
      dark: "#1d4ed8", // blue-700
      contrastText: "#ffffff",
    },
    background: {
      default: "#f8fafc", // slate-50
      paper: "#ffffff",
    },
    divider: "#e2e8f0", // slate-200
    text: {
      primary: "#0f172a", // slate-900
      // Between slate-500 and -600: slate-500 (#64748b) fell under 4.5:1 on
      // the tinted cards and chips it labels.
      secondary: "#56657a",
    },
  },
  components: {
    MuiCssBaseline: {
      styleOverrides: {
        body: {
          backgroundColor: "#f8fafc",
          backgroundImage:
            "radial-gradient(ellipse at 50% -20%, rgba(59, 130, 246, 0.05), transparent 60%)",
          backgroundAttachment: "fixed",
        },
      },
    },
    MuiPaper: {
      styleOverrides: {
        root: {
          backdropFilter: "blur(16px)",
          border: "1px solid #e2e8f0",
          boxShadow:
            "0 4px 6px -1px rgb(0 0 0 / 0.05), 0 2px 4px -2px rgb(0 0 0 / 0.05)",
        },
      },
    },
    MuiButton: {
      styleOverrides: {
        root: {
          borderRadius: RADIUS.md,
        },
      },
    },
  },
});
