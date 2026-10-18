# ADR-006: Frontend authentication - HttpOnly session cookie behind a Next.js BFF, direct uploads with an upload-only token

**Status:** Accepted (production phase)

## Context
The Next.js frontend is deployed on Vercel (`https://<project>.vercel.app`); the FastAPI
API runs on an Oracle Cloud VM behind Caddy (`https://api.<domain>` or
`<ip>.sslip.io`). These are **different sites** (different registrable domains;
`vercel.app` is on the Public Suffix List, so every project is its own site).

The API issues short-lived bearer JWTs (`POST /auth/login`, 30 min by default) and has
no cookie support. Requirements: never put tokens in `localStorage` or URLs if
avoidable, never log tokens, and support uploads up to `MAX_UPLOAD_SIZE_BYTES`
(10 MiB by default).

## Options considered
1. **Token in `localStorage`, browser calls the API directly.** Simplest, but any XSS
   can read and exfiltrate the token. Rejected.
2. **API sets an HttpOnly `Secure; SameSite=None` cookie, browser calls the API
   directly (CORS with credentials).** The cookie belongs to the API's site, so from
   the Vercel page it is a *third-party* cookie. Safari (ITP) and Firefox (Total Cookie
   Protection) already block or partition such cookies and Chrome lets users block them,
   so sign-in breaks for part of the audience unless the API and frontend share a
   registrable domain (which requires owning a domain - not guaranteed here).
   `SameSite=None` also needs a full CSRF defence on the API. Would require reworking
   the backend auth. Rejected for now.
3. **Backend-for-frontend (BFF) proxy in Next.js route handlers.** The browser only
   talks to its own origin; `/api/auth/*` logs in at the API server-side and stores the
   JWT in an HttpOnly, `SameSite=Lax`, `Secure` (on HTTPS) **first-party** cookie;
   `/api/proxy/*` attaches it as `Authorization: Bearer` when calling the API. Problem:
   Vercel Functions accept request bodies of about **4.5 MB**, below the 10 MiB upload
   limit, and streaming file bodies through a function adds latency and cost.
4. **Option 3 plus direct uploads with a short-lived, upload-only token.** Chosen.

## Decision
- Session: JWT in the `dip_session` cookie - `HttpOnly`, `SameSite=Lax`, `Secure` when
  the request is HTTPS, `Path=/`, `Max-Age` = token lifetime minus 30 s. Page scripts
  cannot read it. Logout deletes the cookie (JWTs are stateless and expire on their own).
- CSRF (cookie-authenticated, state-changing calls to `/api/*`): `SameSite=Lax`, plus a
  required custom header `X-DIP-CSRF: 1` (cannot be sent cross-site without a CORS
  preflight, which these handlers never approve), plus an `Origin` header that must equal
  the frontend's host. Login/register/logout are covered too (login-CSRF).
- The proxy forwards only an explicit allowlist of method + path pairs (documents,
  status, reprocess, delete, search, ask, me, audit log) and only `page`/`page_size`
  query parameters; JSON bodies are capped at 32 KiB.
- Uploads: the browser calls `POST /api/auth/upload-token` (CSRF-checked), which calls
  the new `POST /auth/upload-token` on the API with the session token and returns a JWT
  with `type=upload`, valid for `UPLOAD_TOKEN_EXPIRE_SECONDS` (300 s by default). The
  browser then sends the file straight to `POST {NEXT_PUBLIC_API_URL}/documents` with
  `XMLHttpRequest` (upload progress) and `Authorization: Bearer <upload token>`. The API
  accepts the `upload` type **only** on `POST /documents` (covered by
  `tests/api/test_upload_token.py`: 401 on every other endpoint). The token lives in a
  JavaScript closure for one upload and is never stored.
- CORS on the API stays `allow_credentials=False` and only lists the frontend origin(s)
  (`CORS_ALLOWED_ORIGINS`), which is all direct uploads need.
- Only `NEXT_PUBLIC_API_URL` is configured in the frontend; it is not a secret.

## Consequences
- An XSS bug could still *use* the session (by calling `/api/proxy/*` from the page) and
  could obtain an upload token, but could not steal the long-lived session token; an
  upload token can only add documents for 5 minutes. A strict CSP (`connect-src 'self'
  <api>`, `frame-ancestors 'none'`) is sent by `next.config.ts`.
- All authenticated API traffic comes from Vercel's servers, so the API's **per-IP**
  limits (register, login) count Vercel egress addresses rather than end users. The
  per-email login limit (5/minute) still stops password guessing for one account; the
  production defaults for per-IP limits are set with this in mind. Forwarding the real
  client IP would need a shared secret between Vercel and the API (not implemented).
- One extra hop (Vercel → API) per call; `/ask` is bounded by the route's
  `maxDuration = 60` and the API's `LLM_TIMEOUT_SECONDS`.
- If the frontend and API later share a registrable domain, option 2 becomes viable and
  removes the proxy hop.

## Verification
VERIFIED LOCALLY (Playwright, production-like stack with HTTPS): cookie is HttpOnly,
SameSite=Lax and Secure; `document.cookie`, `localStorage` and `sessionStorage` contain
no token; uploads go to the API with `Authorization: Bearer` and no cookie; a proxy POST
without the CSRF header gets 403. NOT VERIFIED on Vercel itself (no access).
