"use client";

import { API_URL, CSRF_HEADER, CSRF_VALUE } from "@/lib/config";
import { ApiError, DEMO_LIMIT_EVENT, apiErrorFromBody, isDemoLimit } from "@/lib/errors";
import type { DemoStatus, UploadResponse } from "@/lib/types";

const SESSION_EXPIRED_EVENT = "dip:session-expired";

/** Any demo_limit_reached answer opens the "create a free account" modal. */
export function announceDemoLimit(error: ApiError): void {
  window.dispatchEvent(new CustomEvent(DEMO_LIMIT_EVENT, { detail: { limit: error.limit, message: error.message } }));
}

export function onDemoLimit(listener: (detail: { limit: string | null; message: string }) => void): () => void {
  const handler = (event: Event) => listener((event as CustomEvent).detail);
  window.addEventListener(DEMO_LIMIT_EVENT, handler);
  return () => window.removeEventListener(DEMO_LIMIT_EVENT, handler);
}

export function onSessionExpired(listener: () => void): () => void {
  window.addEventListener(SESSION_EXPIRED_EVENT, listener);
  return () => window.removeEventListener(SESSION_EXPIRED_EVENT, listener);
}

async function request<T>(url: string, method: string, body?: unknown): Promise<T> {
  const headers: Record<string, string> = { accept: "application/json" };
  if (method !== "GET") headers[CSRF_HEADER] = CSRF_VALUE;
  if (body !== undefined) headers["content-type"] = "application/json";
  let response: Response;
  try {
    response = await fetch(url, {
      method,
      headers,
      body: body === undefined ? undefined : JSON.stringify(body),
      credentials: "same-origin",
      cache: "no-store",
    });
  } catch {
    throw new ApiError(0, "network_error", "Network error");
  }
  const text = await response.text();
  let parsed: unknown = null;
  if (text) {
    try {
      parsed = JSON.parse(text);
    } catch {
      parsed = null;
    }
  }
  if (!response.ok) {
    const error = apiErrorFromBody(response.status, parsed, response.headers);
    if (response.status === 401 && !url.startsWith("/api/auth/")) {
      window.dispatchEvent(new Event(SESSION_EXPIRED_EVENT));
    }
    if (isDemoLimit(error)) announceDemoLimit(error);
    throw error;
  }
  return parsed as T;
}

/** Calls the backend through the same-origin proxy (the HttpOnly cookie authenticates). */
export const api = {
  get: <T>(path: string) => request<T>(`/api/proxy/${path}`, "GET"),
  post: <T>(path: string, body?: unknown) => request<T>(`/api/proxy/${path}`, "POST", body),
  delete: <T>(path: string) => request<T>(`/api/proxy/${path}`, "DELETE"),
};

export const auth = {
  login: (email: string, password: string) =>
    request<{ authenticated: boolean }>("/api/auth/login", "POST", { email, password }),
  register: (email: string, password: string) =>
    request<{ authenticated: boolean }>("/api/auth/register", "POST", { email, password }),
  logout: () => request<{ authenticated: boolean }>("/api/auth/logout", "POST"),
  demo: () => request<{ authenticated: boolean; demo: DemoStatus | null }>("/api/auth/demo", "POST"),
  convertDemo: (email: string, password: string) =>
    request<{ authenticated: boolean }>("/api/auth/demo/convert", "POST", { email, password }),
};

export interface UploadHandle {
  promise: Promise<UploadResponse>;
  abort: () => void;
}

/**
 * Upload straight to the API with XMLHttpRequest (for progress events), authorised by a
 * 5-minute upload-only token fetched just before. The token stays in this closure only.
 */
export function uploadDocument(file: File, onProgress: (fraction: number) => void): UploadHandle {
  const xhr = new XMLHttpRequest();
  let aborted = false;
  const promise = (async () => {
    const { upload_token: uploadToken } = await request<{ upload_token: string }>(
      "/api/auth/upload-token",
      "POST",
    );
    if (aborted) throw new ApiError(0, "aborted", "Upload cancelled");
    return new Promise<UploadResponse>((resolve, reject) => {
      xhr.open("POST", `${API_URL}/documents`);
      xhr.setRequestHeader("Authorization", `Bearer ${uploadToken}`);
      xhr.setRequestHeader("Accept", "application/json");
      xhr.responseType = "text";
      xhr.upload.onprogress = (event) => {
        if (event.lengthComputable && event.total > 0) onProgress(event.loaded / event.total);
      };
      xhr.onerror = () => reject(new ApiError(0, "network_error", "Network error"));
      xhr.onabort = () => reject(new ApiError(0, "aborted", "Upload cancelled"));
      xhr.onload = () => {
        let parsed: unknown = null;
        try {
          parsed = xhr.responseText ? JSON.parse(xhr.responseText) : null;
        } catch {
          parsed = null;
        }
        if (xhr.status >= 200 && xhr.status < 300) {
          onProgress(1);
          resolve(parsed as UploadResponse);
          return;
        }
        const headers = new Headers();
        const retry = xhr.getResponseHeader("Retry-After");
        if (retry) headers.set("retry-after", retry);
        const requestId = xhr.getResponseHeader("X-Request-ID");
        if (requestId) headers.set("x-request-id", requestId);
        const error = apiErrorFromBody(xhr.status, parsed, headers);
        if (isDemoLimit(error)) announceDemoLimit(error);
        reject(error);
      };
      const form = new FormData();
      form.append("file", file, file.name);
      xhr.send(form);
    });
  })();
  return {
    promise,
    abort: () => {
      aborted = true;
      xhr.abort();
    },
  };
}
