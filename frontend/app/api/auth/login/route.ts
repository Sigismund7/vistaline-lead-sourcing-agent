import { NextResponse } from "next/server";

export async function POST(req: Request) {
  const { username, password } = await req.json();

  if (
    username !== process.env.AUTH_USERNAME ||
    password !== process.env.AUTH_PASSWORD
  ) {
    return NextResponse.json({ error: "Invalid credentials" }, { status: 401 });
  }

  const res = NextResponse.json({ ok: true });
  const cookieOpts = {
    httpOnly: true,
    secure: process.env.NODE_ENV === "production",
    sameSite: "lax" as const,
    maxAge: 60 * 60 * 24 * 30,
    path: "/",
  };
  res.cookies.set("session", process.env.SESSION_SECRET!, cookieOpts);
  res.cookies.set("username", username, { ...cookieOpts, httpOnly: false });
  return res;
}
