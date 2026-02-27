import React, { useEffect } from "react";
import {
  Snackbar,
  Alert,
  Typography,
  Box,
  IconButton,
  useTheme,
} from "@mui/material";
import { X } from "lucide-react";

export interface ToastData {
  id: string;
  message: string;
  model?: string;
}

interface ToastProps extends ToastData {
  index: number;
  onDismiss: (id: string) => void;
}

const Toast: React.FC<ToastProps> = ({
  id,
  message,
  model,
  index,
  onDismiss,
}) => {
  const isDark = useTheme().palette.mode === "dark";

  useEffect(() => {
    const timer = setTimeout(() => onDismiss(id), 6000);
    return () => clearTimeout(timer);
  }, [id, onDismiss]);

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
        severity="error"
        variant="filled"
        icon={false}
        action={
          <IconButton
            size="small"
            aria-label="close"
            color="inherit"
            onClick={() => onDismiss(id)}
          >
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
          borderColor: "error.main",
          boxShadow: isDark
            ? "0 4px 40px rgba(220,38,38,0.3)"
            : "0 4px 30px rgba(220,38,38,0.15)",
          "& .MuiAlert-message": { flex: 1, py: 0, minWidth: 0 },
        }}
      >
        <Box sx={{ display: "flex", flexDirection: "column", gap: 0.5 }}>
          <Typography
            variant="overline"
            sx={{
              color: "error.main",
              fontWeight: 800,
              lineHeight: 1,
              mb: 0.5,
            }}
          >
            {model ? `${model} Error` : "System Error"}
          </Typography>
          <Typography
            variant="caption"
            sx={{
              fontFamily: "monospace",
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
