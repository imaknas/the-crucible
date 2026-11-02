import React, { useState } from "react";
import {
  Box,
  Button,
  ButtonBase,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  Divider,
  ListItemIcon,
  ListItemText,
  Menu,
  MenuItem,
  TextField,
  Typography,
} from "@mui/material";
import { ChevronsDown, ChevronsUp, Focus, Layers, PencilLine, Star, StarOff, Trash2, X } from "lucide-react";
import { RADIUS } from "@/theme";

/** What a person can write on tree nodes (useNodeNotes). */
export interface NodeNoteActions {
  rename: (id: string, name: string) => void;
  setBookmark: (id: string, bookmarked: boolean) => void;
  summarize: (id: string) => void;
  clearSummary: (id: string) => void;
  /** Nodes whose subtree is being summarized now. */
  summarizing: string[];
}

export const NAME_MAX_CHARS = 80;

interface NodeMenuProps {
  anchor: HTMLElement | null;
  onClose: () => void;
  name: string | null;
  bookmarked: boolean;
  hasSummary: boolean;
  /** Messages below it; nothing to collapse, show alone or summarize without them. */
  below: number;
  collapsed: boolean;
  hoisted: boolean;
  summarizing: boolean;
  onRename: () => void;
  onBookmark: (bookmarked: boolean) => void;
  onCollapse: (collapsed: boolean) => void;
  onHoist: (hoist: boolean) => void;
  onSummarize: () => void;
  onClearSummary: () => void;
}

/** A node's menu: name its branch, bookmark it, fold it away, show it alone, compress it into a summary. */
export function NodeMenu(p: NodeMenuProps) {
  const act = (fn: () => void) => () => {
    p.onClose();
    fn();
  };
  return (
    <Menu anchorEl={p.anchor} open={!!p.anchor} onClose={p.onClose} slotProps={{ paper: { sx: { minWidth: 240 } } }}>
      <MenuItem onClick={act(p.onRename)}>
        <ListItemIcon>
          <PencilLine size={16} />
        </ListItemIcon>
        <ListItemText>{p.name ? "Rename branch…" : "Name this branch…"}</ListItemText>
      </MenuItem>
      <MenuItem onClick={act(() => p.onBookmark(!p.bookmarked))}>
        <ListItemIcon>{p.bookmarked ? <StarOff size={16} /> : <Star size={16} />}</ListItemIcon>
        <ListItemText>{p.bookmarked ? "Remove bookmark" : "Bookmark"}</ListItemText>
      </MenuItem>
      {p.below > 0 && <Divider />}
      {p.below > 0 && (
        <MenuItem onClick={act(() => p.onCollapse(!p.collapsed))}>
          <ListItemIcon>{p.collapsed ? <ChevronsDown size={16} /> : <ChevronsUp size={16} />}</ListItemIcon>
          <ListItemText secondary={p.collapsed ? undefined : `Hides ${p.below} message${p.below === 1 ? "" : "s"}`}>
            {p.collapsed ? "Expand" : "Collapse"}
          </ListItemText>
        </MenuItem>
      )}
      {p.below > 0 && (
        <MenuItem onClick={act(() => p.onHoist(!p.hoisted))}>
          <ListItemIcon>
            <Focus size={16} />
          </ListItemIcon>
          <ListItemText>{p.hoisted ? "Show the whole tree" : "Show only this branch"}</ListItemText>
        </MenuItem>
      )}
      {p.below > 0 && (
        <MenuItem onClick={act(p.onSummarize)} disabled={p.summarizing}>
          <ListItemIcon>
            <Layers size={16} />
          </ListItemIcon>
          <ListItemText secondary="One call to the summarizer model; the conversation is unchanged">
            {p.hasSummary ? "Summarize again" : "Compress into a summary"}
          </ListItemText>
        </MenuItem>
      )}
      {p.hasSummary && (
        <MenuItem onClick={act(p.onClearSummary)}>
          <ListItemIcon>
            <Trash2 size={16} />
          </ListItemIcon>
          <ListItemText>Remove the summary</ListItemText>
        </MenuItem>
      )}
    </Menu>
  );
}

/** Naming a branch; an empty name removes it. */
export function RenameDialog({
  initial,
  onSave,
  onClose,
}: {
  initial: string;
  onSave: (name: string) => void;
  onClose: () => void;
}) {
  const [name, setName] = useState(initial);
  const save = () => {
    onSave(name.trim());
    onClose();
  };
  return (
    <Dialog open onClose={onClose} fullWidth maxWidth="xs">
      <DialogTitle>Name this branch</DialogTitle>
      <DialogContent>
        <TextField
          autoFocus
          fullWidth
          margin="dense"
          label="Branch name"
          value={name}
          onChange={(e) => setName(e.target.value.slice(0, NAME_MAX_CHARS))}
          onKeyDown={(e) => {
            if (e.key === "Enter") save();
          }}
          helperText="Shown on the node and in the bookmarks. Leave it empty to remove the name."
        />
      </DialogContent>
      <DialogActions>
        <Button onClick={onClose}>Cancel</Button>
        <Button variant="contained" onClick={save}>
          Save
        </Button>
      </DialogActions>
    </Dialog>
  );
}

const barSx = {
  display: "flex",
  alignItems: "center",
  gap: 0.75,
  px: 1,
  py: 0.5,
  borderRadius: `${RADIUS.md}px`,
  border: "1px solid",
  borderColor: "divider",
  bgcolor: "background.paper",
  boxShadow: "0 4px 16px rgba(0,0,0,0.08)",
  maxWidth: "100%",
  minWidth: 0,
};

/** The canvas's top-left corner: the hoisted branch (with the way back) and the bookmarks to jump to. */
export function TreeNavBar({
  hoistedLabel,
  onUnhoist,
  marks,
  onJump,
}: {
  hoistedLabel: string | null;
  onUnhoist: () => void;
  marks: { id: string; label: string }[];
  onJump: (id: string) => void;
}) {
  if (!hoistedLabel && !marks.length) return null;
  return (
    <Box
      sx={{
        position: "absolute",
        top: 12,
        left: 12,
        zIndex: 6,
        display: "flex",
        flexDirection: "column",
        gap: 0.75,
        maxWidth: "min(420px, calc(100% - 24px))",
      }}
    >
      {hoistedLabel && (
        <Box sx={barSx} data-testid="hoist-bar">
          <Focus size={13} aria-hidden style={{ flexShrink: 0 }} />
          <Typography noWrap sx={{ fontSize: "0.75rem", minWidth: 0 }}>
            Showing one branch: <b>{hoistedLabel}</b>
          </Typography>
          <ButtonBase
            onClick={onUnhoist}
            sx={{
              display: "flex",
              alignItems: "center",
              gap: 0.5,
              ml: "auto",
              px: 0.75,
              borderRadius: 1,
              fontSize: "0.75rem",
              fontWeight: 700,
              color: "primary.main",
              flexShrink: 0,
            }}
          >
            <X size={12} aria-hidden />
            Show whole tree
          </ButtonBase>
        </Box>
      )}
      {marks.length > 0 && (
        <Box sx={{ ...barSx, flexWrap: "wrap" }} role="navigation" aria-label="Bookmarks">
          <Star size={13} fill="#f59e0b" color="#f59e0b" aria-hidden style={{ flexShrink: 0 }} />
          {marks.map((m) => (
            <ButtonBase
              key={m.id}
              onClick={() => onJump(m.id)}
              title={`Go to: ${m.label}`}
              sx={{
                px: 0.75,
                py: 0.25,
                borderRadius: 1,
                fontSize: "0.75rem",
                fontWeight: 600,
                maxWidth: 160,
                overflow: "hidden",
                textOverflow: "ellipsis",
                whiteSpace: "nowrap",
                display: "block",
                "&:hover": { bgcolor: "action.hover" },
              }}
            >
              {m.label}
            </ButtonBase>
          ))}
        </Box>
      )}
    </Box>
  );
}
