import type { ApiErrorBody } from "./types";

/** An error answer from the API (or the route handlers), or a network failure (status 0). */
export class ApiError extends Error {
  readonly status: number;
  readonly code: string;
  readonly requestId: string | null;
  readonly retryAfterSeconds: number | null;
  /** For demo_limit_reached: which limit ("questions", "uploads", "file_size", ...). */
  readonly limit: string | null;

  constructor(
    status: number,
    code: string,
    message: string,
    requestId: string | null = null,
    retryAfterSeconds: number | null = null,
    limit: string | null = null,
  ) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.code = code;
    this.requestId = requestId;
    this.retryAfterSeconds = retryAfterSeconds;
    this.limit = limit;
  }
}

export const DEMO_LIMIT_EVENT = "dip:demo-limit";

export function isDemoLimit(error: unknown): error is ApiError {
  return error instanceof ApiError && error.code === "demo_limit_reached";
}

export function apiErrorFromBody(
  status: number,
  body: unknown,
  headers?: Headers,
): ApiError {
  const detail = (body as ApiErrorBody | null)?.error;
  const retry = headers?.get("retry-after");
  const retryAfter = retry && /^\d+$/.test(retry) ? Number(retry) : null;
  const limit = detail?.details?.find((d) => typeof d?.limit === "string")?.limit ?? null;
  return new ApiError(
    status,
    detail?.code ?? "http_error",
    detail?.message ?? `Request failed (${status})`,
    detail?.request_id ?? headers?.get("x-request-id") ?? null,
    retryAfter,
    limit,
  );
}

export interface FriendlyError {
  title: string;
  message: string;
  requestId: string | null;
}

/** "in 42 seconds", "in about 3 minutes", "in about 5 hours" (from Retry-After). */
export function describeWait(seconds: number | null): string {
  if (seconds === null) return "Please wait a moment and try again.";
  if (seconds <= 1) return "Please try again in a second.";
  if (seconds < 90) return `Please try again in ${seconds} seconds.`;
  const minutes = Math.ceil(seconds / 60);
  if (minutes < 90) return `Please try again in about ${minutes} minutes.`;
  const hours = Math.ceil(minutes / 60);
  return `Please try again in about ${hours} hour${hours === 1 ? "" : "s"}.`;
}

/** Turn any thrown value into a short, human message. Never shows raw JSON or stacks. */
export function friendlyError(error: unknown): FriendlyError {
  if (!(error instanceof ApiError)) {
    return {
      title: "Something went wrong",
      message: "An unexpected error occurred. Please try again.",
      requestId: null,
    };
  }
  const requestId = error.requestId;
  const message = error.message;
  switch (true) {
    case error.status === 0:
      return {
        title: "Service unavailable",
        message: "The server could not be reached. Check your connection and try again.",
        requestId,
      };
    case error.status === 401:
      return {
        title: "Session expired",
        message: "Your session has ended. Please sign in again.",
        requestId,
      };
    case error.code === "demo_limit_reached":
      return { title: "Demo limit reached", message, requestId };
    case error.status === 403:
      return { title: "Not allowed", message: "You don't have access to this.", requestId };
    case error.status === 404:
      return {
        title: "Not found",
        message: "This item does not exist or you don't have access to it.",
        requestId,
      };
    case error.status === 413 || error.code === "payload_too_large":
      return { title: "File too large", message, requestId };
    case error.status === 415 || error.code === "unsupported_media_type":
      return { title: "Unsupported file", message, requestId };
    case error.code === "invalid_upload":
      return { title: "File rejected", message, requestId };
    case error.status === 409:
      return { title: "Conflict", message, requestId };
    case error.status === 429:
      return {
        title: "Too many requests",
        message: `You've reached the rate limit for this action. ${describeWait(error.retryAfterSeconds)}`,
        requestId,
      };
    case error.status === 422 || error.status === 400:
      return { title: "Check your input", message, requestId };
    case error.status === 503 && /not configured/i.test(message):
      return {
        title: "AI answers are not configured",
        message:
          "Question answering is turned off on this server (no LLM key configured). Search still works.",
        requestId,
      };
    case error.status === 503 || error.status === 502 || error.status === 504:
      return {
        title: "Service temporarily unavailable",
        message: "A backend service is not responding right now. Please try again shortly.",
        requestId,
      };
    default:
      return {
        title: "Something went wrong",
        message: "The server could not complete the request. Please try again.",
        requestId,
      };
  }
}

/** Plain-language message for a document whose processing job failed. */
export function processingFailureMessage(errorMessage: string | null | undefined): string {
  const detail = errorMessage?.trim();
  return detail
    ? `Processing failed: ${detail}`
    : "Processing failed. You can try reprocessing the document.";
}
