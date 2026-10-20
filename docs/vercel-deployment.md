# Frontend on Vercel

The Next.js app in `frontend/` (App Router, TypeScript, Tailwind) is designed for
Vercel.

**Status: deployed.** Production: https://doc-intelligence-shahil.vercel.app (also
`document-intelligence-analysis-shahils-projects-e75357dc.vercel.app`). Vercel project
`document-intelligence-analysis`, root directory `frontend`, framework Next.js, Node 22,
linked to `shahil5z/document-intelligence-analysis` (pushes to `main` deploy to
production). Vercel Authentication protects preview deployments only, so the
production demo is public. Verified on 2026-10-20 with a headless Playwright run
against the live URL (register, upload, search, one real `/ask`, logout).

## How the frontend talks to the API

Details and alternatives: [ADR-006](adr/ADR-006-frontend-auth-bff.md).

- **Backend-for-frontend.** Login/register go to Next.js route handlers
  (`/api/auth/*`), which call the API server-side and store the JWT in an **HttpOnly,
  SameSite=Lax** cookie (Secure on HTTPS) (`dip_session`). Browser JavaScript never sees the token;
  nothing is put in `localStorage` or in URLs.
- All other reads/writes go through `/api/proxy/...`, which forwards to an allow-list of
  API paths with `Authorization: Bearer <cookie token>`. State-changing calls must carry
  `X-DIP-CSRF: 1` and a same-origin `Origin`.
- **Uploads go directly from the browser to the API** with a 300-second, upload-only
  token from `/api/auth/upload-token` (kept in memory for one request). Reason: Vercel
  functions cap request bodies at about 4.5 MB, below the 10 MB upload limit. The API
  accepts that token only for `POST /documents`. The API's CORS therefore must allow the
  Vercel origin.

## Project settings

1. Vercel > Add New > Project > import the Git repository.
2. **Root Directory: `frontend`**. Framework preset: Next.js (auto-detected). Build
   command `npm run build`, install `npm ci`, output default. Node.js 20.9+ (22 is
   what CI uses).
3. Environment variables (Production, and Preview if you use previews):

   | Name | Value | Secret? |
   | --- | --- | --- |
   | `NEXT_PUBLIC_API_URL` | `https://<API_DOMAIN>` (no trailing slash) | **No.** It is compiled into the browser bundle and the CSP. Never put a key in any `NEXT_PUBLIC_*` variable. |
   | `DIP_CLIENT_IP_SECRET` | random, equal to `CLIENT_IP_HEADER_SECRET` on the API | **Yes**, server-only (Vercel type *sensitive*, Production). Lets the BFF pass the browser IP so per-IP limits (register, login, demo) count real users instead of Vercel's egress IPs. |

   Live values: `NEXT_PUBLIC_API_URL=https://api-140-245-232-103.sslip.io`. The OpenAI key
   lives only on the API server.
   `NEXT_PUBLIC_*` values are fixed at build time: after changing it, redeploy.
4. Deploy. Note the production URL, e.g. `https://dip-yourname.vercel.app`.
5. On the server set `CORS_ALLOWED_ORIGINS=https://dip-yourname.vercel.app` in
   `.env.production` and run `scripts/deploy.sh`. Preview deployments have different
   origins; add them explicitly (comma-separated) only if you need uploads from previews.

## Security headers

`next.config.ts` sets a Content-Security-Policy (`default-src 'self'`, `connect-src
'self' <NEXT_PUBLIC_API_URL>`, `frame-ancestors 'none'`, `object-src 'none'`; scripts
allow `'unsafe-inline'` because Next.js injects inline bootstrap scripts),
`X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY`,
`Referrer-Policy: strict-origin-when-cross-origin`, `Permissions-Policy` (camera,
microphone, geolocation off), `Cross-Origin-Opener-Policy: same-origin`, no
`X-Powered-By`, and `Cache-Control: no-store` on `/api/*`.

## Limitations on Vercel

- Without `DIP_CLIENT_IP_SECRET`, per-IP rate limits on register/login/demo would count
  Vercel's egress IPs, because the BFF calls the API from Vercel. With it set (as in
  production) the API uses the forwarded browser IP. Uploads, search and ask are
  limited per user.
- The session lifetime equals the API token lifetime (30 minutes by default); there are
  no refresh tokens, so users sign in again after expiry.
- `/api/proxy` runs with `maxDuration = 60` seconds; `/ask` normally finishes far
  sooner (LLM timeout 30 s).

## Local run

```bash
cd frontend
cp .env.example .env.local          # NEXT_PUBLIC_API_URL=http://localhost:8000
npm ci
npm run dev                         # http://localhost:3000
```

The API's default `CORS_ALLOWED_ORIGINS` already includes `http://localhost:3000`.
