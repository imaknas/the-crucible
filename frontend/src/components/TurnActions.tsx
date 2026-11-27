import React from "react";
import { Box, ButtonBase, ListSubheader, Menu, MenuItem, TextField } from "@mui/material";
import { CornerDownRight, Plus } from "lucide-react";

/**
 * The controls a finished turn's answers share, on compare cards and on a
 * single-model reply: add one more model to the turn, and the mark on the
 * reply the next message continues.
 */

const quietSx = {
  px: 1,
  py: 0.5,
  minHeight: 28,
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
  /** The provider a model belongs to: the menu is grouped under them. */
  groupOf?: (id: string) => string;
}

/**
 * "+ Add a model": ask one more model this turn's question, without asking
 * the others again. Lists models by display name (the id is a tooltip).
 */
export function AddModelMenu({ options, modelLabel, disabled = false, onAdd, id, groupOf }: AddModelProps) {
  const [anchor, setAnchor] = React.useState<HTMLElement | null>(null);
  const [filter, setFilter] = React.useState("");
  if (!options.length) return null;
  const menuId = `add-model-menu-${id}`;
  const needle = filter.trim().toLowerCase();
  const shown = options.filter((m) => !needle || modelLabel(m).toLowerCase().includes(needle) || m.includes(needle));
  // Grouped by provider, in the catalogue's order: it was one flat list of
  // some thirty models that ran off the screen.
  const groups: [string, string[]][] = [];
  for (const model of shown) {
    const group = groupOf?.(model) ?? "";
    const last = groups[groups.length - 1];
    if (last && last[0] === group) last[1].push(model);
    else groups.push([group, [model]]);
  }
  const close = () => {
    setAnchor(null);
    setFilter("");
  };
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
        onClose={close}
        autoFocus={options.length <= 8}
        slotProps={{
          list: { "aria-label": "Model to add to this turn", dense: true },
          paper: { sx: { maxHeight: 420, minWidth: 240 } },
        }}
      >
        {options.length > 8 && (
          <Box sx={{ px: 1.5, pt: 0.5, pb: 1 }} onKeyDown={(e) => e.stopPropagation()}>
            <TextField
              size="small"
              fullWidth
              autoFocus
              placeholder="Filter models"
              value={filter}
              onChange={(e) => setFilter(e.target.value)}
              slotProps={{ htmlInput: { "aria-label": "Filter models" } }}
            />
          </Box>
        )}
        {groups.flatMap(([group, models]) => [
          ...(group
            ? [
                <ListSubheader key={`h-${group}`} sx={{ lineHeight: "28px", fontSize: "0.75rem" }}>
                  {group}
                </ListSubheader>,
              ]
            : []),
          ...models.map((model) => (
            <MenuItem
              key={model}
              title={model}
              onClick={() => {
                close();
                onAdd(model);
              }}
              sx={{ fontSize: "0.85rem" }}
            >
              {modelLabel(model)}
            </MenuItem>
          )),
        ])}
        {!shown.length && (
          <MenuItem disabled sx={{ fontSize: "0.85rem" }}>
            No model matches
          </MenuItem>
        )}
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
  selectedCount = 0,
}: {
  /** The reply's checkpoint, to tell several replies' menus apart. */
  id: string;
  /** The reply's model, by display name. */
  label: string;
  primary: boolean;
  answerers: string;
  addModel: { options: string[]; disabled: boolean; onAdd: (model: string) => void; groupOf?: (id: string) => string } | null;
  onContinueAll?: () => void;
  modelLabel: (id: string) => string;
  /** How many models are selected: "Continue with all 3". */
  selectedCount?: number;
}) {
  const adds = !!addModel && addModel.options.length > 0;
  if (!primary && !adds && !onContinueAll) return null;
  return (
    <Box
      data-testid="reply-actions"
      sx={{ display: "flex", flexWrap: "wrap", alignItems: "center", gap: 1, mt: -1, px: 1 }}
    >
      {primary && <NextHereMark answerers={answerers} />}
      {onContinueAll && <ContinueAllButton onClick={onContinueAll} label={label} count={selectedCount} />}
      {adds && (
        <AddModelMenu
          id={id}
          options={addModel!.options}
          modelLabel={modelLabel}
          disabled={addModel!.disabled}
          groupOf={addModel!.groupOf}
          onAdd={addModel!.onAdd}
        />
      )}
    </Box>
  );
}

/**
 * "Continue with all 3": this reply becomes the branch point, and every
 * selected model answers. It read "Everyone continues from here" in spaced
 * capitals beside "Continue from this", and the two were hard to tell apart.
 */
export function ContinueAllButton({ onClick, label, count }: { onClick: () => void; label: string; count: number }) {
  const name = count > 1 ? `Continue with all ${count}` : "Continue with every selected model";
  return (
    <ButtonBase
      onClick={onClick}
      aria-label={name}
      title={`Your next message continues ${label}'s answer, and every selected model answers it`}
      sx={{ ...quietSx, fontSize: "0.8125rem", fontWeight: 600, minHeight: 28 }}
    >
      {name}
    </ButtonBase>
  );
}
