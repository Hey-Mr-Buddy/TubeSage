import type { NextConfig } from 'next';

const nextConfig: NextConfig = {
  poweredByHeader: false,
  reactStrictMode: true,
  experimental: {
    // Keep Windows builds deterministic and avoid parallel segment-directory
    // creation collisions on constrained local filesystems.
    cpus: 1,
  },
};

export default nextConfig;
