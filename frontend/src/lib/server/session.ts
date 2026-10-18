import "server-only";

import type { NextRequest, NextResponse } from "next/server";

/**
 * The API access token lives only in this HttpOnly cookie on the frontend's own origin.
 * Browser JavaScript can never read it; the /api/* route handlers attach it to calls to
 * the FastAPI backend. SameSite=Lax plus the CSRF checks in csrf.ts protect writes.
 */
export const SESSION_COOKIE = "dip_session";

export function isSecureRequest(request: NextRequest): boolean {
  const forwarded = request.headers.get("x-forwarded-proto")?.split(",")[0]?.trim();
  if (forwarded) return forwarded === "https";
  return request.nextUrl.protocol === "https:";
}

export function getSessionToken(request: NextRequest): string | null {
  const value = request.cookies.get(SESSION_COOKIE)?.value;
  return value && value.length > 0 ? value : null;
}

export function setSessionCookie(
  response: NextResponse,
  request: NextRequest,
  token: string,
  maxAgeSeconds: number,
): void {
  response.cookies.set({
    name: SESSION_COOKIE,
    value: token,
    httpOnly: true,
    secure: isSecureRequest(request),
    sameSite: "lax",
    path: "/",
    // Slightly shorter than the token so the browser drops it before the API rejects it.
    maxAge: Math.max(60, maxAgeSeconds - 30),
  });
}

export function clearSessionCookie(response: NextResponse, request: NextRequest): void {
  response.cookies.set({
    name: SESSION_COOKIE,
    value: "",
    httpOnly: true,
    secure: isSecureRequest(request),
    sameSite: "lax",
    path: "/",
    maxAge: 0,
  });
}
