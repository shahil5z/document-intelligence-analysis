import "server-only";

import type { NextRequest } from "next/server";

import { CSRF_HEADER, CSRF_VALUE } from "@/lib/config";

/**
 * CSRF defence for state-changing /api/* calls (on top of the SameSite=Lax cookie):
 * 1. the request must carry the custom X-DIP-CSRF header, which a cross-site form or
 *    "simple" request cannot set and a cross-site fetch cannot send without a CORS
 *    preflight these route handlers never approve;
 * 2. the Origin header must match this site's own origin.
 */
export function csrfProblem(request: NextRequest): string | null {
  if (request.headers.get(CSRF_HEADER) !== CSRF_VALUE) return "missing CSRF header";
  const origin = request.headers.get("origin");
  if (!origin) return "missing Origin header";
  const host = request.headers.get("x-forwarded-host") ?? request.headers.get("host");
  let originHost: string;
  try {
    originHost = new URL(origin).host;
  } catch {
    return "invalid Origin header";
  }
  return host && originHost === host ? null : "cross-origin request";
}
