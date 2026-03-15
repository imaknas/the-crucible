import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // @ts-ignore - Turbopack root configuration moved to top-level in recent versions
  turbopack: {
    root: "..",
  },
};

export default nextConfig;
