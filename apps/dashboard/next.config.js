/** @type {import('next').NextConfig} */
const nextConfig = {
  output: "standalone",
  reactStrictMode: true,
  async rewrites() {
    const orchestratorUrl = process.env.ORCHESTRATOR_INTERNAL_URL || "http://orchestrator-agent-orchestrator.agents.svc.cluster.local:8000";
    return [
      {
        source: "/orchestrator/:path*",
        destination: `${orchestratorUrl}/:path*`,
      },
    ];
  },
};

module.exports = nextConfig;
