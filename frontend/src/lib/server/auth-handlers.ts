import "server-only";

import { NextResponse, type NextRequest } from "next/server";

import { callBackend, clientIpOf, errorResponse, relay } from "./backend";
import { csrfProblem } from "./csrf";
import { setSessionCookie } from "./session";

const MAX_CREDENTIAL_BODY_BYTES = 4096;

interface Credentials {
  email: string;
  password: string;
}

export async function readCredentials(request: NextRequest): Promise<Credentials | NextResponse> {
  const problem = csrfProblem(request);
  if (problem) return errorResponse(403, "forbidden", "Request blocked (CSRF check failed)");
  const text = await request.text();
  if (text.length > MAX_CREDENTIAL_BODY_BYTES) {
    return errorResponse(413, "payload_too_large", "Request body is too large");
  }
  try {
    const body = JSON.parse(text) as Partial<Credentials>;
    if (typeof body.email === "string" && typeof body.password === "string") {
      return { email: body.email.trim(), password: body.password };
    }
  } catch {
    // fall through
  }
  return errorResponse(422, "validation_error", "Email and password are required");
}

/** Log in at the API and keep the token in the HttpOnly cookie; the body never has it. */
export async function loginAndSetCookie(
  request: NextRequest,
  credentials: Credentials,
): Promise<NextResponse> {
  const result = await callBackend("/auth/login", {
    method: "POST",
    json: credentials,
    clientIp: clientIpOf(request),
  });
  const body = result.body as { access_token?: string; expires_in?: number } | null;
  if (result.status !== 200 || !body?.access_token) return relay(result);
  const response = NextResponse.json({ authenticated: true }, { status: 200 });
  setSessionCookie(response, request, body.access_token, body.expires_in ?? 1800);
  response.headers.set("cache-control", "no-store");
  return response;
}
