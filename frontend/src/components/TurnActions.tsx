import React from "react";
import { Box, ButtonBase, Menu, MenuItem } from "@mui/material";
import { CornerDownRight, Plus } from "lucide-react";

/**
 * The controls a finished turn's answers share, on compare cards and on a
 * single-model reply: add one more model to the turn, and the mark on the
 * reply the next message continues.
 */

const quietSx = {
  px: 1,
  py: 0.5,
  borderRadius: 1.5,
  fontSize: "0.75rem",
  fontWeight: 700,
  gap: 0.5,
  color: "text.secondary",
  "&:hover": { bgcolor: "action.hover", color: "text.primary" },
  "&[aria-disabled='true']": { opacity: 0.6, cursor: "default" },
};

interface AddModelProps {
  /** Models that can still answer the turn (with a key, not already in it). */
  options: string[];
  modelLabel: (id: string) => string;
  /** Another turn is running: say so instead of sending. */
  disabled?: boolean;
  onAdd: (model: string) => void;
  /** Distinguishes the menus of several turns for assistive tech. */
  id: string;
}

/**
 * "+ Add a model": ask one more model this turn's question, without asking
 * the others again. Lists models by display name (the id is a tooltip).
 */
export function AddModelMenu({ options, modelLabel, disabled = false, onAdd, id }: AddModelProps) {
  const [anchor, setAnchor] = React.useState<HTMLElement | null>(null);
  if (!options.length) return null;
  const menuId = `add-model-menu-${id}`;
  return (
    <>
      <ButtonBase
        onClick={(e) => {
          if (!disabled) setAnchor(e.currentTarget);
        }}
        aria-disabled={disabled}
        aria-haspopup="menu"
        aria-expanded={!!anchor}
        aria-controls={anchor ? menuId : undefined}
        title={
          disabled
            ? "Available once the models have finished answering"
            : "Ask one more model this question; the others aren't asked again"
        }
        sx={quietSx}
      >
        <Plus width={12} height={12} aria-hidden />
        Add a model
      </ButtonBase>
      <Menu
        id={menuId}
        anchorEl={anchor}
        open={!!anchor}
        onClose={() => setAnchor(null)}
        slotProps={{ list: { "aria-label": "Model to add to this turn" } }}
      >
        {options.map((model) => (
          <MenuItem
            key={model}
            title={model}
            onClick={() => {
              setAnchor(null);
              onAdd(model);
            }}
            sx={{ fontSize: "0.85rem" }}
          >
            {modelLabel(model)}
          </MenuItem>
        ))}
      </Menu>
    </>
  );
}

/** Who answers next, in words: "Claude Sonnet 5.5", "GPT and Claude Sonnet 5.5". */
export function answererNames(models: string[], modelLabel: (id: string) => string): string {
  const names = models.map(modelLabel);
  return names.length <= 1 ? (names[0] ?? "") : `${names.slice(0, -1).join(", ")} and ${names[names.length - 1]}`;
}

/**
 * The reply the next message continues (the branch point a click or "Continue
 * from this" chose). Nothing carries it while the next message continues the
 * latest turn, where each model continues its own reply.
 */
export function NextHereMark({ answerers, color }: { answerers: string; color?: string }) {
  return (
    <Box
      data-testid="next-here"
      title={answerers ? `Your next message continues this answer; ${answerers} will answer it` : undefined}
      sx={{
        display: "flex",
        alignItems: "center",
        gap: 0.5,
        fontSize: "0.6875rem",
        fontWeight: 700,
        color: color ?? "primary.main",
        whiteSpace: "nowrap",
      }}
    >
      <CornerDownRight width={12} height={12} aria-hidden />
      Next message continues here
    </Box>
  );
}

/**
 * Under a single-model reply: the mark when the next message continues it,
 * "Everyone continues from here", and "+ Add a model" (which turns the
 * reply into a turn of compare cards).
 */
export function ReplyTurnActions({
  id,
  label,
  primary,
  answerers,
  addModel,
  onContinueAll,
  modelLabel,
}: {
  /** The reply's checkpoint, to tell several replies' menus apart. */
  id: string;
  /** The reply's model, by display name. */
  label: string;
  primary: boolean;
  answerers: string;
  addModel: { options: string[]; disabled: boolean; onAdd: (model: string) => void } | null;
  onContinueAll?: () => void;
  modelLabel: (id: string) => string;
}) {
  const adds = !!addModel && addModel.options.length > 0;
  if (!primary && !adds && !onContinueAll) return null;
  return (
    <Box
      data-testid="reply-actions"
      sx={{ display: "flex", flexWrap: "wrap", alignItems: "center", gap: 1, mt: -1, px: 1 }}
    >
      {primary && <NextHereMark answerers={answerers} />}
      {onContinueAll && <ContinueAllButton onClick={onContinueAll} label={label} />}
      {adds && (
        <AddModelMenu
          id={id}
          options={addModel!.options}
          modelLabel={modelLabel}
          disabled={addModel!.disabled}
          onAdd={addModel!.onAdd}
        />
      )}
    </Box>
  );
}

/** "Everyone continues from here": this reply becomes the branch point, and every selected model answers. */
export function ContinueAllButton({ onClick, label }: { onClick: () => void; label: string }) {
  return (
    <ButtonBase
      onClick={onClick}
      title={`Continue from ${label}'s answer with every selected model`}
      sx={{
        ...quietSx,
        fontSize: "0.7rem",
        fontWeight: 800,
        textTransform: "uppercase",
        letterSpacing: "0.08em",
      }}
    >
      Everyone continues from here
    </ButtonBase>
  );
}
