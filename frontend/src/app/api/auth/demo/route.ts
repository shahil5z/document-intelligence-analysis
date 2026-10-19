import { NextResponse, type NextRequest } from "next/server";

import { callBackend, clientIpOf, errorResponse, relay } from "@/lib/server/backend";
import { csrfProblem } from "@/lib/server/csrf";
import { setSessionCookie } from "@/lib/server/session";

/**
 * "Try the demo": POST /auth/demo at the API, then keep the demo token in the same
 * HttpOnly session cookie as a normal login. The browser only learns the demo limits.
 */
export async function POST(request: NextRequest) {
  if (csrfProblem(request)) {
    return errorResponse(403, "forbidden", "Request blocked (CSRF check failed)");
  }
  const result = await callBackend("/auth/demo", { method: "POST", clientIp: clientIpOf(request) });
  const body = result.body as { access_token?: string; expires_in?: number; demo?: unknown } | null;
  if (result.status !== 201 || !body?.access_token) return relay(result);
  const response = NextResponse.json({ authenticated: true, demo: body.demo ?? null }, { status: 201 });
  setSessionCookie(response, request, body.access_token, body.expires_in ?? 1800);
  response.headers.set("cache-control", "no-store");
  return response;
}
