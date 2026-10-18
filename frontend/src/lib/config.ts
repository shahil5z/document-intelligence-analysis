/** Public URL of the FastAPI backend (no trailing slash). Not a secret. */
export const API_URL = (process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000").replace(
  /\/+$/,
  "",
);

/** Header every state-changing call to the /api/* route handlers must carry (CSRF). */
export const CSRF_HEADER = "x-dip-csrf";
export const CSRF_VALUE = "1";
