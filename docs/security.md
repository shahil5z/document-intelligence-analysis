# Security

Scope: the final system (DIP1 + DIP2 + DIP3 + final fixes + production phase: Next.js
frontend, production compose, Caddy, ops scripts). Every control below names
where it lives and what tests it. Verification numbers are in
[FINAL_PROJECT_REPORT.md](../FINAL_PROJECT_REPORT.md).

## Authentication and authorization

- Passwords: Argon2id via `pwdlib` (`app/core/security.py`). Login errors are generic;
  an unknown e-mail still runs a dummy hash so timing does not reveal accounts.
- JWT (PyJWT, HS256/384/512): `sub`, `role`, `type`, `jti`, `iat`, `exp`, `iss` are all
  required; issuer and algorithm are pinned on decode; default lifetime 30 minutes. The
  role and active flag are re-read from the database on every request, so a tampered
  role claim or a deleted user's token gets 401 (`tests/api/test_security_matrix.py`).
- No refresh tokens, revocation list or account lockout (rate limits only).

## Tenant isolation

Every repository query that reads documents, jobs, chunks or audit entries takes the
caller's id and filters inside SQL. Chunk queries filter `c.owner_id = :caller` **and**
join `documents` with `d.owner_id = :caller AND d.status = 'completed'`; results are
never filtered in Python afterwards. Foreign ids return 404, never 403.

Cross-user matrix (`tests/api/test_security_matrix.py`, plus the live smoke test):
GET document, GET status, DELETE, reprocess, list, search in all three modes,
search/ask with a foreign `document_id`, audit log - all 404 or empty for another user.

## Rate limiting

Fixed-window counters in Redis (INCR + EXPIRE; keys contain a SHA-256 of the IP or
e-mail, never the raw value). Exceeding a limit returns 429 `rate_limited` with
`Retry-After` (seconds until the window ends); the frontend shows "Too many requests -
try again in N seconds/minutes".

### Rate limits

| Endpoint | Scope (setting `RATE_LIMIT_*`) | Key | Default (class / `.env.example`) | `docker-compose.prod.yml` | Redis down |
| --- | --- | --- | --- | --- | --- |
| `POST /auth/register` | `REGISTER` + `REGISTER_DAILY` | IP | 5/minute + 20/day | 10/hour + 20/day | 503 (closed) |
| `POST /auth/login`, `/auth/token` | `LOGIN` | IP | 10/minute | 10/minute | 503 (closed) |
| same | `LOGIN_PER_EMAIL` | e-mail | 5/minute | 5/minute | 503 (closed) |
| `POST /auth/demo` | `DEMO` | IP | 3/day | 3/day | 503 (closed) |
| same | `DEMO_GLOBAL` | one global key | 200/day | 200/day | 503 (closed) |
| `POST /auth/demo/convert` | `REGISTER` + `REGISTER_DAILY` | IP | as register | as register | 503 (closed) |
| `POST /auth/upload-token` | `UPLOAD_TOKEN` | user | 30/minute | 30/minute | open |
| `POST /documents` | `UPLOAD` + `UPLOAD_DAILY` | user | 10/minute + 100/day | 30/day + 100/day | open |
| `POST /search` | `SEARCH` | user | 60/minute | 60/minute | open |
| `POST /ask` | `ASK` + `ASK_DAILY` | user | 10/minute + 200/day | 20/hour + 200/day | open |
| `POST /documents/{id}/reprocess` | `REPROCESS` | user | 10/minute | 20/day | open |

Read-only authenticated endpoints (lists, details, status, `/auth/me`) are not limited.
Demo accounts additionally have hard usage limits ([demo-mode.md](demo-mode.md)).
"IP" is the TCP peer, or the `X-DIP-Client-IP` header when it comes with the
`CLIENT_IP_HEADER_SECRET` (the BFF; see demo-mode.md#per-ip-limits-behind-the-bff).

**When Redis is unavailable** (`app/api/dependencies/rate_limit.py`):

| Scope | Decision | Response |
| --- | --- | --- |
| `register`, `register_daily`, `login`, `login_per_email`, `demo`, `demo_global` | **fail closed** | 503 `Sign-in and registration are temporarily unavailable; retry later`, `Retry-After: 5`; the password is not checked |
| `upload`, `upload_daily`, `upload_token`, `search`, `ask`, `ask_daily`, `reprocess` | **fail open** | request proceeds |

Both paths increment `dip_rate_limiter_errors_total{scope,decision}` and log
`rate_limit.backend_unavailable` with `error_type` only. Rationale: an attacker who can
make Redis unreachable must not get unlimited password guesses, while authenticated
users keep working during a short Redis outage. Tested in
`tests/unit/test_http_hardening.py` and live (Redis container stopped: login and
register 503, search and list 200).

The upload limit is checked after the multipart body has been received (bounded by the
body limit below).

## Request size

`BodySizeLimitMiddleware` (`app/core/middleware.py`) runs before routing:

- A declared `Content-Length` above the limit is answered with 413 **before the body is
  read** (raw ASGI test asserts `receive` is never called; the smoke test sends only the
  headers and gets 413).
- Chunked/undeclared bodies are counted while streaming and cut off at the limit.
- Limits: 1 MiB for JSON (`MAX_REQUEST_BODY_BYTES`), `MAX_UPLOAD_SIZE_BYTES` + 64 KiB
  overhead for `POST /documents`; the file part itself is limited to
  `MAX_UPLOAD_SIZE_BYTES` while it is streamed to storage.

## Uploads and untrusted files

- Extension and content-type allow-lists, magic-byte check, server-generated storage
  keys, sanitised display names, path-traversal guard, SHA-256 + per-user duplicate check.
- Parsers run in the worker, not in the API. PDF: `pypdf` non-strict, encrypted files
  rejected unless the empty password works. DOCX: total uncompressed size checked first
  (`MAX_DOCX_UNCOMPRESSED_BYTES`, zip-bomb guard). TXT: NUL bytes rejected.
- Bounds: `MAX_CHUNKS_PER_DOCUMENT`, Celery soft/hard time limits (240 s / 300 s).
- Not done: parser sandboxing, malware scanning, PDF sanitisation.

## Prompt injection and answer integrity

1. Retrieved text goes only into the user message inside `<untrusted_sources>`, never
   into the system message; `&`, `<`, `>` in excerpts and the question are escaped so
   text cannot close the wrapper or forge a `<source>`.
2. The system prompt says excerpts are data, not instructions.
3. **No retrieval, no LLM call**: when nothing is retrieved, or the best semantic
   similarity is below `MIN_EVIDENCE_SIMILARITY`, `/ask` returns
   `insufficient_evidence: true`, `model: null` without contacting the LLM.
4. Citation validation: `[S#]` labels that were not sent are stripped; citation metadata
   comes from database rows, never from model output. An empty model reply is treated
   as insufficient evidence.
5. LLM errors (timeout, connection, 4xx/5xx, malformed body) become `LLMError` and a
   controlled 503 without upstream details; a missing or placeholder key gives 503 "not
   configured" only after evidence was found.
6. The LLM has no tools; the worst case of a successful injection is a misleading answer
   to the uploader of that document (who can only inject into their own scope).

Tested in `tests/unit/test_answer_service.py`, `tests/unit/test_llm_provider.py`, the API
tests and the live smoke test against a stub that emits a forged `[S99]` citation (it
is removed). Limitation: injected text can still influence the answer wording; there
is no entailment or second-pass check.

## HTTP hardening

- Security headers on every response: `X-Content-Type-Options: nosniff`,
  `X-Frame-Options: DENY`, `Referrer-Policy: no-referrer`,
  `Cross-Origin-Resource-Policy: same-origin`; HSTS (`max-age=31536000;
  includeSubDomains`) only when `APP_ENV=production`.
- CORS: explicit origins only (`*` rejected at startup); production requires https.
- Swagger/ReDoc/OpenAPI off in production unless `API_DOCS_ENABLED=true`.
- Production refuses `DEBUG=true`, `LOG_LEVEL=DEBUG`, non-https CORS origins, http
  `LLM_BASE_URL`, the in-memory rate limiter.
- Unhandled errors return a generic 500 envelope without exception text.

## Secrets

- All secrets come from the environment as `SecretStr`; startup fails on missing or
  placeholder values, and messages name variables, never values.
- `OPENAI_API_KEY` is read only when `/ask` needs the LLM and sent only in the
  `Authorization` header; not logged, not returned, not in exceptions.
- `.env`, `.env.*` (except `.env.example`), a root file `env` and `*.bak` are git-ignored
  and excluded from the Docker build context.
- Redis: password required; compose writes it to a 0600 config file at container start
  instead of the command line, so it is not visible in `ps` / `docker top`
  (`REDISCLI_AUTH` for the healthcheck). It is still visible to anyone who can run
  `docker inspect` (container environment).
- Logs: no secrets or document text (live check: 0 occurrences, see observability.md).
- Repository audit: tracked files and full history contain only placeholders, local
  test credentials (`dip`) and fake test keys; no real key pattern
  ([report](../FINAL_PROJECT_REPORT.md#9-security-audit)).

## Containers and supply chain

- Base images pinned by multi-arch index digest (Dockerfile, compose, CI); bump
  procedure in [deployment.md](deployment.md#image-digests). Caddy is pinned the same way
  (`caddy:2-alpine@sha256:d8542f48...`).
- App containers run as uid 10001 with `cap_drop: [ALL]`, `no-new-privileges`, `init`.
  Postgres, Redis and the worker exporter are not published to the host.
- `pip-audit` on the locked dependencies: no known vulnerabilities (torch skipped by the
  tool). No image vulnerability scan; root filesystems are not read-only.
- Embedding model: downloaded from Hugging Face on first use; the revision is not
  pinned. Seed the cache and set `HF_HUB_OFFLINE=1` to stop network access.

## Frontend sessions (BFF) and uploads

Decision record: [ADR-006](adr/ADR-006-frontend-auth-bff.md).

- The JWT is stored only in the `dip_session` cookie: `HttpOnly`, `SameSite=Lax`,
  `Path=/`, `Secure` on HTTPS, lifetime = token lifetime - 30 s. It is never exposed to
  browser JavaScript, never in `localStorage`/`sessionStorage`, never in a URL, never
  logged. Verified by Playwright (cookie flags, empty web storage, no token in the page).
- CSRF: every state-changing route handler requires `X-DIP-CSRF: 1` **and** an `Origin`
  equal to the host; SameSite=Lax blocks cross-site cookie sends on POST as a second
  layer. Playwright asserts a 403 without the header.
- `/api/proxy/[...path]` forwards only an allow-list of API paths and methods, only the
  `page`/`page_size` query parameters, and JSON bodies up to 32 KiB.
- Uploads go browser -> API directly with a **300-second upload-only token**
  (`type=upload`): the API accepts it only on `POST /documents`; every other endpoint
  answers 401 (unit/API tests + smoke test). Normal access tokens still work for uploads.
- Errors shown to users come from a fixed mapping (`frontend/src/lib/errors.ts`); raw
  server messages and stack traces are not rendered.
- Security headers from `next.config.ts`: CSP (`default-src 'self'`, `connect-src 'self'
  <API URL>`, `frame-ancestors 'none'`, `object-src 'none'`; `script-src` needs
  `'unsafe-inline'` for Next.js bootstrap scripts), nosniff, `X-Frame-Options: DENY`,
  `Referrer-Policy: strict-origin-when-cross-origin`, `Permissions-Policy`, COOP
  same-origin, `Cache-Control: no-store` on `/api/*`.
- Only `NEXT_PUBLIC_API_URL` is exposed to the browser bundle; no secret uses the
  `NEXT_PUBLIC_` prefix (checked in the `.next` output, see the report).

## Production edge and server

- Caddy terminates TLS (automatic ACME certificates), redirects HTTP to HTTPS, serves
  HTTP/1.1 + HTTP/2 only, has its admin API off, answers `/metrics` with 404 and rejects
  bodies above 11 MB before they reach the API. Only 80/443 are published.
- PostgreSQL and Redis sit on an `internal: true` network: no published ports, no
  internet route. The API port 8000 and the worker exporter 9100 are internal only.
- CORS is restricted to the configured frontend origin(s) (`CORS_ALLOWED_ORIGINS`,
  https only in production).
- Public-demo rate limits in `docker-compose.prod.yml` (table above). Behind Vercel the
  per-IP limits count Vercel egress IPs unless `CLIENT_IP_HEADER_SECRET` /
  `DIP_CLIENT_IP_SECRET` are set.
- Missing `OPENAI_API_KEY` is not an error: `/ask` answers 503 "not configured", the
  rest works.
- `.env.production` must be mode 0600 (the scripts warn otherwise) and is git-ignored;
  the scripts refuse `<placeholder>` values and read single keys without `source`-ing
  the file. Backups are 0600 in a 0700 directory, optionally GPG-encrypted.
- `setup_server.sh` opens only 22/80/443 and leaves the SSH daemon configuration alone
  (disable password login yourself if your image allows it). Deploys over SSH from
  GitHub use a dedicated key and a pinned `known_hosts` (`StrictHostKeyChecking=yes`).
- `restore_postgres.sh` never overwrites the live database without
  `--replace-live-database --i-understand-this-overwrites-data` and a safety backup.

## Open gaps

Fixed windows allow bursts at window edges; upload rate limit after body receipt;
unauthenticated `/metrics`; no token revocation; no parser sandbox; no image scan;
model revision not pinned; Redis password visible via `docker inspect`; per-IP limits
see Vercel egress IPs when called through the BFF; no refresh tokens (sessions end
with the 30-minute token); CSP allows inline scripts; no WAF or DDoS protection beyond
rate limits on a single VM.
