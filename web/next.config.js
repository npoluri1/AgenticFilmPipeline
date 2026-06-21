/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  async rewrites() {
    return [
      { source: "/api/:path*", destination: "http://backend:8080/:path*" },
    ];
  },
};

module.exports = nextConfig;
