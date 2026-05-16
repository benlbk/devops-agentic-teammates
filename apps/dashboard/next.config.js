/** @type {import('next').NextConfig} */
const nextConfig = {
  output: "standalone",
  reactStrictMode: true,
  async rewrites() {
    return [
      {
        source: "/api/metrics/:path*",
        destination: `${process.env.ORCHESTRATOR_INTERNAL_URL || "http://orchestrator.agents.svc.cluster.local:8000"}/api/metrics/:path*`,
      },
    ];
  },
};

module.exports = nextConfig;
