/** @type {import('next').NextConfig} */

// Server-side proxy target. In docker compose this is `http://studio:8080`;
// for local development it defaults to the studio running on :8080.
const API_PROXY =
  process.env.API_PROXY_TARGET ||
  process.env.NEXT_PUBLIC_API_URL ||
  "http://localhost:8080";

const nextConfig = {
  reactStrictMode: true,
  async rewrites() {
    return [
      { source: "/api/:path*", destination: `${API_PROXY}/api/:path*` },
      { source: "/artifacts/:path*", destination: `${API_PROXY}/artifacts/:path*` },
    ];
  },
};

module.exports = nextConfig;
