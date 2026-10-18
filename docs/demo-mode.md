# Demo mode ("Try the demo")

Visitors can try the product without registering. Code:
`app/services/demo_service.py`, `app/api/routes/auth.py` (`/auth/demo`,
`/auth/demo/convert`), migration `alembic/versions/20261018_0003_demo_users.py`,
frontend `src/app/api/auth/demo/route.ts`, `src/components/demo/*`.

## Flow

1. "Try the demo" (landing page, login and register pages) posts to the BFF route
   `/api/auth/demo` (CSRF header + Origin check), which calls `POST /auth/demo` and stores
   the returned token in the usual HttpOnly `dip_session` cookie. The browser never sees
   the token.
2. The API creates a user with `is_demo = true`, an address `demo-<random>@demo.invalid`
   (RFC 2606, cannot receive mail and is rejected by the login schema), a random
   password nobody knows (password login is refused for demo users anyway) and
   `demo_expires_at = now + DEMO_TTL_HOURS`. The session token lives at most 2 hours.
3. The app shell shows a banner "Demo: N of 3 questions left" with a "Create free
   account" button.
4. At a limit the API answers **403 `demo_limit_reached`** with
   `details: [{"limit": "questions" | "uploads" | "file_size" | "file_type" | "disabled"}]`;
   the UI opens the modal "Create a free account to continue".
5. "Create free account" in the banner or modal converts the demo
   (`POST /auth/demo/convert` with email + password): limits and expiry are removed,
   documents are kept, and the BFF logs in with the new credentials.

## Limits (server-side)

| Limit | Setting | Default | How it is enforced |
| --- | --- | --- | --- |
| Questions | `DEMO_MAX_QUESTIONS` | 3 | `UPDATE users SET demo_questions_used = demo_questions_used + 1 WHERE id = :id AND demo_questions_used < :max RETURNING ...` before the LLM call; given back if the LLM was never called (below the evidence threshold, LLM error/503) |
| Uploads | `DEMO_MAX_UPLOADS` | 1 | same pattern on `demo_uploads_used`; given back when the upload fails (wrong type, too large, storage error, duplicate) |
| File size | `DEMO_MAX_UPLOAD_BYTES` | 5 MB | enforced while streaming (`min(MAX_UPLOAD_SIZE_BYTES, DEMO_MAX_UPLOAD_BYTES)`) |
| File types | `DEMO_ALLOWED_EXTENSIONS` | `pdf` | checked after the normal type/magic-byte validation |
| Lifetime | `DEMO_TTL_HOURS` | 24 | expired users get 401 immediately; the beat task deletes them |
| New demos per IP | `RATE_LIMIT_DEMO` | 3/day | fixed window in Redis, fails closed (503) when Redis is down |
| New demos overall | `RATE_LIMIT_DEMO_GLOBAL` | 200/day | one shared counter; caps the worst-case LLM cost |
| Off switch | `DEMO_ENABLED` | true | `false` makes `POST /auth/demo` answer 403 `demo_limit_reached` (`disabled`) |

Counters are persistent columns, so restarting the API or clearing Redis does not reset
them. Search, listing, document details and status are not limited beyond the normal
rate limits.

Worst-case LLM cost per day: `RATE_LIMIT_DEMO_GLOBAL × DEMO_MAX_QUESTIONS` = 600
gpt-4o-mini calls with the defaults (each about 2-5k input tokens).

## Isolation

Demo users are ordinary owners: every document, chunk, search and ask query is
filtered by `owner_id` in SQL, exactly as for registered users (tested: a demo user sees
no other user's documents, gets 404 for their ids, cannot use admin endpoints).

## Expiry and cleanup

Beat task `users.cleanup_expired_demos` (every `DEMO_CLEANUP_INTERVAL_SECONDS`, 900 s;
`0` disables it) deletes expired demo users in batches of 200. Documents, chunks and
jobs cascade in PostgreSQL; the stored files are deleted afterwards (a failed file
delete is logged, and the orphaned file is harmless). Audit log rows keep the action with
`user_id = NULL`. The task runs even with `DEMO_ENABLED=false`, so old demos still expire.
Locally the embedded beat of the worker runs it; in production the `beat` service.

## Per-IP limits behind the BFF

Browser requests reach the API from the BFF's server, so per-IP limits would count the
BFF (Vercel) egress IP. With `CLIENT_IP_HEADER_SECRET` (API) and the same value as
`DIP_CLIENT_IP_SECRET` (frontend server env), the BFF sends `X-DIP-Client-IP` (taken
from Vercel's `x-forwarded-for`) and `X-DIP-Client-Secret`; the API accepts the header
only with the right secret (constant-time compare) and a valid IP. Without the secret
every demo visitor shares one per-IP budget.

## Metrics and logs

`dip_demo_events_total{event=created|converted|limit_questions|limit_uploads|expired_deleted}`;
log events `demo.created`, `demo.converted`, `demo.cleanup` (count only).

## Tests

`tests/api/test_demo.py` (creation, no password login, upload/type/size limits and
refunds, 3 questions then 403, below-threshold and LLM failures not counted, regular
users unaffected, isolation, conversion, expiry + file cleanup, batches, atomic
counters, disabled, per-IP and global rate limits) and
`tests/unit/test_http_hardening.py` (fail closed, trusted client IP header).
