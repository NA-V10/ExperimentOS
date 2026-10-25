import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // The Docker image runs the standalone server; Render/Vercel use `next start` / their own runtime.
  output: process.env.NEXT_OUTPUT === "standalone" ? "standalone" : undefined,
  reactStrictMode: true,
};

export default nextConfig;
