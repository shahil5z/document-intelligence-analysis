import type { NextRequest } from "next/server";

import { loginAndSetCookie, readCredentials } from "@/lib/server/auth-handlers";
import { callBackend, clientIpOf, errorResponse, relay } from "@/lib/server/backend";
import { clearSessionCookie, getSessionToken } from "@/lib/server/session";

/** Turn the current demo session into a free account, then sign in with it. */
export async function POST(request: NextRequest) {
  const credentials = await readCredentials(request);
  if (credentials instanceof Response) return credentials;
  const token = getSessionToken(request);
  if (!token) return errorResponse(401, "not_authenticated", "Not signed in");
  const converted = await callBackend("/auth/demo/convert", {
    method: "POST",
    token,
    json: credentials,
    clientIp: clientIpOf(request),
  });
  if (converted.status !== 200) {
    const response = relay(converted);
    if (converted.status === 401) clearSessionCookie(response, request);
    return response;
  }
  return loginAndSetCookie(request, credentials);
}
