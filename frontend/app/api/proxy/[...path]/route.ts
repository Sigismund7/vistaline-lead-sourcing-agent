import { NextRequest, NextResponse } from "next/server";

const BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";
const SECRET = process.env.VISTALINE_API_SECRET ?? "";

async function forward(req: NextRequest, path: string[]) {
  const url = new URL(req.url);
  const target = `${BASE}/${path.join("/")}${url.search}`;

  const ct = req.headers.get("content-type");
  const forwardedHeaders: Record<string, string> = { "X-Api-Key": SECRET };
  // For multipart, forward the original Content-Type (which includes the boundary).
  // For all other requests, default to application/json if none is set.
  if (ct) {
    forwardedHeaders["Content-Type"] = ct;
  } else if (req.method !== "GET" && req.method !== "HEAD") {
    forwardedHeaders["Content-Type"] = "application/json";
  }

  const init: RequestInit = {
    method: req.method,
    headers: forwardedHeaders,
  };

  if (req.method !== "GET" && req.method !== "HEAD") {
    init.body = (ct ?? "").startsWith("multipart/") ? await req.arrayBuffer() : await req.text();
  }

  const upstream = await fetch(target, init);
  const body = await upstream.arrayBuffer();
  const headers = new Headers();
  upstream.headers.forEach((value, key) => {
    // Skip hop-by-hop and content-encoding (Next handles compression)
    if (
      key.toLowerCase() === "content-encoding" ||
      key.toLowerCase() === "transfer-encoding" ||
      key.toLowerCase() === "connection"
    ) return;
    headers.set(key, value);
  });

  return new NextResponse(body, {
    status: upstream.status,
    headers,
  });
}

export async function GET(req: NextRequest, ctx: { params: Promise<{ path: string[] }> }) {
  const { path } = await ctx.params;
  return forward(req, path);
}
export async function POST(req: NextRequest, ctx: { params: Promise<{ path: string[] }> }) {
  const { path } = await ctx.params;
  return forward(req, path);
}
export async function PATCH(req: NextRequest, ctx: { params: Promise<{ path: string[] }> }) {
  const { path } = await ctx.params;
  return forward(req, path);
}
export async function DELETE(req: NextRequest, ctx: { params: Promise<{ path: string[] }> }) {
  const { path } = await ctx.params;
  return forward(req, path);
}
