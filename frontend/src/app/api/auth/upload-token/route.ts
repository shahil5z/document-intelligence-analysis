import type { NextRequest } from "next/server";

import { callBackend, errorResponse, relay } from "@/lib/server/backend";
import { csrfProblem } from "@/lib/server/csrf";
import { clearSessionCookie, getSessionToken } from "@/lib/server/session";

/**
 * Exchange the session for a short-lived, upload-only token (POST /auth/upload-token).
 * The browser sends the file straight to the API with it, so uploads do not pass through
 * a serverless function (Vercel caps request bodies at about 4.5 MB). The API accepts this
 * token type on POST /documents only; it is kept in memory and never stored.
 */
export async function POST(request: NextRequest) {
  if (csrfProblem(request)) {
    return errorResponse(403, "forbidden", "Request blocked (CSRF check failed)");
  }
  const token = getSessionToken(request);
  if (!token) return errorResponse(401, "not_authenticated", "Not signed in");
  const result = await callBackend("/auth/upload-token", { method: "POST", token });
  const response = relay(result);
  if (result.status === 401) clearSessionCookie(response, request);
  return response;
}
