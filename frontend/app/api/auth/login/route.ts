import { timingSafeEqual } from "crypto";
import { NextResponse } from "next/server";
import { createClient } from "@supabase/supabase-js";

/** Constant-time string comparison. Returns false if lengths differ. */
function safeEqual(a: string, b: string): boolean {
  const aBuf = Buffer.from(a);
  const bBuf = Buffer.from(b);
  if (aBuf.length !== bBuf.length) return false;
  return timingSafeEqual(aBuf, bBuf);
}

const RATE_LIMIT_WINDOW_MINUTES = 15;
const RATE_LIMIT_MAX_ATTEMPTS = 10;

export async function POST(req: Request) {
  if (!process.env.AUTH_USERNAME || !process.env.AUTH_PASSWORD || !process.env.SESSION_SECRET) {
    throw new Error("AUTH_USERNAME, AUTH_PASSWORD, and SESSION_SECRET env vars are required");
  }

  const clientIp =
    req.headers.get("x-forwarded-for")?.split(",")[0].trim() ?? "unknown";

  // --- Rate limiting (best-effort — if Supabase is unreachable we proceed) ---
  let supabase: ReturnType<typeof createClient> | null = null;
  try {
    supabase = createClient(
      process.env.SUPABASE_URL!,
      process.env.SUPABASE_SERVICE_ROLE_KEY!
    );

    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const { count, error: countError } = await (supabase.from("login_attempts") as any)
      .select("*", { count: "exact", head: true })
      .eq("ip", clientIp)
      .eq("succeeded", false)
      .gte(
        "attempted_at",
        new Date(
          Date.now() - RATE_LIMIT_WINDOW_MINUTES * 60 * 1000
        ).toISOString()
      );

    if (countError) {
      console.warn("[login] Supabase rate-limit check failed:", countError.message);
    } else if ((count ?? 0) >= RATE_LIMIT_MAX_ATTEMPTS) {
      return NextResponse.json(
        { error: "Too many login attempts. Try again later." },
        { status: 429 }
      );
    }
  } catch (err) {
    console.warn("[login] Supabase unreachable, skipping rate limit:", err);
  }

  // --- Credential check (constant-time) ---
  let username: string | undefined;
  let password: string | undefined;
  try {
    const body = await req.json();
    username = body.username;
    password = body.password;
  } catch {
    return NextResponse.json({ error: "Bad request" }, { status: 400 });
  }

  const expectedUsername = process.env.AUTH_USERNAME ?? "";
  const expectedPassword = process.env.AUTH_PASSWORD ?? "";

  const credentialsValid =
    safeEqual(username ?? "", expectedUsername) &&
    safeEqual(password ?? "", expectedPassword);

  // --- Record attempt (best-effort) ---
  if (supabase) {
    try {
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      await (supabase.from("login_attempts") as any).insert({
        ip: clientIp,
        username_attempted: (username ?? "").substring(0, 256),
        succeeded: credentialsValid,
      });
    } catch (err) {
      console.warn("[login] Failed to record login attempt:", err);
    }
  }

  if (!credentialsValid) {
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
  res.cookies.set("username", username ?? "", { ...cookieOpts, httpOnly: false });
  return res;
}
