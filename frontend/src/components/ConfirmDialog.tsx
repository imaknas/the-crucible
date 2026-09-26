import React from "react";
import {
  Button,
  Dialog,
  DialogActions,
  DialogContent,
  DialogContentText,
  DialogTitle,
} from "@mui/material";
import { useThemeMode } from "@/components/ThemeRegistry";
import type { ConfirmRequest } from "@/hooks/useConfirm";

/** Destructive-action confirmation, driven by useConfirm(). */
export default function ConfirmDialog({
  request,
  onAnswer,
}: {
  request: ConfirmRequest | null;
  onAnswer: (accepted: boolean) => void;
}) {
  const { isDark } = useThemeMode();
  return (
    <Dialog
      open={!!request}
      onClose={() => onAnswer(false)}
      PaperProps={{
        sx: {
          borderRadius: 3,
          bgcolor: isDark ? "#111827" : "#fff",
          border: "1px solid",
          borderColor: isDark ? "rgba(255,255,255,0.08)" : "divider",
          minWidth: 360,
          backgroundImage: "none",
        },
      }}
      slotProps={{
        backdrop: {
          sx: { backdropFilter: "blur(4px)", bgcolor: "rgba(0,0,0,0.5)" },
        },
      }}
    >
      <DialogTitle sx={{ fontWeight: 700, fontSize: "1rem", pb: 0.5 }}>
        {request?.title}
      </DialogTitle>
      <DialogContent>
        <DialogContentText sx={{ fontSize: "0.85rem", color: "text.secondary" }}>
          {request?.message}
        </DialogContentText>
      </DialogContent>
      <DialogActions sx={{ px: 3, pb: 2.5, gap: 1 }}>
        <Button
          onClick={() => onAnswer(false)}
          size="small"
          sx={{ textTransform: "none", fontWeight: 600, color: "text.secondary" }}
        >
          Cancel
        </Button>
        <Button
          onClick={() => onAnswer(true)}
          variant="contained"
          size="small"
          color="error"
          sx={{
            textTransform: "none",
            fontWeight: 700,
            borderRadius: 2,
            px: 2.5,
            boxShadow: "none",
            "&:hover": { boxShadow: "none" },
          }}
        >
          Confirm
        </Button>
      </DialogActions>
    </Dialog>
  );
}
