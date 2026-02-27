import React from "react";
import {
  Dialog,
  DialogTitle,
  DialogContent,
  DialogActions,
  Box,
  Typography,
  Button,
  IconButton,
  useTheme,
} from "@mui/material";
import { Settings2, Zap, Terminal } from "lucide-react";

interface ErrorModalProps {
  title: string;
  details: string;
  suggestion?: string;
  onDismiss: () => void;
}

const ErrorModal: React.FC<ErrorModalProps> = ({
  title,
  details,
  suggestion,
  onDismiss,
}) => {
  const isDark = useTheme().palette.mode === "dark";
  return (
    <Dialog
      open={true}
      onClose={onDismiss}
      maxWidth="sm"
      fullWidth
      PaperProps={{
        sx: {
          borderRadius: 2.5,
          border: "1px solid",
          borderColor: isDark ? "rgba(220, 38, 38, 0.3)" : "error.light",
          bgcolor: isDark ? "#0f172a" : "background.paper",
          backgroundImage: "none",
          boxShadow: isDark ? "0 25px 50px -12px rgba(220, 38, 38, 0.25)" : 24,
          overflow: "hidden",
        },
      }}
    >
      <Box
        sx={{
          height: 6,
          width: "100%",
          background: "linear-gradient(to right, #dc2626, #f97316, #dc2626)",
        }}
      />

      <DialogTitle
        sx={{
          px: 4,
          pt: 4,
          pb: 2,
          display: "flex",
          alignItems: "center",
          gap: 2,
        }}
      >
        <Box
          sx={{
            p: 1.5,
            borderRadius: 2,
            bgcolor: isDark ? "rgba(239, 68, 68, 0.1)" : "error.50",
          }}
        >
          <Settings2 width={24} height={24} color="#ef4444" />
        </Box>
        <Box>
          <Typography
            variant="subtitle1"
            sx={{
              fontWeight: 900,
              textTransform: "uppercase",
              letterSpacing: "0.1em",
              color: isDark ? "text.primary" : "text.primary",
            }}
          >
            {title}
          </Typography>
          <Box sx={{ height: 2, width: 48, bgcolor: "error.main", mt: 0.5 }} />
        </Box>
      </DialogTitle>

      <DialogContent sx={{ px: 4, pb: 2 }}>
        <Box
          sx={{
            position: "relative",
            p: 2.5,
            borderRadius: 2,
            mb: 3,
            border: "1px solid",
            borderColor: isDark ? "rgba(239, 68, 68, 0.2)" : "error.light",
            bgcolor: isDark ? "rgba(0, 0, 0, 0.6)" : "error.50",
            color: isDark ? "error.light" : "error.main",
            overflow: "hidden",
          }}
        >
          <Typography
            variant="caption"
            sx={{
              position: "relative",
              zIndex: 10,
              fontFamily: "monospace",
              whiteSpace: "pre-wrap",
              display: "block",
              maxHeight: 200,
              overflow: "auto",
            }}
          >
            {details}
          </Typography>
          <Terminal
            width={96}
            height={96}
            style={{
              position: "absolute",
              bottom: -16,
              right: -16,
              opacity: 0.05,
              pointerEvents: "none",
            }}
          />
        </Box>

        {suggestion && (
          <Box
            sx={{
              display: "flex",
              alignItems: "flex-start",
              gap: 1.5,
              p: 2,
              borderRadius: 2,
              mb: 1,
              bgcolor: isDark ? "rgba(59, 130, 246, 0.05)" : "primary.50",
              border: "1px solid",
              borderColor: isDark ? "rgba(59, 130, 246, 0.1)" : "primary.100",
              color: isDark ? "primary.light" : "primary.main",
            }}
          >
            <Zap
              width={16}
              height={16}
              style={{ marginTop: 2, flexShrink: 0 }}
            />
            <Typography
              variant="caption"
              sx={{ fontWeight: 500, lineHeight: 1.6 }}
            >
              <Box
                component="span"
                sx={{
                  fontWeight: 800,
                  textTransform: "uppercase",
                  letterSpacing: "-0.05em",
                  mr: 1,
                }}
              >
                Recovery Info:
              </Box>
              {suggestion}
            </Typography>
          </Box>
        )}
      </DialogContent>

      <DialogActions sx={{ px: 4, pb: 4, pt: 1, gap: 2 }}>
        <Button
          fullWidth
          variant="outlined"
          onClick={() => navigator.clipboard.writeText(`${title}: ${details}`)}
          sx={{
            py: 1.5,
            borderRadius: 2,
            fontSize: "0.625rem",
            fontWeight: 900,
            textTransform: "uppercase",
            letterSpacing: "0.1em",
            color: isDark ? "text.secondary" : "text.secondary",
            borderColor: isDark ? "divider" : "divider",
            "&:hover": {
              bgcolor: isDark ? "rgba(255, 255, 255, 0.05)" : "action.hover",
              color: isDark ? "text.primary" : "text.primary",
            },
          }}
        >
          Copy Log
        </Button>
        <Button
          fullWidth
          variant="contained"
          color="error"
          onClick={onDismiss}
          sx={{
            py: 1.5,
            borderRadius: 2,
            fontSize: "0.625rem",
            fontWeight: 900,
            textTransform: "uppercase",
            letterSpacing: "0.1em",
            boxShadow: "0 10px 15px -3px rgba(220, 38, 38, 0.2)",
          }}
        >
          Dismiss
        </Button>
      </DialogActions>
    </Dialog>
  );
};

export default ErrorModal;
