import { NextResponse } from "next/server";
import type { NextRequest } from "next/server";

const PUBLIC = ["/login", "/api/auth/login"];

export function proxy(req: NextRequest) {
  const { pathname } = req.nextUrl;
  if (PUBLIC.some((p) => pathname.startsWith(p))) return NextResponse.next();

  const session = req.cookies.get("session")?.value;
  if (session !== process.env.SESSION_SECRET) {
    return NextResponse.redirect(new URL("/login", req.url));
  }
  return NextResponse.next();
}

export const config = {
  matcher: [
    "/((?!_next|[^?]*\\.(?:html?|css|js(?!on)|jpe?g|webp|png|gif|svg|ttf|woff2?|ico|csv|docx?|xlsx?|zip|webmanifest)).*)",
  ],
};
