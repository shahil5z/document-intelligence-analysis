import { NextResponse, type NextRequest } from "next/server";

import { callBackend, relay } from "@/lib/server/backend";
import { clearSessionCookie, getSessionToken } from "@/lib/server/session";

/** Who is signed in (GET /auth/me with the cookie's token). 401 clears a stale cookie. */
export async function GET(request: NextRequest) {
  const token = getSessionToken(request);
  if (!token) {
    return NextResponse.json(
      { error: { code: "not_authenticated", message: "Not signed in" } },
      { status: 401, headers: { "cache-control": "no-store" } },
    );
  }
  const result = await callBackend("/auth/me", { token });
  const response = relay(result);
  if (result.status === 401) clearSessionCookie(response, request);
  return response;
}
