import React from "react";
import {
  Box,
  Typography,
  ButtonBase,
  Paper,
  Grid,
  useTheme,
} from "@mui/material";
import { motion } from "framer-motion";
import { Layers, Sparkles, Network, Zap, Cpu, ShieldCheck } from "lucide-react";

interface LandingViewProps {
  onStartNewExperiment: () => void;
}

const LandingView: React.FC<LandingViewProps> = ({ onStartNewExperiment }) => {
  const isDark = useTheme().palette.mode === "dark";
  return (
    <Box
      sx={{
        flex: 1,
        display: "flex",
        flexDirection: "column",
        alignItems: "center",
        justifyContent: "center",
        p: 4,
        width: "100%",
        height: "100%",
        overflowY: "auto",
        "&::-webkit-scrollbar": { display: "none" },
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
        {/* Hero Section */}
        <Box
          component={motion.div}
          initial={{ opacity: 0, scale: 0.9 }}
          animate={{ opacity: 1, scale: 1 }}
          transition={{ duration: 0.5, type: "spring" }}
          sx={{ textAlign: "center", mb: 8 }}
        >
          <Box
            sx={{
              display: "inline-flex",
              p: 3,
              borderRadius: 6,
              mb: 4,
              background: isDark
                ? "linear-gradient(135deg, rgba(37,99,235,0.2), rgba(139,92,246,0.2))"
                : "linear-gradient(135deg, rgba(37,99,235,0.1), rgba(139,92,246,0.1))",
              border: "1px solid",
              borderColor: isDark
                ? "rgba(255,255,255,0.05)"
                : "rgba(0,0,0,0.05)",
              boxShadow: isDark
                ? "0 20px 40px -10px rgba(139,92,246,0.3)"
                : "0 20px 40px -10px rgba(37,99,235,0.2)",
            }}
          >
            <Zap
              width={48}
              height={48}
              color={isDark ? "#a78bfa" : "#6366f1"}
            />
          </Box>
          <Typography
            variant="h2"
            sx={{
              fontWeight: 900,
              letterSpacing: "-0.02em",
              mb: 2,
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
            sx={{
              fontWeight: 400,
              color: "text.secondary",
              maxWidth: 600,
              mx: "auto",
              lineHeight: 1.6,
            }}
          >
            Harness the combined intelligence of multiple AI models. Force
            parallel deliberation to synthesize unbreakable academic and
            structural consensus.
          </Typography>
        </Box>

        {/* Features Grid */}
        <Box
          component={motion.div}
          initial="hidden"
          animate="visible"
          variants={{
            hidden: { opacity: 0 },
            visible: { opacity: 1, transition: { staggerChildren: 0.1 } },
          }}
          sx={{
            width: "100%",
            display: "grid",
            gridTemplateColumns: { xs: "1fr", md: "repeat(3, 1fr)" },
            gap: 3,
            mb: 8,
          }}
        >
          <Paper
            component={motion.div}
            variants={{
              hidden: { opacity: 0, y: 20 },
              visible: { opacity: 1, y: 0 },
            }}
            sx={{
              p: 4,
              borderRadius: 4,
              border: "1px solid",
              borderColor: "divider",
              bgcolor: isDark
                ? "rgba(255,255,255,0.02)"
                : "rgba(255,255,255,0.6)",
              backdropFilter: "blur(16px)",
              transition: "transform 0.2s",
              "&:hover": { transform: "translateY(-4px)" },
            }}
          >
            <Box
              sx={{
                w: 40,
                h: 40,
                borderRadius: 3,
                bgcolor: "rgba(59, 130, 246, 0.1)",
                color: "#3b82f6",
                display: "flex",
                alignItems: "center",
                justifyContent: "center",
                mb: 3,
              }}
            >
              <Cpu width={24} height={24} />
            </Box>
            <Typography
              variant="h6"
              sx={{ fontWeight: 800, mb: 1.5, fontSize: "1.25rem" }}
            >
              Parallel Deliberation
            </Typography>
            <Typography
              variant="body2"
              sx={{ color: "text.secondary", lineHeight: 1.6 }}
            >
              Queries are routed to multiple models simultaneously. Compare
              reasoning side-by-side in The Arena.
            </Typography>
          </Paper>

          <Paper
            component={motion.div}
            variants={{
              hidden: { opacity: 0, y: 20 },
              visible: { opacity: 1, y: 0 },
            }}
            sx={{
              p: 4,
              borderRadius: 4,
              border: "1px solid",
              borderColor: "divider",
              bgcolor: isDark
                ? "rgba(255,255,255,0.02)"
                : "rgba(255,255,255,0.6)",
              backdropFilter: "blur(16px)",
              transition: "transform 0.2s",
              "&:hover": { transform: "translateY(-4px)" },
            }}
          >
            <Box
              sx={{
                w: 40,
                h: 40,
                borderRadius: 3,
                bgcolor: "rgba(139, 92, 246, 0.1)",
                color: "#a78bfa",
                display: "flex",
                alignItems: "center",
                justifyContent: "center",
                mb: 3,
              }}
            >
              <ShieldCheck width={24} height={24} />
            </Box>
            <Typography
              variant="h6"
              sx={{ fontWeight: 800, mb: 1.5, fontSize: "1.25rem" }}
            >
              Consensus Synthesis
            </Typography>
            <Typography
              variant="body2"
              sx={{ color: "text.secondary", lineHeight: 1.6 }}
            >
              Force models to peer-review each other&apos;s outputs to extract
              the highest quality insights and resolve contradictions.
            </Typography>
          </Paper>

          <Paper
            component={motion.div}
            variants={{
              hidden: { opacity: 0, y: 20 },
              visible: { opacity: 1, y: 0 },
            }}
            sx={{
              p: 4,
              borderRadius: 4,
              border: "1px solid",
              borderColor: "divider",
              bgcolor: isDark
                ? "rgba(255,255,255,0.02)"
                : "rgba(255,255,255,0.6)",
              backdropFilter: "blur(16px)",
              transition: "transform 0.2s",
              "&:hover": { transform: "translateY(-4px)" },
            }}
          >
            <Box
              sx={{
                w: 40,
                h: 40,
                borderRadius: 3,
                bgcolor: "rgba(16, 185, 129, 0.1)",
                color: "#10b981",
                display: "flex",
                alignItems: "center",
                justifyContent: "center",
                mb: 3,
              }}
            >
              <Network width={24} height={24} />
            </Box>
            <Typography
              variant="h6"
              sx={{ fontWeight: 800, mb: 1.5, fontSize: "1.1rem" }}
            >
              Decision Trees
            </Typography>
            <Typography
              variant="body2"
              sx={{ color: "text.secondary", lineHeight: 1.6 }}
            >
              Visually explore branch paths. Switch contexts instantly and fork
              conversations to explore alternative realities.
            </Typography>
          </Paper>
        </Box>

        {/* CTA */}
        <Box
          component={motion.div}
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ delay: 0.4 }}
        >
          <ButtonBase
            component={motion.button}
            whileHover={{ scale: 1.05 }}
            whileTap={{ scale: 0.95 }}
            onClick={onStartNewExperiment}
            sx={{
              px: 5,
              py: 2,
              borderRadius: 8,
              background: "linear-gradient(135deg, #2563eb, #7c3aed)",
              color: "white",
              fontWeight: 800,
              fontSize: "1rem",
              letterSpacing: "0.1em",
              textTransform: "uppercase",
              boxShadow: "0 10px 25px -5px rgba(37,99,235,0.5)",
              display: "flex",
              alignItems: "center",
              gap: 1.5,
            }}
          >
            <Sparkles width={18} height={18} />
            Initialize New Experiment
          </ButtonBase>
        </Box>
      </Box>
    </Box>
  );
};

export default LandingView;
