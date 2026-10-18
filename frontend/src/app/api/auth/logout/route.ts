import { NextResponse, type NextRequest } from "next/server";

import { errorResponse } from "@/lib/server/backend";
import { csrfProblem } from "@/lib/server/csrf";
import { clearSessionCookie } from "@/lib/server/session";

// Stateless JWTs: logging out deletes the cookie; the token expires on its own
// (JWT_ACCESS_TOKEN_EXPIRE_MINUTES) and was never readable by page scripts.
export async function POST(request: NextRequest) {
  if (csrfProblem(request)) {
    return errorResponse(403, "forbidden", "Request blocked (CSRF check failed)");
  }
  const response = NextResponse.json({ authenticated: false });
  clearSessionCookie(response, request);
  return response;
}
