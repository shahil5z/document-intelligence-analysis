import { NextResponse, type NextRequest } from "next/server";

const SESSION_COOKIE = "dip_session";

/**
 * Send visitors without a session cookie to /login before rendering app pages. This is a
 * convenience redirect only: every API call is still authorised by the backend, and an
 * expired cookie is detected (401) and cleared by the /api/* route handlers.
 */
export function proxy(request: NextRequest) {
  if (request.cookies.get(SESSION_COOKIE)?.value) return NextResponse.next();
  const login = new URL("/login", request.url);
  const next = request.nextUrl.pathname;
  if (next !== "/") login.searchParams.set("next", next);
  return NextResponse.redirect(login);
}

export const config = {
  matcher: [
    "/dashboard/:path*",
    "/upload/:path*",
    "/documents/:path*",
    "/search/:path*",
    "/ask/:path*",
    "/settings/:path*",
  ],
};
