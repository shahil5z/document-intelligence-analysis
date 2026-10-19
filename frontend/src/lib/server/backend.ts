import "server-only";

import { NextResponse } from "next/server";

import { API_URL } from "@/lib/config";

const DEFAULT_TIMEOUT_MS = 30_000;

export interface BackendResult {
  status: number;
  headers: Headers;
  body: unknown;
}

/** Call the FastAPI backend from the server. Never logs tokens or bodies. */
export async function callBackend(
  path: string,
  init: {
    method?: string;
    token?: string | null;
    json?: unknown;
    timeoutMs?: number;
    requestId?: string | null;
    /** Browser IP to pass on for the API's per-IP limits (needs DIP_CLIENT_IP_SECRET). */
    clientIp?: string | null;
  } = {},
): Promise<BackendResult> {
  const headers = new Headers({ accept: "application/json" });
  const clientIpSecret = process.env.DIP_CLIENT_IP_SECRET;
  if (clientIpSecret && init.clientIp) {
    headers.set("x-dip-client-ip", init.clientIp);
    headers.set("x-dip-client-secret", clientIpSecret);
  }
  if (init.token) headers.set("authorization", `Bearer ${init.token}`);
  if (init.json !== undefined) headers.set("content-type", "application/json");
  if (init.requestId) headers.set("x-request-id", init.requestId);
  try {
    const response = await fetch(`${API_URL}${path}`, {
      method: init.method ?? "GET",
      headers,
      body: init.json === undefined ? undefined : JSON.stringify(init.json),
      cache: "no-store",
      redirect: "manual",
      signal: AbortSignal.timeout(init.timeoutMs ?? DEFAULT_TIMEOUT_MS),
    });
    const text = await response.text();
    let body: unknown = null;
    if (text) {
      try {
        body = JSON.parse(text);
      } catch {
        body = null;
      }
    }
    return { status: response.status, headers: response.headers, body };
  } catch (error) {
    const timedOut = error instanceof DOMException && error.name === "TimeoutError";
    return {
      status: timedOut ? 504 : 502,
      headers: new Headers(),
      body: {
        error: {
          code: "service_unavailable",
          message: timedOut ? "The API did not answer in time" : "The API could not be reached",
        },
      },
    };
  }
}

const PASSTHROUGH_HEADERS = ["retry-after", "x-request-id"];

/** Relay a backend answer to the browser (JSON only; status and safe headers kept). */
export function relay(result: BackendResult): NextResponse {
  const response =
    result.status === 204 || result.body === null
      ? new NextResponse(null, { status: result.status })
      : NextResponse.json(result.body, { status: result.status });
  for (const name of PASSTHROUGH_HEADERS) {
    const value = result.headers.get(name);
    if (value) response.headers.set(name, value);
  }
  response.headers.set("cache-control", "no-store");
  return response;
}

export function errorResponse(status: number, code: string, message: string): NextResponse {
  return NextResponse.json({ error: { code, message } }, { status });
}

/**
 * The browser's IP as seen by this server: the first x-forwarded-for entry (set by
 * Vercel / the local reverse proxy) or x-real-ip. Only forwarded to the API together
 * with DIP_CLIENT_IP_SECRET, which the API checks; the API ignores it otherwise.
 */
export function clientIpOf(request: Request): string | null {
  const forwarded = request.headers.get("x-forwarded-for")?.split(",")[0]?.trim();
  const ip = forwarded || request.headers.get("x-real-ip")?.trim() || "";
  return /^[0-9a-fA-F:.]{2,45}$/.test(ip) ? ip : null;
}
