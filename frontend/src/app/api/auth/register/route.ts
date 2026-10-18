import type { NextRequest } from "next/server";

import { callBackend, relay } from "@/lib/server/backend";
import { loginAndSetCookie, readCredentials } from "@/lib/server/auth-handlers";

export async function POST(request: NextRequest) {
  const credentials = await readCredentials(request);
  if (credentials instanceof Response) return credentials;
  const created = await callBackend("/auth/register", { method: "POST", json: credentials });
  if (created.status !== 201) return relay(created);
  return loginAndSetCookie(request, credentials);
}
