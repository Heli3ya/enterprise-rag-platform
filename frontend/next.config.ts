
import { withSentryConfig } from "@sentry/nextjs/config";
import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  allowedDevOrigins: ["127.0.0.1"],
};

export default withSentryConfig(nextConfig, {
  silent: !process.env.CI,
});
