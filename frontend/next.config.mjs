/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  // No gzip at the Next layer: its compression buffers the chat SSE stream
  // (deltas sit in the gzip window until the response ends, so replies arrive
  // all at once through cloudflared). Cloudflare compresses at the edge anyway.
  compress: false,
  // Same-origin proxy to the backend so the httpOnly session cookie flows
  // automatically. BACKEND_URL is a runtime env (e.g. http://backend:8000 in Docker).
  async rewrites() {
    return [
      {
        source: "/api/:path*",
        destination: `${process.env.BACKEND_URL || "http://localhost:8000"}/api/:path*`,
      },
    ];
  },
};

export default nextConfig;
