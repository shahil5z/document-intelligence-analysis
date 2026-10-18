import type { NextRequest } from "next/server";

import { loginAndSetCookie, readCredentials } from "@/lib/server/auth-handlers";

export async function POST(request: NextRequest) {
  const credentials = await readCredentials(request);
  if (credentials instanceof Response) return credentials;
  return loginAndSetCookie(request, credentials);
}
