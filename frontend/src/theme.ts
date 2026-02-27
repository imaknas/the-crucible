"use client";
import { createTheme } from "@mui/material/styles";

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
    borderRadius: 16,
  },
};

export const darkTheme = createTheme({
  ...baseTheme,
  palette: {
    mode: "dark",
    primary: {
      main: "#3b82f6", // blue-500
      light: "#60a5fa", // blue-400
      dark: "#2563eb", // blue-600
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
          borderRadius: 9999, // Pill shape
        },
      },
    },
  },
});

export const lightTheme = createTheme({
  ...baseTheme,
  palette: {
    mode: "light",
    primary: {
      main: "#3b82f6",
      light: "#60a5fa",
      dark: "#2563eb",
    },
    background: {
      default: "#f8fafc", // slate-50
      paper: "#ffffff",
    },
    divider: "#e2e8f0", // slate-200
    text: {
      primary: "#0f172a", // slate-900
      secondary: "#64748b", // slate-500
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
          borderRadius: 9999,
        },
      },
    },
  },
});
