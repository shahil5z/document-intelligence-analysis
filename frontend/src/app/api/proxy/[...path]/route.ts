import type { NextRequest } from "next/server";

import { callBackend, errorResponse, relay } from "@/lib/server/backend";
import { csrfProblem } from "@/lib/server/csrf";
import { clearSessionCookie, getSessionToken } from "@/lib/server/session";

// Allow /ask to wait for the LLM (LLM_TIMEOUT_SECONDS defaults to 30 s).
export const maxDuration = 60;

const UUID = "[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}";
const MAX_JSON_BODY_BYTES = 32 * 1024;

interface RouteRule {
  method: "GET" | "POST" | "DELETE";
  pattern: RegExp;
  query?: string[];
  timeoutMs?: number;
}

// Only these backend endpoints are reachable through the proxy. Uploads are not: the
// browser sends files directly to the API with an upload-only token.
const RULES: RouteRule[] = [
  { method: "GET", pattern: /^auth\/me$/ },
  { method: "GET", pattern: /^documents$/, query: ["page", "page_size"] },
  { method: "GET", pattern: /^documents\/upload-policy$/ },
  { method: "GET", pattern: new RegExp(`^documents/${UUID}$`) },
  { method: "GET", pattern: new RegExp(`^documents/${UUID}/status$`) },
  { method: "DELETE", pattern: new RegExp(`^documents/${UUID}$`) },
  { method: "POST", pattern: new RegExp(`^documents/${UUID}/reprocess$`) },
  { method: "POST", pattern: /^search$/ },
  { method: "POST", pattern: /^ask$/, timeoutMs: 55_000 },
  { method: "GET", pattern: /^audit-logs\/me$/, query: ["page", "page_size"] },
];

async function forward(
  request: NextRequest,
  context: { params: Promise<{ path: string[] }> },
): Promise<Response> {
  const { path } = await context.params;
  const joined = path.join("/").toLowerCase();
  const rule = RULES.find((r) => r.method === request.method && r.pattern.test(joined));
  if (!rule) return errorResponse(404, "not_found", "Not found");

  if (request.method !== "GET" && csrfProblem(request)) {
    return errorResponse(403, "forbidden", "Request blocked (CSRF check failed)");
  }
  const token = getSessionToken(request);
  if (!token) return errorResponse(401, "not_authenticated", "Not signed in");

  let json: unknown;
  if (request.method === "POST") {
    const text = await request.text();
    if (text.length > MAX_JSON_BODY_BYTES) {
      return errorResponse(413, "payload_too_large", "Request body is too large");
    }
    if (text) {
      try {
        json = JSON.parse(text);
      } catch {
        return errorResponse(422, "validation_error", "Request body must be JSON");
      }
    }
  }

  const query = new URLSearchParams();
  for (const name of rule.query ?? []) {
    const value = request.nextUrl.searchParams.get(name);
    if (value !== null && /^\d{1,6}$/.test(value)) query.set(name, value);
  }
  const suffix = query.size > 0 ? `?${query.toString()}` : "";
  const result = await callBackend(`/${joined}${suffix}`, {
    method: request.method,
    token,
    json,
    timeoutMs: rule.timeoutMs,
    requestId: request.headers.get("x-request-id"),
  });
  const response = relay(result);
  if (result.status === 401) clearSessionCookie(response, request);
  return response;
}

export const GET = forward;
export const POST = forward;
export const DELETE = forward;
