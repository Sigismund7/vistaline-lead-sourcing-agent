import { NextRequest, NextResponse } from "next/server";

const BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";
const SECRET = process.env.VISTALINE_API_SECRET ?? "";

async function forward(req: NextRequest, path: string[]) {
  const url = new URL(req.url);
  const target = `${BASE}/${path.join("/")}${url.search}`;

  const init: RequestInit = {
    method: req.method,
    headers: {
      "X-Api-Key": SECRET,
      "Content-Type": req.headers.get("content-type") ?? "application/json",
    },
  };

  if (req.method !== "GET" && req.method !== "HEAD") {
    init.body = await req.text();
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
