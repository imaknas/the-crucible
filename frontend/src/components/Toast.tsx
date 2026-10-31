import React, { useEffect } from "react";
import { Snackbar, Alert, Typography, Box, IconButton, useTheme } from "@mui/material";
import { X } from "lucide-react";

/**
 * What a notice is about. A confirmation ("Session deleted") used to share the
 * red "System Error" look with real failures, so successes read as errors.
 */
export type ToastKind = "error" | "success" | "info";

export interface ToastData {
  id: string;
  message: string;
  kind: ToastKind;
  /** Overrides the heading, e.g. the model a failure came from. */
  title?: string;
}

interface ToastProps extends ToastData {
  index: number;
  onDismiss: (id: string) => void;
}

const HEADING: Record<ToastKind, string> = {
  error: "Something went wrong",
  success: "Done",
  info: "Note",
};

/** Errors stay up longer: they usually need reading. */
const DURATION_MS: Record<ToastKind, number> = { error: 8000, success: 4000, info: 6000 };

const Toast: React.FC<ToastProps> = ({ id, message, kind, title, index, onDismiss }) => {
  const isDark = useTheme().palette.mode === "dark";

  useEffect(() => {
    const timer = setTimeout(() => onDismiss(id), DURATION_MS[kind]);
    return () => clearTimeout(timer);
  }, [id, kind, onDismiss]);

  return (
    <Snackbar
      open={true}
      anchorOrigin={{ vertical: "bottom", horizontal: "right" }}
      sx={{
        bottom: { xs: `${24 + index * 88}px !important` },
        right: { xs: "24px !important" },
      }}
    >
      <Alert
        severity={kind}
        variant="outlined"
        role={kind === "error" ? "alert" : "status"}
        icon={false}
        data-kind={kind}
        action={
          <IconButton size="small" aria-label="Dismiss notification" color="inherit" onClick={() => onDismiss(id)}>
            <X width={16} height={16} />
          </IconButton>
        }
        sx={{
          minWidth: 300,
          maxWidth: 400,
          alignItems: "flex-start",
          borderRadius: 2.5,
          bgcolor: isDark ? "#0f172a" : "#ffffff",
          color: "text.primary",
          border: "1px solid",
          borderColor: `${kind}.main`,
          boxShadow: isDark ? "0 4px 40px rgba(0,0,0,0.4)" : "0 4px 30px rgba(0,0,0,0.12)",
          "& .MuiAlert-message": { flex: 1, py: 0, minWidth: 0 },
        }}
      >
        <Box sx={{ display: "flex", flexDirection: "column", gap: 0.5 }}>
          <Typography
            variant="overline"
            sx={{ color: isDark ? `${kind}.light` : `${kind}.dark`, fontWeight: 800, lineHeight: 1, mb: 0.5 }}
          >
            {title ?? HEADING[kind]}
          </Typography>
          <Typography
            variant="caption"
            sx={{
              display: "-webkit-box",
              WebkitLineClamp: 4,
              WebkitBoxOrient: "vertical",
              overflow: "hidden",
              lineHeight: 1.5,
              wordBreak: "break-word",
            }}
          >
            {message}
          </Typography>
        </Box>
      </Alert>
    </Snackbar>
  );
};

export default Toast;
