import React from "react";
import {
  Box,
  Drawer,
  Typography,
  Button,
  List,
  ListItem,
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
  Target,
} from "lucide-react";
import { searchHistory } from "@/lib/api";
import { motion, AnimatePresence } from "framer-motion";

interface Thread {
  id: string;
  title: string;
}

interface SidebarProps {
  threads: Thread[];
  threadId: string | null;
  editingThreadId: string | null;
  editingTitle: string;
  onStartNewExperiment: () => void;
  onSwitchThread: (id: string) => void;
  onDeleteThread: (e: React.MouseEvent, id: string) => void;
  onRenameThread: (id: string, newTitle: string) => void;
  setEditingThreadId: (id: string | null) => void;
  setEditingTitle: (title: string) => void;
  onSwitchCheckpoint: (id: string) => void;
}

const Sidebar: React.FC<SidebarProps> = React.memo(
  ({
    threads,
    threadId,
    editingThreadId,
    editingTitle,
    onStartNewExperiment,
    onSwitchThread,
    onDeleteThread,
    onRenameThread,
    setEditingThreadId,
    setEditingTitle,
    onSwitchCheckpoint,
  }) => {
    const isDark = useTheme().palette.mode === "dark";
    const [searchQuery, setSearchQuery] = React.useState("");
    const [searchResults, setSearchResults] = React.useState<any[]>([]);
    const [isSearching, setIsSearching] = React.useState(false);

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
    return (
      <Drawer
        variant="permanent"
        PaperProps={{
          sx: {
            position: "relative",
            width: 288, // w-72
            flexShrink: 0,
            borderRadius: "40px",
            border: "1px solid",
            borderColor: "divider",
            backgroundColor: "background.paper",
            backdropFilter: "blur(16px)",
            overflow: "hidden",
            zIndex: 20,
          },
        }}
      >
        {/* Header */}
        <Box
          sx={{
            px: 4,
            pt: 5,
            pb: 3,
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
              sx={{
                fontWeight: 800,
                letterSpacing: "0.15em",
                color: "primary.light",
              }}
            >
              SESSIONS
            </Typography>
            <Typography
              variant="overline"
              sx={{
                display: "block",
                lineHeight: 1,
                color: "text.secondary",
                fontWeight: 600,
              }}
            >
              Research Log
            </Typography>
          </Box>
        </Box>

        {/* Search Bar */}
        <Box sx={{ px: 2, pt: 1 }}>
          <TextField
            fullWidth
            size="small"
            disabled={!threadId}
            placeholder={
              threadId ? "Search history..." : "Open a session to search"
            }
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            InputProps={{
              startAdornment: (
                <InputAdornment position="start">
                  <Search
                    width={14}
                    height={14}
                    color={
                      !threadId
                        ? "text.disabled"
                        : isDark
                          ? "rgba(255,255,255,0.4)"
                          : "rgba(0,0,0,0.3)"
                    }
                  />
                </InputAdornment>
              ),
              endAdornment: searchQuery && (
                <InputAdornment position="end">
                  <IconButton size="small" onClick={() => setSearchQuery("")}>
                    <X width={12} height={12} />
                  </IconButton>
                </InputAdornment>
              ),
              sx: {
                borderRadius: "12px",
                fontSize: "0.75rem",
                bgcolor: isDark ? "rgba(255,255,255,0.03)" : "rgba(0,0,0,0.02)",
                "& fieldset": { borderColor: "transparent" },
                "&:hover fieldset": {
                  borderColor: threadId ? "divider" : "transparent",
                },
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
            onClick={onStartNewExperiment}
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
            NEW SESSION
          </Button>
        </Box>

        {/* Main Content Area: Search Results or Thread List */}
        <Box
          sx={{
            flex: 1,
            overflow: "hidden",
            display: "flex",
            flexDirection: "column",
          }}
        >
          {searchQuery.length >= 2 ? (
            <Box
              sx={{
                flex: 1,
                display: "flex",
                flexDirection: "column",
                minHeight: 0,
              }}
            >
              <Box
                sx={{
                  px: 3,
                  pt: 2,
                  pb: 1,
                  display: "flex",
                  alignItems: "center",
                  justifyContent: "space-between",
                }}
              >
                <Typography
                  variant="overline"
                  sx={{
                    fontWeight: 800,
                    color: "primary.main",
                    fontSize: "0.6rem",
                    letterSpacing: "0.1em",
                  }}
                >
                  Search Results
                </Typography>
                {isSearching && (
                  <Box
                    sx={{
                      width: 12,
                      height: 12,
                      borderRadius: "50%",
                      border: "2px solid",
                      borderTopColor: "primary.main",
                      borderRightColor: "transparent",
                      animation: "spin 1s linear infinite",
                    }}
                  />
                )}
              </Box>
              <List sx={{ flex: 1, overflow: "auto", px: 1.5, pt: 0 }}>
                {searchResults.length === 0 && !isSearching ? (
                  <Typography
                    align="center"
                    variant="caption"
                    sx={{ display: "block", py: 4, color: "text.secondary" }}
                  >
                    No matches found in this thread
                  </Typography>
                ) : (
                  searchResults.map((result) => (
                    <ListItemButton
                      key={result.checkpoint_id}
                      onClick={() => {
                        onSwitchCheckpoint(result.checkpoint_id);
                        setSearchQuery(""); // Optional: clear search after jump
                      }}
                      sx={{
                        borderRadius: 3,
                        mb: 0.5,
                        flexDirection: "column",
                        alignItems: "flex-start",
                        py: 1.5,
                        border: "1px solid transparent",
                        "&:hover": {
                          borderColor: "primary.main",
                          bgcolor: isDark
                            ? "rgba(37, 99, 235, 0.05)"
                            : "primary.50",
                        },
                      }}
                    >
                      <Box
                        sx={{
                          display: "flex",
                          alignItems: "center",
                          gap: 1,
                          mb: 0.5,
                          width: "100%",
                        }}
                      >
                        <Box
                          sx={{
                            width: 6,
                            height: 6,
                            borderRadius: "50%",
                            bgcolor:
                              result.role === "user"
                                ? "primary.main"
                                : "success.main",
                          }}
                        />
                        <Typography
                          variant="caption"
                          sx={{
                            fontWeight: 800,
                            textTransform: "uppercase",
                            fontSize: "0.6rem",
                            color: "text.secondary",
                          }}
                        >
                          {result.model ||
                            (result.role === "user" ? "User" : "AI")}
                        </Typography>
                      </Box>
                      <Typography
                        variant="body2"
                        sx={{
                          fontSize: "0.75rem",
                          color: "text.primary",
                          lineHeight: 1.4,
                          display: "-webkit-box",
                          WebkitLineClamp: 2,
                          WebkitBoxOrient: "vertical",
                          overflow: "hidden",
                          fontStyle: "italic",
                          opacity: 0.8,
                        }}
                      >
                        {result.excerpt}
                      </Typography>
                    </ListItemButton>
                  ))
                )}
              </List>
            </Box>
          ) : (
            <List
              sx={{
                flex: 1,
                overflow: "auto",
                px: 1.5,
                py: 1.5,
                "&::-webkit-scrollbar": { display: "none" },
              }}
            >
              <AnimatePresence mode="popLayout">
                {threads.length === 0 ? (
                  <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }}>
                    <Typography
                      align="center"
                      variant="caption"
                      sx={{
                        display: "block",
                        py: 8,
                        color: "text.secondary",
                        fontWeight: 500,
                      }}
                    >
                      No sessions yet
                    </Typography>
                  </motion.div>
                ) : (
                  threads.map((t, idx) => {
                    const isActive = t.id === threadId;
                    const isEditing = editingThreadId === t.id;

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
                          <Box
                            sx={{
                              display: "flex",
                              alignItems: "center",
                              gap: 1,
                              p: 0.5,
                              borderRadius: 3,
                              border: "1px solid",
                              borderColor: "divider",
                              bgcolor: isDark
                                ? "rgba(0,0,0,0.2)"
                                : "background.default",
                            }}
                          >
                            <TextField
                              autoFocus
                              fullWidth
                              variant="standard"
                              size="small"
                              value={editingTitle}
                              onChange={(e) => setEditingTitle(e.target.value)}
                              onKeyDown={(e) => {
                                if (e.key === "Enter")
                                  onRenameThread(t.id, editingTitle);
                                if (e.key === "Escape")
                                  setEditingThreadId(null);
                              }}
                              InputProps={{
                                disableUnderline: true,
                                sx: {
                                  fontSize: "0.875rem",
                                  fontWeight: 600,
                                  px: 1,
                                },
                              }}
                            />
                            <IconButton
                              size="small"
                              onClick={() => onRenameThread(t.id, editingTitle)}
                              sx={{ color: "success.main" }}
                            >
                              <Check width={14} height={14} />
                            </IconButton>
                            <IconButton
                              size="small"
                              onClick={() => setEditingThreadId(null)}
                              sx={{ color: "error.main" }}
                            >
                              <X width={14} height={14} />
                            </IconButton>
                          </Box>
                        ) : (
                          <ListItem
                            disablePadding
                            secondaryAction={
                              <Box
                                className="thread-actions"
                                sx={{
                                  opacity: 0,
                                  transition: "opacity 0.2s",
                                  display: "flex",
                                  mr: -1,
                                }}
                              >
                                <IconButton
                                  size="small"
                                  onClick={(e) => {
                                    e.stopPropagation();
                                    setEditingThreadId(t.id);
                                    setEditingTitle(t.title);
                                  }}
                                >
                                  <Edit3 width={14} height={14} />
                                </IconButton>
                                <IconButton
                                  size="small"
                                  onClick={(e) => onDeleteThread(e, t.id)}
                                  sx={{ "&:hover": { color: "error.main" } }}
                                >
                                  <Trash2 width={14} height={14} />
                                </IconButton>
                              </Box>
                            }
                            sx={{
                              borderRadius: 3,
                              overflow: "hidden",
                              border: "1px solid",
                              borderColor: isActive
                                ? "primary.main"
                                : "transparent",
                              bgcolor: isActive
                                ? isDark
                                  ? "rgba(37, 99, 235, 0.1)"
                                  : "primary.50"
                                : "transparent",
                              "&:hover": {
                                borderColor: isActive
                                  ? "primary.main"
                                  : "divider",
                                "& .thread-actions": { opacity: 1 },
                              },
                            }}
                          >
                            <ListItemButton
                              onClick={() => onSwitchThread(t.id)}
                              sx={{ py: 1.5, px: 2 }}
                            >
                              <ListItemText
                                primary={t.title}
                                primaryTypographyProps={{
                                  variant: "body2",
                                  fontWeight: 600,
                                  noWrap: true,
                                  sx: {
                                    color: isActive
                                      ? "primary.main"
                                      : "text.primary",
                                    pr: 5,
                                  },
                                }}
                              />
                            </ListItemButton>
                          </ListItem>
                        )}
                      </Box>
                    );
                  })
                )}
              </AnimatePresence>
            </List>
          )}
        </Box>
      </Drawer>
    );
  },
);

export default Sidebar;
