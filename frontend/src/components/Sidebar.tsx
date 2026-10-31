"use client";
import React from "react";
import {
  Box,
  ButtonBase,
  Drawer,
  Typography,
  Button,
  List,
  ListItemButton,
  ListItemText,
  IconButton,
  TextField,
  InputAdornment,
  useTheme,
} from "@mui/material";
import {
  Terminal,
  Zap,
  Check,
  X,
  Edit3,
  Trash2,
  Search,
  Swords,
  ChevronDown,
  ChevronRight,
  PanelLeftClose,
  PanelLeftOpen,
  Plus,
} from "lucide-react";
import type { PanelMode } from "@/hooks/useLayoutPanels";
import { searchHistory } from "@/lib/api";
import type { DebateSession, DebateUiStatus } from "@/lib/types";
import { sessionAge, sessionRowStatus } from "@/lib/debateTranscript";
import { motion, AnimatePresence } from "framer-motion";

interface Thread {
  id: string;
  title: string;
}

interface SidebarProps {
  threads: Thread[];
  threadId: string | null;
  onStartNewExperiment: () => void;
  onSwitchThread: (id: string) => void;
  onDeleteThread: (id: string) => void;
  /** Resolves true once the title is saved; the row leaves edit mode then. */
  onRenameThread: (id: string, newTitle: string) => Promise<boolean>;
  onSwitchCheckpoint: (id: string) => void;
  debateSessions?: DebateSession[];
  activeDebateSessionId?: string | null;
  /** Live status of the active debate; the server's record says "running" while paused. */
  activeDebateStatus?: DebateUiStatus | null;
  onSwitchDebateSession?: (sessionId: string) => void;
  onDeleteDebateSession?: (sessionId: string) => void;
  /** Human-facing model name; raw IDs belong in tooltips only. */
  modelLabel?: (modelId: string) => string;
  /** Docked beside the main pane, or an overlay drawer on narrow screens. */
  mode?: PanelMode;
  /** Overlay mode: whether the drawer is open. */
  open?: boolean;
  onClose?: () => void;
  /** Docked mode: shrunk to a rail. */
  collapsed?: boolean;
  onCollapsedChange?: (collapsed: boolean) => void;
}

const RAIL_WIDTH = 64;

const Sidebar: React.FC<SidebarProps> = React.memo(
  ({
    threads,
    threadId,
    onStartNewExperiment,
    onSwitchThread,
    onDeleteThread,
    onRenameThread,
    onSwitchCheckpoint,
    debateSessions = [],
    activeDebateSessionId,
    activeDebateStatus,
    onSwitchDebateSession,
    onDeleteDebateSession,
    modelLabel = (id: string) => id,
    mode = "docked",
    open = false,
    onClose,
    collapsed = false,
    onCollapsedChange,
  }) => {
    // In the overlay, picking something closes the drawer so you see it.
    const closeOverlay = () => {
      if (mode === "overlay") onClose?.();
    };
    const isDark = useTheme().palette.mode === "dark";
    // Which row is being renamed, and its draft title. Kept here: nothing
    // outside the sidebar needs it.
    const [editingThreadId, setEditingThreadId] = React.useState<string | null>(null);
    const [editingTitle, setEditingTitle] = React.useState("");
    const commitRename = async (id: string) => {
      if (await onRenameThread(id, editingTitle)) setEditingThreadId(null);
    };
    const [expandedDebateThreads, setExpandedDebateThreads] = React.useState<Set<string>>(new Set());
    const [searchQuery, setSearchQuery] = React.useState("");
    // "5 min ago" is read at render; a minute's drift is fine for a sidebar.
    const [now] = React.useState(() => Date.now());
    const [searchResults, setSearchResults] = React.useState<any[]>([]);
    const [isSearching, setIsSearching] = React.useState(false);

    // Group debates by parent thread
    const debatesByThread = React.useMemo(() => {
      const map = new Map<string, DebateSession[]>();
      for (const s of debateSessions) {
        const list = map.get(s.parent_thread_id) ?? [];
        list.push(s);
        map.set(s.parent_thread_id, list);
      }
      return map;
    }, [debateSessions]);

    // Auto-expand thread that has the active debate
    React.useEffect(() => {
      if (!activeDebateSessionId) return;
      const session = debateSessions.find((s) => s.session_id === activeDebateSessionId);
      if (session) {
        setExpandedDebateThreads((prev) => new Set([...prev, session.parent_thread_id]));
      }
    }, [activeDebateSessionId, debateSessions]);

    React.useEffect(() => {
      if (!threadId || searchQuery.length < 2) {
        setSearchResults([]);
        return;
      }
      const timer = setTimeout(async () => {
        setIsSearching(true);
        try {
          const { results } = await searchHistory(threadId, searchQuery);
          setSearchResults(results);
        } catch (err) {
          console.error("Search failed:", err);
        } finally {
          setIsSearching(false);
        }
      }, 400);
      return () => clearTimeout(timer);
    }, [searchQuery, threadId]);

    const toggleDebateExpand = (e: React.MouseEvent, tid: string) => {
      e.stopPropagation();
      setExpandedDebateThreads((prev) => {
        const next = new Set(prev);
        if (next.has(tid)) next.delete(tid);
        else next.add(tid);
        return next;
      });
    };

    // Docked and collapsed: a rail with the two things worth one click.
    if (mode === "docked" && collapsed) {
      return (
        <Box
          component="nav"
          aria-label="Sessions"
          sx={{
            width: RAIL_WIDTH,
            flexShrink: 0,
            display: "flex",
            flexDirection: "column",
            alignItems: "center",
            gap: 1.5,
            py: 2.5,
            borderRadius: "40px",
            border: "1px solid",
            borderColor: "divider",
            bgcolor: "background.paper",
          }}
        >
          <IconButton aria-label="Expand sessions" title="Expand sessions" onClick={() => onCollapsedChange?.(false)}>
            <PanelLeftOpen width={18} height={18} />
          </IconButton>
          <IconButton
            aria-label="New Session"
            title="New session"
            onClick={onStartNewExperiment}
            sx={{ bgcolor: "primary.main", color: "white", "&:hover": { bgcolor: "primary.dark" } }}
          >
            <Plus width={18} height={18} />
          </IconButton>
        </Box>
      );
    }

    const body = (
      <>
        {/* Header */}
        <Box
          sx={{
            px: mode === "overlay" ? 2.5 : 4,
            pt: mode === "overlay" ? 2.5 : 5,
            pb: mode === "overlay" ? 2 : 3,
            display: "flex",
            alignItems: "center",
            gap: 1.5,
            borderBottom: 1,
            borderColor: "divider",
          }}
        >
          <Box
            sx={{
              width: 40,
              height: 40,
              borderRadius: 3,
              bgcolor: "primary.dark",
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              boxShadow: "0 10px 15px -3px rgba(37, 99, 235, 0.15)",
            }}
          >
            <Terminal width={20} height={20} color="white" />
          </Box>
          <Box>
            <Typography
              variant="caption"
              sx={{ fontWeight: 800, letterSpacing: "0.15em", color: "primary.light" }}
            >
              SESSIONS
            </Typography>
            <Typography
              variant="overline"
              sx={{ display: "block", lineHeight: 1, color: "text.secondary", fontWeight: 600 }}
            >
              Research Log
            </Typography>
          </Box>
          {mode === "overlay" ? (
            <IconButton aria-label="Close sessions" onClick={onClose} sx={{ ml: "auto", color: "text.secondary" }}>
              <X width={18} height={18} />
            </IconButton>
          ) : (
            <IconButton
              aria-label="Collapse sessions"
              title="Collapse sessions"
              onClick={() => onCollapsedChange?.(true)}
              sx={{ ml: "auto", color: "text.secondary" }}
            >
              <PanelLeftClose width={18} height={18} />
            </IconButton>
          )}
        </Box>

        {/* Search Bar */}
        <Box sx={{ px: 2, pt: 1 }}>
          <TextField
            fullWidth
            size="small"
            disabled={!threadId}
            placeholder={threadId ? "Search this session…" : "Open a session to search"}
            inputProps={{ "aria-label": "Search this session's history" }}
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            InputProps={{
              startAdornment: (
                <InputAdornment position="start">
                  <Search
                    width={14}
                    height={14}
                    color={!threadId ? "text.disabled" : isDark ? "rgba(255,255,255,0.4)" : "rgba(0,0,0,0.3)"}
                  />
                </InputAdornment>
              ),
              endAdornment: searchQuery && (
                <InputAdornment position="end">
                  <IconButton size="small" aria-label="Clear search" onClick={() => setSearchQuery("")}>
                    <X width={12} height={12} />
                  </IconButton>
                </InputAdornment>
              ),
              sx: {
                borderRadius: "12px",
                fontSize: "0.75rem",
                bgcolor: isDark ? "rgba(255,255,255,0.03)" : "rgba(0,0,0,0.02)",
                "& fieldset": { borderColor: "transparent" },
                "&:hover fieldset": { borderColor: threadId ? "divider" : "transparent" },
                "&.Mui-focused fieldset": { borderColor: "primary.main" },
                opacity: threadId ? 1 : 0.6,
              },
            }}
          />
        </Box>

        {/* New Session Button */}
        <Box sx={{ px: 2.5, pt: 2, pb: 1 }}>
          <Button
            fullWidth
            variant="contained"
            onClick={() => {
              onStartNewExperiment();
              closeOverlay();
            }}
            startIcon={<Zap width={14} height={14} fill="currentColor" />}
            sx={{
              py: 1.2,
              borderRadius: 3,
              fontWeight: 800,
              letterSpacing: "0.05em",
              fontSize: "0.75rem",
              boxShadow: "0 10px 15px -3px rgba(37, 99, 235, 0.2)",
            }}
          >
            New Session
          </Button>
        </Box>

        {/* Main Content */}
        <Box sx={{ flex: 1, overflow: "hidden", display: "flex", flexDirection: "column" }}>
          {searchQuery.length >= 2 ? (
            <Box sx={{ flex: 1, display: "flex", flexDirection: "column", minHeight: 0 }}>
              <Box sx={{ px: 3, pt: 2, pb: 1, display: "flex", alignItems: "center", justifyContent: "space-between" }}>
                <Typography variant="overline" sx={{ fontWeight: 800, color: "primary.main", fontSize: "0.6875rem", letterSpacing: "0.1em" }}>
                  Search Results
                </Typography>
                {isSearching && (
                  <Box sx={{ width: 12, height: 12, borderRadius: "50%", border: "2px solid", borderTopColor: "primary.main", borderRightColor: "transparent", animation: "spin 1s linear infinite" }} />
                )}
              </Box>
              <List sx={{ flex: 1, overflow: "auto", px: 1.5, pt: 0 }}>
                {searchResults.length === 0 && !isSearching ? (
                  <Typography align="center" variant="caption" sx={{ display: "block", py: 4, color: "text.secondary" }}>
                    No matches found in this thread
                  </Typography>
                ) : (
                  searchResults.map((result) => (
                    <ListItemButton
                      component="button"
                      key={result.checkpoint_id}
                      onClick={() => { onSwitchCheckpoint(result.checkpoint_id); setSearchQuery(""); closeOverlay(); }}
                      sx={{
                        borderRadius: 3, mb: 0.5, flexDirection: "column", alignItems: "flex-start", py: 1.5, width: "100%", textAlign: "left",
                        border: "1px solid transparent",
                        "&:hover": { borderColor: "primary.main", bgcolor: isDark ? "rgba(37, 99, 235, 0.05)" : "primary.50" },
                      }}
                    >
                      <Box sx={{ display: "flex", alignItems: "center", gap: 1, mb: 0.5, width: "100%" }}>
                        <Box sx={{ width: 6, height: 6, borderRadius: "50%", bgcolor: result.role === "user" ? "primary.main" : "success.main" }} />
                        <Typography variant="caption" sx={{ fontWeight: 800, textTransform: "uppercase", fontSize: "0.6875rem", color: "text.secondary" }}>
                          {result.role === "user" ? "You" : result.model ? modelLabel(result.model) : "Assistant"}
                        </Typography>
                      </Box>
                      <Typography variant="body2" sx={{ fontSize: "0.75rem", color: "text.primary", lineHeight: 1.4, display: "-webkit-box", WebkitLineClamp: 2, WebkitBoxOrient: "vertical", overflow: "hidden", fontStyle: "italic", opacity: 0.8 }}>
                        {result.excerpt}
                      </Typography>
                    </ListItemButton>
                  ))
                )}
              </List>
            </Box>
          ) : (
            <List sx={{ flex: 1, overflow: "auto", px: 1.5, py: 1.5, "&::-webkit-scrollbar": { display: "none" } }}>
              <AnimatePresence mode="popLayout">
                {threads.length === 0 ? (
                  <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }}>
                    <Typography align="center" variant="caption" sx={{ display: "block", py: 8, color: "text.secondary", fontWeight: 500 }}>
                      No sessions yet
                    </Typography>
                  </motion.div>
                ) : (
                  threads.map((t) => {
                    const isActive = t.id === threadId;
                    const isEditing = editingThreadId === t.id;
                    const threadDebates = debatesByThread.get(t.id) ?? [];
                    const hasDebates = threadDebates.length > 0;
                    const isDebateExpanded = expandedDebateThreads.has(t.id);

                    return (
                      <Box
                        component={motion.div}
                        layout
                        initial={{ opacity: 0, x: -12 }}
                        animate={{ opacity: 1, x: 0 }}
                        exit={{ opacity: 0, scale: 0.96 }}
                        key={t.id}
                        sx={{ mb: 0.75 }}
                      >
                        {isEditing ? (
                          <Box sx={{ display: "flex", alignItems: "center", gap: 1, p: 0.5, borderRadius: 3, border: "1px solid", borderColor: "divider", bgcolor: isDark ? "rgba(0,0,0,0.2)" : "background.default" }}>
                            <TextField
                              autoFocus fullWidth variant="standard" size="small"
                              inputProps={{ "aria-label": "Session name" }}
                              value={editingTitle}
                              onChange={(e) => setEditingTitle(e.target.value)}
                              onKeyDown={(e) => {
                                if (e.key === "Enter") commitRename(t.id);
                                if (e.key === "Escape") setEditingThreadId(null);
                              }}
                              InputProps={{ disableUnderline: true, sx: { fontSize: "0.875rem", fontWeight: 600, px: 1 } }}
                            />
                            <IconButton size="small" aria-label="Save name" onClick={() => commitRename(t.id)} sx={{ color: "success.main" }}>
                              <Check width={14} height={14} />
                            </IconButton>
                            <IconButton size="small" aria-label="Cancel rename" onClick={() => setEditingThreadId(null)} sx={{ color: "error.main" }}>
                              <X width={14} height={14} />
                            </IconButton>
                          </Box>
                        ) : (
                          <>
                            <Box
                              sx={{
                                display: "flex",
                                alignItems: "center",
                                gap: 0.5,
                                pr: 1,
                                borderRadius: 3,
                                border: "1px solid",
                                borderColor: isActive ? "primary.main" : "transparent",
                                bgcolor: isActive ? (isDark ? "rgba(37, 99, 235, 0.1)" : "primary.50") : "transparent",
                                // Rename/delete appear on hover, whenever keyboard focus is in
                                // the row, and always on touch screens (no hover there).
                                "& .thread-edit": { display: "none" },
                                "&:hover, &:focus-within": {
                                  borderColor: isActive ? "primary.main" : "divider",
                                  "& .thread-edit": { display: "flex" },
                                },
                                "@media (hover: none)": { "& .thread-edit": { display: "flex" } },
                              }}
                            >
                              <ListItemButton
                                component="button"
                                onClick={() => {
                                  onSwitchThread(t.id);
                                  closeOverlay();
                                }}
                                aria-current={isActive ? "page" : undefined}
                                title={t.title}
                                sx={{ py: 1.5, pl: 2, pr: 1, flex: 1, minWidth: 0, borderRadius: 3, textAlign: "left" }}
                              >
                                <ListItemText
                                  primary={t.title}
                                  primaryTypographyProps={{ variant: "body2", fontWeight: 600, noWrap: true, sx: { color: isActive ? "primary.main" : "text.primary" } }}
                                />
                              </ListItemButton>
                              {hasDebates && (
                                <ButtonBase
                                  onClick={(e) => toggleDebateExpand(e, t.id)}
                                  aria-expanded={isDebateExpanded}
                                  aria-label={`${isDebateExpanded ? "Hide" : "Show"} ${threadDebates.length} debate${threadDebates.length === 1 ? "" : "s"}`}
                                  sx={{
                                    display: "flex", alignItems: "center", gap: 0.5, px: 0.75, py: 0.5, flexShrink: 0,
                                    borderRadius: 1.5,
                                    bgcolor: "rgba(139,92,246,0.12)",
                                    color: "#8b5cf6",
                                    "&:hover": { bgcolor: "rgba(139,92,246,0.22)" },
                                  }}
                                >
                                  <Swords width={11} height={11} />
                                  <Typography component="span" sx={{ fontSize: "0.6875rem", fontWeight: 700, lineHeight: 1 }}>
                                    {threadDebates.length}
                                  </Typography>
                                  {isDebateExpanded
                                    ? <ChevronDown width={11} height={11} />
                                    : <ChevronRight width={11} height={11} />
                                  }
                                </ButtonBase>
                              )}
                              <Box className="thread-edit" sx={{ alignItems: "center", flexShrink: 0 }}>
                                <IconButton size="small" aria-label="Rename session" onClick={(e) => { e.stopPropagation(); setEditingThreadId(t.id); setEditingTitle(t.title); }}>
                                  <Edit3 width={14} height={14} />
                                </IconButton>
                                <IconButton size="small" aria-label="Delete session" onClick={() => onDeleteThread(t.id)} sx={{ "&:hover": { color: "error.main" } }}>
                                  <Trash2 width={14} height={14} />
                                </IconButton>
                              </Box>
                            </Box>

                            {/* Debate sub-items */}
                            <AnimatePresence>
                              {hasDebates && isDebateExpanded && (
                                <motion.div
                                  initial={{ opacity: 0, height: 0 }}
                                  animate={{ opacity: 1, height: "auto" }}
                                  exit={{ opacity: 0, height: 0 }}
                                  style={{ overflow: "hidden" }}
                                >
                                  <Box sx={{ ml: 2, mt: 0.5, borderLeft: "2px solid rgba(139,92,246,0.25)", pl: 1.5, pb: 0.5 }}>
                                    {threadDebates.map((s) => {
                                      const isActiveDebate = s.session_id === activeDebateSessionId;
                                      const rowStatus = sessionRowStatus(s.status, isActiveDebate ? activeDebateStatus : null);
                                      const statusColor =
                                        rowStatus === "running" ? "#10b981" : rowStatus === "paused" || rowStatus === "pausing" ? "#f59e0b" : undefined;
                                      return (
                                        <Box
                                          key={s.session_id}
                                          aria-current={isActiveDebate ? "true" : undefined}
                                          sx={{
                                            position: "relative", borderRadius: 2, mb: 0.5,
                                            border: "1px solid",
                                            borderColor: isActiveDebate ? "rgba(139,92,246,0.5)" : "transparent",
                                            bgcolor: isActiveDebate ? "rgba(139,92,246,0.08)" : "transparent",
                                            "&:hover": { borderColor: "rgba(139,92,246,0.3)", bgcolor: "rgba(139,92,246,0.05)" },
                                          }}
                                        >
                                          <ListItemButton
                                            component="button"
                                            onClick={() => {
                                              onSwitchDebateSession?.(s.session_id);
                                              closeOverlay();
                                            }}
                                            sx={{ width: "100%", textAlign: "left", borderRadius: 2, py: 0.75, pl: 1.25, pr: 4.5 }}
                                          >
                                            <Box sx={{ width: "100%", minWidth: 0 }}>
                                              <Box sx={{ display: "flex", alignItems: "center", gap: 0.75, mb: 0.2 }}>
                                                <Swords width={11} height={11} color="#8b5cf6" style={{ flexShrink: 0 }} />
                                                {/* The question tells debates on one thread apart; the
                                                    participants alone made every row look the same. */}
                                                <Typography variant="caption" title={s.question ?? undefined} sx={{ fontWeight: 700, color: isActiveDebate ? "#a78bfa" : "text.primary", fontSize: "0.75rem", flex: 1, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                                                  {s.question || s.participants.map(modelLabel).join(" vs ")}
                                                </Typography>
                                                <Box sx={{ px: 0.75, py: 0.1, borderRadius: 1, fontSize: "0.6875rem", fontWeight: 700, flexShrink: 0, bgcolor: statusColor ? `${statusColor}26` : "rgba(100,116,139,0.15)", color: statusColor ?? "text.secondary" }}>
                                                  {rowStatus}
                                                </Box>
                                              </Box>
                                              <Typography variant="caption" title={s.participants.join(", ")} sx={{ display: "block", color: "text.secondary", fontSize: "0.6875rem", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                                                {[
                                                  s.question ? s.participants.map(modelLabel).join(" vs ") : null,
                                                  `${s.termination_policy.max_rounds} rounds`,
                                                  sessionAge(s.created_at, now),
                                                ]
                                                  .filter(Boolean)
                                                  .join(" · ")}
                                              </Typography>
                                            </Box>
                                          </ListItemButton>
                                          {onDeleteDebateSession && (
                                            <IconButton
                                              size="small"
                                              aria-label="Delete debate"
                                              onClick={() => onDeleteDebateSession(s.session_id)}
                                              sx={{ position: "absolute", top: 4, right: 4, p: 0.5, color: "text.secondary", "&:hover": { color: "error.main" } }}
                                            >
                                              <Trash2 width={12} height={12} />
                                            </IconButton>
                                          )}
                                        </Box>
                                      );
                                    })}
                                  </Box>
                                </motion.div>
                              )}
                            </AnimatePresence>
                          </>
                        )}
                      </Box>
                    );
                  })
                )}
              </AnimatePresence>
            </List>
          )}
        </Box>
      </>
    );

    if (mode === "overlay") {
      return (
        <Drawer
          variant="temporary"
          anchor="left"
          open={open}
          onClose={onClose}
          ModalProps={{ keepMounted: true }}
          PaperProps={{
            component: "nav",
            "aria-label": "Sessions",
            sx: {
              width: "min(320px, 88vw)",
              backgroundColor: "background.paper",
              backgroundImage: "none",
              display: "flex",
              flexDirection: "column",
            },
          } as object}
        >
          {body}
        </Drawer>
      );
    }

    return (
      <Drawer
        variant="permanent"
        PaperProps={{
          component: "nav",
          "aria-label": "Sessions",
          sx: {
            position: "relative",
            width: 288,
            flexShrink: 0,
            borderRadius: "40px",
            border: "1px solid",
            borderColor: "divider",
            backgroundColor: "background.paper",
            backdropFilter: "blur(16px)",
            overflow: "hidden",
            zIndex: 20,
          },
        } as object}
      >
        {body}
      </Drawer>
    );
  },
);
Sidebar.displayName = "Sidebar";

export default Sidebar;
