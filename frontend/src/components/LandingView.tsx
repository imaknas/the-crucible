import React from "react";
import { Box, Typography, ButtonBase, Paper, useTheme } from "@mui/material";
import { motion } from "framer-motion";
import { Sparkles, Network, Zap, Columns3, Swords, KeyRound } from "lucide-react";

interface LandingViewProps {
  onStartNewExperiment: () => void;
  hasAnyKey: boolean | null;
}

const FEATURES = [
  {
    title: "Arena",
    icon: Columns3,
    tint: "59, 130, 246",
    color: "#3b82f6",
    body: "Send one prompt to several models at once and read their answers side by side. Synthesis merges them into one answer; Deliberation asks one model to critique the thread.",
  },
  {
    title: "Debate",
    icon: Swords,
    tint: "139, 92, 246",
    color: "#a78bfa",
    body: "Models read each other's answers and reply over several rounds, stopping when they agree or stop changing. Pause, add a message, or synthesize at any point.",
  },
  {
    title: "Branching tree",
    icon: Network,
    tint: "16, 185, 129",
    color: "#10b981",
    body: "Every message is a node. Reply from any earlier point to try another direction without losing the original.",
  },
] as const;

const LandingView: React.FC<LandingViewProps> = ({ onStartNewExperiment, hasAnyKey }) => {
  const isDark = useTheme().palette.mode === "dark";
  return (
    <Box
      sx={{
        flex: 1,
        display: "flex",
        flexDirection: "column",
        alignItems: "center",
        // Top-aligned on short screens so the call to action stays above the fold.
        justifyContent: { xs: "flex-start", lg: "center" },
        px: { xs: 2, sm: 4 },
        py: { xs: 3, sm: 4 },
        width: "100%",
        height: "100%",
        overflowY: "auto",
      }}
    >
      <Box
        sx={{
          maxWidth: 900,
          width: "100%",
          display: "flex",
          flexDirection: "column",
          alignItems: "center",
        }}
      >
        {/* Hero */}
        <Box
          component={motion.div}
          initial={{ opacity: 0, scale: 0.96 }}
          animate={{ opacity: 1, scale: 1 }}
          transition={{ duration: 0.4 }}
          sx={{ textAlign: "center", mb: { xs: 3, md: 4 } }}
        >
          <Box
            sx={{
              display: "inline-flex",
              p: 2,
              borderRadius: 4,
              mb: 2.5,
              background: isDark
                ? "linear-gradient(135deg, rgba(37,99,235,0.2), rgba(139,92,246,0.2))"
                : "linear-gradient(135deg, rgba(37,99,235,0.1), rgba(139,92,246,0.1))",
              border: "1px solid",
              borderColor: isDark ? "rgba(255,255,255,0.05)" : "rgba(0,0,0,0.05)",
            }}
          >
            <Zap width={36} height={36} color={isDark ? "#a78bfa" : "#6366f1"} />
          </Box>
          <Typography
            variant="h2"
            component="h1"
            sx={{
              fontWeight: 900,
              letterSpacing: "-0.02em",
              mb: 1.5,
              fontSize: { xs: "2.25rem", md: "3.25rem" },
              background: isDark
                ? "linear-gradient(to right, #fff, #a8a29e)"
                : "linear-gradient(to right, #1e293b, #475569)",
              WebkitBackgroundClip: "text",
              WebkitTextFillColor: "transparent",
            }}
          >
            The Crucible
          </Typography>
          <Typography
            variant="h6"
            component="p"
            sx={{
              fontWeight: 400,
              color: "text.secondary",
              maxWidth: 620,
              mx: "auto",
              lineHeight: 1.6,
              fontSize: { xs: "1rem", md: "1.15rem" },
            }}
          >
            Ask several AI models the same question, compare their answers side by side, and
            branch the conversation from any point. Or have the models debate each other until
            they agree.
          </Typography>
        </Box>

        {hasAnyKey === false && (
          <Box
            sx={{
              mb: 3,
              px: 3,
              py: 2,
              borderRadius: 3,
              border: "1px solid",
              borderColor: "warning.dark",
              bgcolor: isDark ? "rgba(234,179,8,0.08)" : "rgba(234,179,8,0.06)",
              display: "flex",
              alignItems: "center",
              gap: 2,
              maxWidth: 520,
            }}
          >
            <KeyRound
              width={18}
              height={18}
              color={isDark ? "#fbbf24" : "#d97706"}
              style={{ flexShrink: 0 }}
            />
            <Typography variant="body2" sx={{ color: isDark ? "#fcd34d" : "#92400e", lineHeight: 1.5 }}>
              No API keys configured. Add at least one under{" "}
              <strong>Control Panel → API Keys</strong> to get started.
            </Typography>
          </Box>
        )}

        {/* Call to action, right under the pitch so it is visible without scrolling. */}
        <ButtonBase
          component={motion.button}
          whileHover={{ scale: 1.03 }}
          whileTap={{ scale: 0.97 }}
          onClick={onStartNewExperiment}
          sx={{
            px: 4,
            py: 1.75,
            mb: { xs: 4, md: 5 },
            borderRadius: 8,
            background: "linear-gradient(135deg, #2563eb, #7c3aed)",
            color: "white",
            fontWeight: 800,
            fontSize: "1rem",
            letterSpacing: "0.04em",
            boxShadow: "0 10px 25px -5px rgba(37,99,235,0.5)",
            display: "flex",
            alignItems: "center",
            gap: 1.5,
          }}
        >
          <Sparkles width={18} height={18} />
          Start a session
        </ButtonBase>

        <Box
          sx={{
            width: "100%",
            display: "grid",
            gridTemplateColumns: { xs: "1fr", md: "repeat(3, 1fr)" },
            gap: 2.5,
          }}
        >
          {FEATURES.map(({ title, icon: Icon, tint, color, body }) => (
            <Paper
              key={title}
              sx={{
                p: 3,
                borderRadius: 4,
                border: "1px solid",
                borderColor: "divider",
                bgcolor: isDark ? "rgba(255,255,255,0.02)" : "rgba(255,255,255,0.6)",
              }}
            >
              <Box
                sx={{
                  width: 40,
                  height: 40,
                  borderRadius: 3,
                  bgcolor: `rgba(${tint}, 0.1)`,
                  color,
                  display: "flex",
                  alignItems: "center",
                  justifyContent: "center",
                  mb: 2,
                }}
              >
                <Icon width={22} height={22} />
              </Box>
              <Typography variant="h6" component="h2" sx={{ fontWeight: 800, mb: 1, fontSize: "1.1rem" }}>
                {title}
              </Typography>
              <Typography variant="body2" sx={{ color: "text.secondary", lineHeight: 1.6 }}>
                {body}
              </Typography>
            </Paper>
          ))}
        </Box>
      </Box>
    </Box>
  );
};

export default LandingView;
