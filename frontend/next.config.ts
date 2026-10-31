import type { NextConfig } from "next";
import path from "path";

const nextConfig: NextConfig = {
  // The e2e suite builds into its own directory (playwright.config.ts).
  distDir: process.env.NEXT_DIST_DIR || ".next",
  // @ts-ignore - Turbopack root configuration moved to top-level in recent versions
  turbopack: {
    root: path.resolve(__dirname, ".."),
  },
  // The dev server blocks its own resources (HMR, chunks) for hosts other
  // than localhost; the app is also opened as 127.0.0.1 (the e2e suite, and
  // anyone who types it), which otherwise loads a page that never hydrates.
  allowedDevOrigins: ["127.0.0.1", "[::1]"],
  // `next dev` would write agent instructions into frontend/AGENTS.md on every
  // start. Instructions for agents working here live in CLAUDE.md, reviewed
  // with the code; a dependency rewriting them on each run is not.
  agentRules: false,
};

export default nextConfig;
