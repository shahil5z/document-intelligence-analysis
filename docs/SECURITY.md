# Security

Scope: the final system (DIP1 + DIP2 + DIP3 + final fixes). Every control below names
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
e-mail, never the raw value). Scopes: register and login per IP, login per e-mail,
upload/search/ask/reprocess per user. Exceeding a limit returns 429 with `Retry-After`.

**When Redis is unavailable** (`app/api/dependencies/rate_limit.py`):

| Scope | Decision | Response |
| --- | --- | --- |
| `register`, `login`, `login_per_email` | **fail closed** | 503 `Sign-in and registration are temporarily unavailable; retry later`, `Retry-After: 5`; the password is not checked |
| `upload`, `search`, `ask`, `reprocess` | **fail open** | request proceeds |

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
  procedure in [deployment.md](deployment.md#image-digests).
- App containers run as uid 10001 with `cap_drop: [ALL]`, `no-new-privileges`, `init`.
  Postgres, Redis and the worker exporter are not published to the host.
- `pip-audit` on the locked dependencies: no known vulnerabilities (torch skipped by the
  tool). No image vulnerability scan; root filesystems are not read-only.
- Embedding model: downloaded from Hugging Face on first use; the revision is not
  pinned. Seed the cache and set `HF_HUB_OFFLINE=1` to stop network access.

## Open gaps

Fixed windows allow bursts at window edges; upload rate limit after body receipt;
unauthenticated `/metrics`; no token revocation; no parser sandbox; no image scan;
model revision not pinned; Redis password visible via `docker inspect`.
