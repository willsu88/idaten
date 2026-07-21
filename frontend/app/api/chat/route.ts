import { NextRequest } from "next/server";

// The chat endpoint streams Server-Sent Events. Next's rewrites() proxy buffers
// streamed responses — after an initial burst (e.g. tool events) the text deltas
// stall until the upstream closes, so a long reply never appears. We proxy this
// single route explicitly and pass the upstream body straight through untouched
// so deltas flow to the browser as they arrive. Everything else under /api/*
// still goes through the rewrite in next.config.mjs.
export const runtime = "nodejs";
export const dynamic = "force-dynamic";

const BACKEND = process.env.BACKEND_URL || "http://localhost:8000";

export async function POST(request: NextRequest) {
  const upstream = await fetch(`${BACKEND}/api/chat`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      // Forward the httpOnly session cookie so backend auth (gb_session) works.
      cookie: request.headers.get("cookie") ?? "",
    },
    body: await request.text(),
  });

  // Pass the streaming body through as-is. 400/429 arrive here too (with a JSON
  // detail sentence) — forward their status and content-type unchanged so the
  // client's error handling still sees them.
  return new Response(upstream.body, {
    status: upstream.status,
    headers: {
      "Content-Type":
        upstream.headers.get("content-type") ?? "text/event-stream",
      "Cache-Control": "no-cache, no-transform",
      "X-Accel-Buffering": "no",
    },
  });
}
