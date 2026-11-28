import React from "react";
import { Box, Button, ButtonBase, Chip, Popover, TextField, Tooltip, Typography } from "@mui/material";
import { Crosshair, X } from "lucide-react";
import { ANGLE_SUGGESTIONS } from "@/lib/angles";

/**
 * The composer's "Angles": the angle each model that answers the next
 * message takes (lib/angles). One field per model; a suggestion fills the
 * first empty field. Angles go with the next message only, like attachments.
 */
export function AnglesButton({
  models,
  angles,
  onChange,
  modelLabel,
  maxChars,
  disabled = false,
}: {
  /** Who answers the next message. */
  models: string[];
  angles: Record<string, string>;
  onChange: (angles: Record<string, string>) => void;
  modelLabel: (id: string) => string;
  maxChars?: number;
  disabled?: boolean;
}) {
  const [anchor, setAnchor] = React.useState<HTMLElement | null>(null);
  const set = Object.values(angles).filter((a) => a.trim()).length;
  const suggest = (text: string) => {
    const empty = models.find((m) => !angles[m]?.trim());
    if (empty) onChange({ ...angles, [empty]: text });
  };
  return (
    <>
      <Tooltip title="Give each model its own angle on your next message, e.g. to review a plan from several sides" placement="top" arrow>
        <span>
          <ButtonBase
            aria-haspopup="dialog"
            disabled={disabled}
            onClick={(e) => setAnchor(e.currentTarget)}
            sx={{
              display: "flex",
              alignItems: "center",
              gap: 0.5,
              px: 1,
              py: 0.75,
              borderRadius: 2,
              fontSize: "0.8125rem",
              fontWeight: 700,
              color: set ? "primary.main" : "text.secondary",
              "&:hover": { bgcolor: "action.hover" },
              "&.Mui-disabled": { opacity: 0.5 },
            }}
          >
            <Crosshair width={15} height={15} />
            <Box component="span">{set ? `Angles (${set})` : "Angles"}</Box>
          </ButtonBase>
        </span>
      </Tooltip>
      <Popover
        open={!!anchor}
        anchorEl={anchor}
        onClose={() => setAnchor(null)}
        anchorOrigin={{ vertical: "top", horizontal: "left" }}
        transformOrigin={{ vertical: "bottom", horizontal: "left" }}
        slotProps={{ paper: { role: "dialog", "aria-label": "Angles for the next message", sx: { p: 2, width: 360, maxWidth: "calc(100vw - 32px)" } } }}
      >
        <Typography sx={{ fontSize: "0.875rem", fontWeight: 700, mb: 0.5 }}>Angles for the next message</Typography>
        <Typography sx={{ fontSize: "0.75rem", color: "text.secondary", mb: 1.5 }}>
          Every model gets the same message; each answers from its own angle. To collect what they raise, use
          &ldquo;List every problem raised&rdquo; under the answers.
        </Typography>
        <Box sx={{ display: "flex", flexDirection: "column", gap: 1.25 }}>
          {models.map((m) => (
            <TextField
              key={m}
              size="small"
              label={modelLabel(m)}
              value={angles[m] ?? ""}
              onChange={(e) => onChange({ ...angles, [m]: e.target.value })}
              placeholder="e.g. its security"
              slotProps={{ htmlInput: maxChars ? { maxLength: maxChars } : {} }}
            />
          ))}
        </Box>
        <Box sx={{ display: "flex", flexWrap: "wrap", gap: 0.75, mt: 1.5 }} aria-label="Suggestions">
          {ANGLE_SUGGESTIONS.map((s) => (
            <Chip
              key={s}
              label={s}
              size="small"
              variant="outlined"
              onClick={() => suggest(s)}
              disabled={models.every((m) => angles[m]?.trim())}
              sx={{ fontSize: "0.75rem" }}
            />
          ))}
        </Box>
        <Box sx={{ display: "flex", justifyContent: "space-between", mt: 2 }}>
          <Button size="small" onClick={() => onChange({})} disabled={!set}>
            Clear all
          </Button>
          <Button size="small" variant="contained" onClick={() => setAnchor(null)}>
            Done
          </Button>
        </Box>
      </Popover>
    </>
  );
}

/** The angles set for the next message, as removable chips above the text box. */
export function AngleChips({
  angles,
  onChange,
  modelLabel,
}: {
  angles: Record<string, string>;
  onChange: (angles: Record<string, string>) => void;
  modelLabel: (id: string) => string;
}) {
  return (
    <>
      {Object.entries(angles).map(([model, angle]) => (
        <Chip
          key={model}
          size="small"
          label={`${modelLabel(model)}: ${angle}`}
          icon={<Crosshair width={12} height={12} style={{ marginLeft: 8, color: "inherit" }} />}
          onDelete={() => onChange(Object.fromEntries(Object.entries(angles).filter(([m]) => m !== model)))}
          deleteIcon={<X width={12} height={12} aria-label={`Remove ${modelLabel(model)}'s angle`} />}
          sx={{ fontSize: "0.75rem", fontWeight: 600, color: "text.secondary", borderRadius: 1.5, maxWidth: "100%" }}
        />
      ))}
    </>
  );
}
