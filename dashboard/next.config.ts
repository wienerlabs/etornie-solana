import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  async redirects() {
    return [
      // The old "Agent (preview)" route was promoted to the canonical
      // EtornieGPT page; keep old links / bookmarks working.
      {
        source: "/dashboard/agent",
        destination: "/dashboard/etorniegpt",
        permanent: true,
      },
    ];
  },
};

export default nextConfig;
