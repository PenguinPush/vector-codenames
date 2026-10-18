import type { NextConfig } from "next";

const config: NextConfig = {
  poweredByHeader: false,
  devIndicators: false,
  allowedDevOrigins: ["127.0.0.1", ...(process.env.CODENAMES_DEV_ORIGINS?.split(",").filter(Boolean) ?? [])],
};

export default config;
