import type { NextConfig } from "next";
import path from "path";

const nextConfig: NextConfig = {
  // @ts-ignore - Turbopack root configuration moved to top-level in recent versions
  turbopack: {
    root: path.resolve(__dirname, ".."),
  },
};

export default nextConfig;
