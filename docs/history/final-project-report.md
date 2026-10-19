# Final project report: Document Intelligence & Analysis

(Formerly "Document Intelligence Platform"; repository and package slugs unchanged.)

Single source of truth for what exists and what was verified. Branch `final`.
Everything ran on 2026-10-18 on the Linux build box (8 vCPU Intel Xeon, 15 GiB RAM,
Docker + Compose, Python 3.12, Node 22). Nothing ran on Windows, on GitHub Actions,
on Oracle Cloud, on Vercel or against a real OpenAI model.

Labels: **VERIFIED LOCALLY** (run here, result shown), **CONFIGURED BUT NOT DEPLOYED**
(file/config exists and was validated, no live target), **REQUIRES MANUAL ACTION**
(needs the owner's accounts), **NOT VERIFIED** (not run). Part A (sections 1-19 below
the production part) uses the earlier words PASS / PARTIAL with the same meaning as
VERIFIED LOCALLY / partially verified.

## U. UX round: Ask fix, demo mode, rename, theme, enterprise UI (latest)

Run on 2026-10-18/19 on the same Linux build box. Labels as below. Nothing in this round
ran against real OpenAI, on Windows, on Vercel, on Oracle Cloud or on GitHub Actions.

### U1. "Not enough evidence" on every question: root cause and fix

- **Evidence**: the reported log line `ask.insufficient_evidence ... llm_called: true`
  was emitted by the old code *only* when the reply started with `INSUFFICIENT_EVIDENCE`
  or was empty, so the model itself declined. Causes in code and data: an all-or-nothing
  prompt at temperature 0; every passage had to reach 0.48 individually (document-level
  questions scored 0.507-0.584); the Docker stub always answered, masking it. The real
  gpt-4o-mini replies were **not** inspected (no key here): inferred from the code path.
- **Fix** (`a864594`): structured output (strict JSON schema) with one fallback retry
  on 400/422; tolerant parser (`app/services/answer_parsing.py`: JSON, fenced, prose +
  JSON, alternative keys, `[S1]`/`[1-3]`/`[Source 1]`/`【1】`); answers are kept with
  at least one valid citation, invalid ones removed; `partial` + `missing_information`;
  `insufficient_reason` (`below_threshold` / `model_declined` / `parse_failed` /
  `no_valid_citations`) logged with counts only; gate on the best passage, supporting
  passages down to 0.40, `ASK_TOP_K=8`, `MAX_CONTEXT_TOKENS=4000`,
  `LLM_MAX_OUTPUT_TOKENS=900`.
- **Follow-up found by the one-command check** (`b58b306`): against the stub stack
  "What is this document about?" scored 0.415 vs 0.422 off-topic, so it was still
  refused. Document-level questions and questions scoped to one document now use
  `ASK_SCOPED_MIN_SIMILARITY=0.20` and the model decides; unscoped off-topic questions
  keep the 0.48 gate (logged as `gate`).
- **Prompt folder** `app/prompt/` (`system.md`, `answer_instructions.md`,
  `insufficient_evidence.md`, `response_schema.json`, loader, `PROMPT_VERSION =
  "2026-10-18.2"`, README), tested by `tests/unit/test_prompt_files.py`.
- **Replay fixture**: `tests/fixtures/llm_replies.json`, 18 hand-written replies
  (**not** captured OpenAI output) replayed through the real parser/validator in
  `tests/unit/test_llm_replay.py`.
- **One-command real check**: `python scripts/check_ask_real.py --base-url <api>`
  (throwaway user, sample or `--pdf`, document-level + specific + off-topic question,
  exit 1 on failure). Against the local stub stack: **RESULT PASS, 3/3** after the
  follow-up (FAIL 1/3 before it). Against real OpenAI: **NOT VERIFIED**: the user's to run.

### U2. Demo mode (`0f8805b` backend, frontend in `36f4788`..`5242193`)

`POST /auth/demo` creates an ephemeral user (`demo-<hex>@demo.invalid`, random
password, token lifetime min(TTL, 2 h)); server-side counters with atomic
`UPDATE ... WHERE used < limit RETURNING`: 3 questions (refunded when the LLM was not
called or failed), 1 upload, PDF only, 5 MB; 403 `demo_limit_reached` with
`details[0].limit`. Login refuses demo users. `POST /auth/demo/convert` turns it into a
normal account in place (documents kept). Beat task `users.cleanup_expired_demos`
(every 900 s, batches of 200) deletes expired demo users and their files. Migration
`0003` (columns + partial index). UI: "Try the demo" on landing/login/register, banner
"Demo: N of 3 questions left", upload hints, "Create a free account to continue" modal
on any `demo_limit_reached` (4th question, 2nd upload) and from the banner, inline
conversion. Design: [docs/demo-mode.md](../demo-mode.md).

### U3. Rate limits (public-demo defaults)

| Endpoint | Scopes and defaults | Key | Redis down |
| --- | --- | --- | --- |
| register / demo convert | `REGISTER` 5/minute + `REGISTER_DAILY` 20/day | IP | closed (503) |
| login | `LOGIN` 10/minute, `LOGIN_PER_EMAIL` 5/minute | IP / e-mail | closed |
| `POST /auth/demo` | `DEMO` 3/day, `DEMO_GLOBAL` 200/day | IP / global | closed |
| upload token | `UPLOAD_TOKEN` 30/minute | user | open |
| upload | `UPLOAD` 10/minute + `UPLOAD_DAILY` 100/day | user | open |
| search | `SEARCH` 60/minute | user | open |
| ask | `ASK` 10/minute + `ASK_DAILY` 200/day | user | open |
| reprocess | `REPROCESS` 10/minute | user | open |

`docker-compose.prod.yml` keeps its stricter overrides (docs/security.md). Behind the
Vercel BFF every request comes from Vercel's egress IPs: with
`CLIENT_IP_HEADER_SECRET` (API) = `DIP_CLIENT_IP_SECRET` (frontend, server-only) the
BFF forwards the browser IP in `X-DIP-Client-IP` and the API trusts it only with the
matching secret. The UI shows 429s as "You've reached the rate limit for this action.
Please try again in N seconds/minutes/hours." (from `Retry-After`).

### U4. Frontend: rename, brand, theme, UX

- **Rename**: "Document Intelligence & Analysis" in titles, metadata/OG/Twitter,
  manifest, header/sidebar wordmark, hero, auth, footer, modal, toasts, FastAPI
  `app_name`, compose `APP_NAME` default, README/docs headings, this report. Slugs,
  packages, Docker services, DB names and env keys unchanged. `grep -r "Document
  Intelligence Platform"` over code/docs: only historical mentions in this report.
- **Brand** (`4b11059`): `frontend/public/brand/` derived by
  `frontend/scripts/derive_brand_assets.py` (border-connected white removed, page inside
  the "D" protected, edge pixels un-premultiplied; corner alpha 0, no halo on dark;
  all derived files < 100 KB), favicon 16/32/48, apple-touch, 192/512 icons, 1200x630
  OG image. Mark via `next/image` with alt "Document Intelligence & Analysis". Tokens
  `#1E6BF0` -> `#7C3AED`.
- **Theme**: dark by default; `ThemeToggle` in the public header (landing, auth, legal
  pages) and the app sidebar/mobile header; choice in `localStorage["dia-theme"]`,
  applied by an inline head script before first paint; `suppressHydrationWarning` on
  `<html>`/`<body>`, `color-scheme` and `<meta name="darkreader-lock">`. Contrast
  (WCAG, computed from the tokens): body text 17.6:1 light / 16.0:1 dark, muted 7.7 /
  8.3, subtle 4.9-5.1 / 5.5-6.0, links 6.0 / 8.6, white on primary 4.75, on violet
  5.7; a dark `blue-700` that was 2.6:1 was remapped.
- **Shell**: sidebar (desktop), mobile header with hamburger + bottom navigation,
  reduced-motion aware transitions, toasts, skeletons, empty states.
- **Pages**: landing (hero, how it works, features, tech stack, CTA, footer with
  GitHub placeholder and privacy note); Impressum and Privacy templates (Austria/EU,
  GDPR) with highlighted placeholders and no invented addresses (the only real address
  is the Austrian Data Protection Authority's); no analytics, no tracking cookies;
  dashboard with counts, storage, quick actions and recent activity (audit log);
  upload dropzone with Uploading -> Processing -> Ready stepper, toast and "Ask
  questions about this document"; chat-style Ask (document picker, sessionStorage
  history, starter questions, typing indicator, safe Markdown subset rendered as React
  elements, `[n]` chips that highlight/expand the source card, copy, partial and
  insufficient-reason notices, disclaimer); search with highlighted terms.

### U5. Verification (this round)

| Check | Result | Label |
| --- | --- | --- |
| `ruff check .` / `ruff format --check .` | clean / 200 files formatted | VERIFIED LOCALLY |
| `mypy` (strict) | no issues in 166 source files | VERIFIED LOCALLY |
| `pytest --cov=app` (PostgreSQL + pgvector, Redis) | **491 passed, 11 skipped, 96% (4068 statements, 178 missed), 87.7 s**; skips = S3 live-server tests (no S3 server in this run) | VERIFIED LOCALLY |
| Alembic on a scratch DB: upgrade head, downgrade -1, upgrade, downgrade base, upgrade, check | `0003 (head)`, "No new upgrade operations detected." | VERIFIED LOCALLY |
| Frontend `npm run lint` / `typecheck` / `build` | clean / clean / build OK (24 routes) | VERIFIED LOCALLY |
| Playwright on the prod-like stack (`scripts/e2e_prod_local.sh`: prod compose, Caddy HTTPS with local CA, `next start`, structured stub LLM) | **21 passed** (demo flow 6, full flow 10, theme 5): demo -> upload PDF -> 3 cited answers -> 4th opens the modal -> conversion keeps the document; default dark + toggle persists across reload; name/title/logo-alt assertions; no console errors on public pages in both themes at 1366px and 375px; no horizontal overflow at 375px | VERIFIED LOCALLY |
| `scripts/check_ask_real.py` against the stub stack | RESULT PASS (3/3) | VERIFIED LOCALLY (stub only) |
| Secret scan (file:pattern only): tracked files / history (69 commits) / `frontend/.next` (762 files) | 12 / 10 / 28 hits: `replace-with-...` placeholders, CI/test values, fake `sk-test` keys, the pattern list in this report, and `.nft.json` paths containing `...task-async-storage...`; no secret names in `.next/static` | VERIFIED LOCALLY |
| Real OpenAI `/ask` | not run; the key was never read or used | **NOT VERIFIED** |
| Dark Reader extension in a real browser | not installed here; the mitigations are in place and no hydration errors were logged by Chromium | **NOT VERIFIED** |
| Windows (case-only renames avoided; no files renamed by case) | not run on Windows | NOT VERIFIED |
| Vercel / Oracle / GitHub Actions with these changes | no accounts | NOT VERIFIED |

Bugs found while verifying: the e2e script left `next start`'s child `next-server` on
port 3000 (next run served stale assets); it now starts it in its own process group,
kills the group on exit and refuses to start when 3000 is busy. "Create account"
showed on 375px (class conflict) and "Sign in" wrapped; the sticky Ask composer was
see-through on mobile.

Screenshots (Playwright, local stub LLM): `docs/screenshots/` (curated subset kept in the repository)
(32 files): `landing|login|impressum-{desktop,mobile}-{dark,light}`,
`ask-citations-{dark,light}`, `ask-mobile-{dark,light}`, `dashboard-desktop-{dark,light}`,
`dashboard-mobile-{dark,light}`, `demo-limit-modal-{dark,light}`,
`demo-upload-ready-dark`, plus the full-flow set.

### U6. New and changed environment keys

Backend (`.env.example`, compose): `ASK_TOP_K` (8), `ASK_CONTEXT_MIN_SIMILARITY` (0.40),
`ASK_SCOPED_MIN_SIMILARITY` (0.20), `LLM_STRUCTURED_OUTPUT` (true),
`RATE_LIMIT_REGISTER_DAILY` (20/day), `RATE_LIMIT_UPLOAD_DAILY` (100/day),
`RATE_LIMIT_UPLOAD_TOKEN` (30/minute), `RATE_LIMIT_ASK_DAILY` (200/day),
`RATE_LIMIT_DEMO` (3/day), `RATE_LIMIT_DEMO_GLOBAL` (200/day), `CLIENT_IP_HEADER_SECRET`
(unset; >= 24 chars), `DEMO_ENABLED` (true), `DEMO_MAX_QUESTIONS` (3),
`DEMO_MAX_UPLOADS` (1), `DEMO_MAX_UPLOAD_BYTES` (5242880), `DEMO_ALLOWED_EXTENSIONS`
(pdf), `DEMO_TTL_HOURS` (24), `DEMO_CLEANUP_INTERVAL_SECONDS` (900).
Changed defaults: `LLM_MAX_OUTPUT_TOKENS` 700 -> 900, `MAX_CONTEXT_TOKENS` 3000 -> 4000,
`RATE_LIMIT_UPLOAD` 30/minute -> 10/minute, `RATE_LIMIT_ASK` 20/minute -> 10/minute,
`APP_NAME` "Document Intelligence & Analysis".
Frontend (`frontend/.env.example`): `NEXT_PUBLIC_SITE_URL` (optional), `DIP_CLIENT_IP_SECRET`
(server-only, same value as `CLIENT_IP_HEADER_SECRET`).
Your local `.env`: `scripts/generate_env.py --merge` adds missing keys but does not
change existing values; edit `APP_NAME`, `LLM_MAX_OUTPUT_TOKENS`, `MAX_CONTEXT_TOKENS`,
`RATE_LIMIT_ASK`, `RATE_LIMIT_UPLOAD` by hand if you want the new defaults.

### U7. Repository state

`main` `2643292` and `dip2` `7eba5a1` unchanged; no remote added, nothing pushed.
Commits since `72c04dc`: `a864594` ask fix, `0f8805b` demo backend, `4b11059` brand
assets, `01fe282` frontend foundation, `36f4788` landing/legal/shell/demo UI,
`b90ed8a` chat Ask, `5242193` upload/dashboard/search, `92fc8c2` rename defaults,
`4965d58` e2e, `601d213` format, `f4829a1` mobile/contrast fixes, `4937068` docs,
`b58b306` scoped gate, and the final docs/screenshots commit. Bundle:
`/workspace/dip-ux.bundle` (`72c04dc..final`; `.env`, `.env.production`, `.e2e/` are
untracked and not in it).

---

## P. Production phase

### P1. What was added

| Area | Files | Status |
| --- | --- | --- |
| Upload-only tokens + upload policy | `app/core/security.py`, `app/api/routes/{auth,documents}.py`, `tests/api/test_upload_token.py` | VERIFIED LOCALLY |
| S3 / OCI Object Storage backend | `app/storage/s3.py`, `app/storage/factory.py`, `tests/unit/test_storage_s3.py`, `tests/api/...` | VERIFIED LOCALLY against moto + SeaweedFS; real OCI NOT VERIFIED |
| Production API process | `app/gunicorn_conf.py` (gunicorn + `uvicorn_worker`, 2 workers, multiprocess metrics) | VERIFIED LOCALLY |
| Production stack | `docker-compose.prod.yml`, `deploy/caddy/Caddyfile`, `.env.production.example` | VERIFIED LOCALLY (prod-like); CONFIGURED BUT NOT DEPLOYED |
| Local prod-like harness | `docker-compose.prod.e2e.yml`, `deploy/caddy/Caddyfile.e2e`, `scripts/e2e_prod_local.sh` | VERIFIED LOCALLY |
| Ops scripts | `scripts/{lib_prod,setup_server,deploy,backup_postgres,restore_postgres,health_check}.sh`, `scripts/production_smoke_test.py` | VERIFIED LOCALLY |
| Frontend | `frontend/` (Next.js 16 App Router, TypeScript, Tailwind 4, Playwright) | VERIFIED LOCALLY; Vercel CONFIGURED BUT NOT DEPLOYED |
| Auth decision | `docs/adr/ADR-006-frontend-auth-bff.md` | - |
| CI/CD | `.github/workflows/ci.yml` (+ shellcheck, frontend, optional e2e, prod compose/Caddy validation), `.github/workflows/deploy.yml` | actionlint clean; never run on GitHub: NOT VERIFIED |
| Docs | README (17 sections), `docs/{local-development,production-deployment,oracle-cloud-deployment,vercel-deployment,backup-and-recovery,security}.md`, `docs/{architecture,manual-testing,deployment}.md` updated, `docs/deployment-checklist.md`, this report | - |

The backend was not rewritten: all backend changes are additive (new token type,
new storage backend, gunicorn config, placeholder detection for `<...>` values). The
development `docker compose up` workflow is unchanged (`docker compose config` valid;
STORAGE_S3_* passthrough added with `local` default).

### P2. Verification results (this phase)

| Check | Result | Label |
| --- | --- | --- |
| `ruff check .` / `ruff format --check .` | clean / 184 files formatted | VERIFIED LOCALLY |
| `mypy app tests scripts` (strict) | no issues in 154 source files | VERIFIED LOCALLY |
| `pytest --cov=app` (PostgreSQL 16 + pgvector 0.8.7, Redis with password, SeaweedFS S3) | **414 passed, 0 skipped, 96% (3538 statements, 158 missed), 81.6 s** | VERIFIED LOCALLY |
| Alembic on a fresh DB: upgrade, check, downgrade base, upgrade, check | "No new upgrade operations detected.", `0002 (head)` | VERIFIED LOCALLY |
| Frontend `npm run lint` (`--max-warnings=0`), `npm run typecheck`, `npm run build` | clean, clean, build OK | VERIFIED LOCALLY |
| Playwright E2E (`frontend/e2e/full-flow.spec.ts`) against `next start` + prod compose behind Caddy (local CA, stub LLM over HTTPS) | **10 passed (13.2 s)** | VERIFIED LOCALLY |
| `production_smoke_test.py --register --with-llm` against `https://api.localhost:8443` | **13/13 checks PASS** (health, /metrics 404, register, login, policy, upload token + refusal elsewhere, upload 201, completed, keyword search, ask via stub, delete 204, 404) | VERIFIED LOCALLY |
| `deploy.sh --no-pull` on the local prod stack | DEPLOY_RC=0: backup, build, migrate, all services healthy, health check "all checks passed", smoke PASS | VERIFIED LOCALLY |
| `health_check.sh --url https://api.localhost:8443 --cacert ...` | all checks passed (6 services healthy, internal readiness, public /health/ready 200, /metrics 404, disk 47%) | VERIFIED LOCALLY |
| Backup -> restore `--into` round trip | users 10 / documents 6 / chunks 5 / alembic 0002 in both; reuse of name refused; live restore without 2nd flag refused | VERIFIED LOCALLY |
| Live restore drill (`--replace-live-database --i-understand-this-overwrites-data`) | after deleting all documents/chunks, counts back to 10 / 6 / 5; safety backup written; health check passed | VERIFIED LOCALLY |
| GPG-encrypted backup restored with `--into` | users 11 / documents 6 / chunks 5 | VERIFIED LOCALLY |
| Files archive (`--with-files`) | checksum OK; extracted file count 6 = live 6 | VERIFIED LOCALLY |
| `setup_server.sh --skip-swap` in `ubuntu:24.04` and `ubuntu:22.04` containers with Oracle-style iptables rules, run twice | RC 0 / 0 both; Docker 29.9.1 + Compose v5.6.0 installed; ACCEPT 80/443 inserted above REJECT, no duplicates on re-run; `deploy` user, docker group, 0700 `.ssh`, 0600 `authorized_keys`, `/opt/dip`, `/var/backups/dip` | VERIFIED LOCALLY (container: systemd, swap and the ufw branch NOT VERIFIED) |
| shellcheck (stable and v0.10.0, `-x`) on `scripts/*.sh` | clean | VERIFIED LOCALLY |
| actionlint on `.github/workflows` | clean | VERIFIED LOCALLY |
| `caddy validate` on both Caddyfiles; `docker compose config` (prod, prod+e2e, dev) | valid | VERIFIED LOCALLY |
| arm64: `buildx --platform linux/arm64` of the app image | BUILD_RC=0 (first builds 210 s / 221 s; final rebuild at HEAD mostly cached), image 1.52 GB | VERIFIED LOCALLY (QEMU) |
| arm64: import + embedding under emulation | aarch64, torch 2.14.1+cpu, sentence-transformers 6.1.0, dim 384, cosine 0.613, first embed 5.1 s / query 2.23 s (emulated, not representative of A1 speed) | VERIFIED LOCALLY (QEMU) |
| arm64: unit test suite (`tests/unit`) in the arm64 app image under emulation | **256 passed, 12 skipped, 0 failed (163 s)**; skips: 11 S3 live-server tests (no server in that run), 1 real-Redis test (no Redis) | VERIFIED LOCALLY (QEMU) |
| Base images are multi-arch indexes (amd64 + arm64/v8) | python 3.12-slim, uv 0.13.1, pgvector pg16, redis 7-alpine, caddy 2-alpine (2.11.7) via `imagetools inspect` | VERIFIED LOCALLY |
| Secret scan (see P4) | placeholders / test values / false positives only | VERIFIED LOCALLY |
| Real OpenAI `/ask` | not run (no key; never handled) | NOT VERIFIED |
| Oracle VM, DNS, Let's Encrypt certificate, Vercel deploy, GitHub Actions runs | no accounts | REQUIRES MANUAL ACTION / NOT VERIFIED |
| Windows PowerShell commands | written, not executed | NOT VERIFIED |

Bugs found and fixed while verifying: beat inherited the image's HTTP healthcheck
(unhealthy) and its schedule file was not a reliable heartbeat, so it got a process
liveness check (excludes its own PID; returns 1 in api/worker containers);
`health_check.sh` and the smoke test expected readiness `"ok"` instead of `"ready"`;
the smoke test expected 202 for uploads (API returns 201); gunicorn's control socket
needed a writable dir (disabled); compose project name lost under `sudo` (explicit
`-p`); SSL_CERT_FILE permissions in the harness; two Playwright selector issues.

### P3. Architecture decisions

- **Auth (ADR-006)**: BFF. JWT only in an HttpOnly, SameSite=Lax (Secure on HTTPS)
  `dip_session` cookie set by Next.js route handlers; CSRF via `X-DIP-CSRF` header +
  Origin check; allow-listed proxy; direct browser upload with a 300 s upload-only
  token because of Vercel's ~4.5 MB body limit and third-party-cookie blocking.
- **Oracle**: one A1 Flex VM (2 OCPU / 12 GB), compose + Caddy auto-HTTPS on 80/443,
  PostgreSQL/Redis on an internal network, local volume or OCI Object Storage.
  Oracle Always Free resources are available for the life of the account within the
  applicable Always Free limits (quotes and limits in `docs/oracle-cloud-deployment.md`).
- **Vercel**: Root Directory `frontend`, only `NEXT_PUBLIC_API_URL`; the OpenAI key
  stays on the VM.

### P4. Secret scan (file:pattern only)

Patterns: `sk-` keys, `OPENAI_API_KEY=` with a value, private-key blocks, AWS `AKIA`,
GitHub `gh?_`, Slack `xox?-`, JWT-shaped strings, `PASSWORD=`/`SECRET_KEY=`/
`SECRET_ACCESS_KEY=` assignments, plus the literal values of the locally generated E2E
secrets and the local S3 test secret.

| Scope | Hits (file: pattern) | Assessment |
| --- | --- | --- |
| `git ls-files` (11) | `.env.example`: OPENAI_API_KEY=, PASSWORD/SECRET_KEY=; `.env.production.example`: same two; `.github/workflows/ci.yml`: SECRET_KEY=; `docs/oracle-cloud-deployment.md`: PASSWORD=; `frontend/e2e/full-flow.spec.ts`: PASSWORD=; `tests/conftest.py`: PASSWORD=; `tests/unit/test_config.py`: PASSWORD=; `tests/unit/test_llm_provider.py`, `tests/unit/test_observability.py`: sk- | `replace-with-...` / `<...>` placeholders, an empty key (regex crossed the line end), `ci-only-...` values, a doc example, test-only passwords, fake `sk-test...` keys |
| Full history, 54 commits, added lines (9) | same as tracked except the two `.env.production.example` hits (line-by-line scan; those two were cross-line false positives) | same |
| `frontend/.next` build output, 563 files (23) | `*.nft.json`: sk- | false positive: the file path `...after-task-async-storage...`; no secret names (`OPENAI`, `JWT_SECRET`, `POSTGRES_PASSWORD`, `REDIS_PASSWORD`) in `.next/static` |

No literal E2E secret or S3 test secret appears in tracked files, history or `.next`.
`.env`, `.env.production`, `.e2e/` were never committed and are not in the bundle.

### P5. Repository state

| Ref | Commit | Note |
| --- | --- | --- |
| `main` | `2643292` | unchanged |
| `dip2` | `7eba5a1` | unchanged |
| `final` | see `git log` (production phase: `13f891a` ... HEAD) | 11 commits in this phase |

No remote was added (the existing `origin` is the local bundle the repository was
cloned from) and nothing was pushed. Bundle: `/workspace/dip-prod.bundle` (`final`).

---

# Part A: backend final phase (before the production phase)

## 1. Summary

A multi-tenant document Q&A backend: FastAPI API, PostgreSQL 16 + pgvector, Redis,
Celery worker. Users upload PDF/DOCX/TXT; the worker extracts, normalizes, chunks and
embeds the text locally (`BAAI/bge-small-en-v1.5`, 384-d); `/search` offers semantic,
keyword and hybrid (RRF) retrieval; `/ask` answers from retrieved passages only, with
validated citations, and skips the LLM entirely when evidence is weak. Every query is
owner-scoped inside SQL.

Final phase: 11 commits on top of the DIP3 snapshot fixing seven reliability/security
gaps, one large performance bug (PyTorch thread oversubscription), Docker/CI
verification and a documentation rewrite. Final state: 364 tests passed, 0 skipped,
96% coverage; Docker build and fresh-volume compose run healthy; smoke test 41/41.

## 2. Repository and branches

| Ref | Commit | Content |
| --- | --- | --- |
| `main` | `2643292` | DIP1, 19 commits (unchanged) |
| `dip2` | `7eba5a1` | DIP1 + DIP2, 14 more commits (unchanged) |
| `final` | `6b054d3` + 12 commits | DIP3 wip snapshot (kept as-is) + final phase |

No remote was added and nothing was pushed. The bundle `/workspace/dip-final.bundle`
contains `final` only; `.env` was never committed.

## 3. What each stage contained

- **DIP1** (`main`): uv/Python 3.12 scaffold; FastAPI app factory and error envelope;
  domain state machine; SQLAlchemy models + hand-written migration `0001`; JWT auth
  (register, JSON + OAuth2 login, roles, admin endpoints, audit log); validated
  uploads, local storage with traversal guard; Celery job pipeline hook; JSON logging
  and request ids; readiness probe; Dockerfile + compose; `generate_env.py`; tests
  against real PostgreSQL.
- **DIP2** (`dip2`): PDF/DOCX/TXT extraction, normalization, token-aware chunking;
  sentence-transformers embeddings, optional cross-encoder, HTTP LLM client; migration
  `0002` (`document_chunks`, HNSW, generated `tsvector`); semantic/keyword/hybrid
  search; grounded `/ask` with evidence threshold and citation validation; reprocess;
  retrieval evaluation (18 queries); smoke test extended.
- **DIP3** (work that was uncommitted, then snapshotted as `6b054d3` "wip(dip3)" on
  `final`, 51 files): rate limiting (Redis/memory), body-size middleware, security
  headers, docs off in production, production config checks, Prometheus metrics (API +
  worker exporter), worker reliability (soft limit message, bounded claims, DB outage
  handling, reprocess row lock), compose hardening, CI workflow, docs, DIP3 handoff.

## 4. Architecture (final)

Pure-ASGI middleware chain RequestContext -> SecurityHeaders -> BodySizeLimit -> CORS;
routes -> services -> owner-scoped repositories -> SQLAlchemy 2 (sync, psycopg 3).
Worker: Celery (acks_late, bounded claims, 240 s soft / 300 s hard limits) with
embedded beat for the stale-job reconciler; metrics exporter on 9100. Redis: broker +
fixed-window rate limits. Details: [docs/architecture.md](../architecture.md).

## 5. Handoff claims vs code (discrepancies)

| Claim | Code / reality |
| --- | --- |
| DIP2: empty LLM reply -> 503 | treated as insufficient evidence (200) |
| DIP2: scanned-PDF message text | code: "No extractable text was found. Scanned documents and images are not supported (OCR is not implemented)." |
| DIP2: hard-time-limit kill leaves the job `processing` | DIP3 bounded claims; final adds terminal failure + reconciler |
| DIP3: work uncommitted on `dip2` | committed as `6b054d3` on `final` |
| CI triggers on `dip3` | branch never existed; `final` was missing |
| Compose honours `.env` upload allow-lists | `ALLOWED_EXTENSIONS` / `ALLOWED_CONTENT_TYPES` (and `LLM_MAX_OUTPUT_TOKENS` / `LLM_TEMPERATURE`) were not passed to containers |
| Secrets kept out of the image | `.dockerignore` did not exclude a root file `env` or `*.bak` |
| Redis password handling | password was on the `redis-server` command line (visible in `ps`) |
| Worker exporter NOT VERIFIED | now verified live |
| README test numbers | still quoted DIP3 Windows 330 passed / 3 skipped |
| Rate limiting | failed open everywhere, including login |
| Stuck jobs | no reaper existed |
| DOCX "paragraphs + tables" | correct, but headers/footers/footnotes/comments/text boxes and `.doc` were not stated as unsupported |
| DIP1 OpenAI embedding/chat adapters | still exported from `app/ai` and tested, but not used by the pipeline or `/ask` (legacy) |

## 6. Fixes in the final phase

| # | Fix | Test |
| --- | --- | --- |
| a | Rate limiter on Redis failure: fail **closed** (503 + `Retry-After: 5`, no credential check) for register/login/login-per-email; fail **open** elsewhere; `dip_rate_limiter_errors_total{scope,decision}` + warning log | parametrized unit tests (3 credential endpoints, fail-open log/metric), real-Redis counter test, live Redis-stop check |
| b | Terminal `failed` on the final transient attempt; stale-job reconciler (beat every 300 s + CLI; `SKIP LOCKED`; outcome `stale_failed`); timeout must exceed the hard limit | 5 integration tests, unit tests for final attempt + beat schedule; live: 4 attempts -> `failed` |
| c | Base images pinned by multi-arch index digest (Dockerfile, compose, CI), tags kept and documented | `imagetools inspect` on 2026-10-18; clean build |
| d | pgvector policy: readiness fails if missing or < 0.5.0; warning below 0.8 | parametrized unit test + readiness test; suite on 0.6.2 and 0.8.7 |
| e | Reprocess concurrency (row lock) | thread test: [202, 409], one job, one dispatch; fails [202, 202] without the lock |
| f | Early 413 on `Content-Length` before reading the body; streaming limit | raw ASGI test (receive never called); smoke: headers-only request -> 413, file part -> 413 |
| g | DOCX/OCR limits stated accurately | docs |
| - | Redis password moved to a 0600 config file; restart loop fixed (`rm -f` first, `fs.protected_regular`) | live: `ps` shows no password; stop/start and restart recover |
| - | Compose passes allow-lists and LLM output settings; `.dockerignore` excludes `env`, `*.bak` | compose run |
| - | `TORCH_NUM_THREADS` (default 2) | unit test; benchmark before/after |
| - | `generate_env.py --merge` (byte-preserving, CRLF, `.bak`, atomic 0600, names only) | 16 unit tests; dry run vs a 24-key `.env` |
| - | Smoke test: early 413, 401, foreign `/ask` / reprocess 404, second reprocess 409, metrics labels, `--check-rate-limit`, `--real-llm`; stub LLM; benchmark script | live run |

## 7. Verification results

| Check | Result |
| --- | --- |
| `ruff check .` | PASS, clean |
| `ruff format --check .` | PASS, 170 files formatted |
| `mypy app tests scripts` (strict) / `mypy` (CI config) | PASS, 147 / 150 source files, no issues |
| `pytest --cov=app` (PostgreSQL 16.15 + pgvector 0.8.7, Redis 7.4.11 with password) | **PASS, 364 passed, 0 skipped, 96% (3370 statements, 148 missed), 57.7 s** |
| Same suite before the final phase | 333 passed, 0 skipped, 95% |
| DB-backed tests (`tests/api` + `tests/integration`) on pgvector 0.6.2 | PASS, 129 passed (fallback path) |
| Alembic on a fresh DB: upgrade head, check, downgrade base, upgrade head, check | PASS, "No new upgrade operations detected.", `0002 (head)` |
| actionlint 1.7.7 on `.github/workflows` | PASS, exit 0 |
| `pip-audit` on `uv export` | PASS, "No known vulnerabilities found" (torch skipped: not on PyPI) |
| Each new commit compiles (`compileall`) | PASS, 11/11 |

## 8. Docker verification

Generated `.env` (fake OpenAI key, `API_PORT=8010`, `HF_HUB_OFFLINE=1`), compose with
`docker-compose.stub-llm.yml`, project `dipfinal`, fresh volumes; the model cache volume
was seeded from the host cache because containers on this box cannot resolve
huggingface.co.

| Check | Result |
| --- | --- |
| `docker compose build --no-cache` | PASS, 56 s, image 1.57 GB |
| `up -d --wait` on fresh volumes | PASS, 39 s; postgres, redis, api, worker, stub-llm healthy; migrate exited 0 (0001, 0002) |
| `/health/ready` | PASS: database, pgvector (0.8.7), redis ok |
| `scripts/smoke_test.py --ask-expect answer --check-rate-limit` | **PASS, 41/41 checks, 13 s** |
| API runs as uid 10001; `alembic current` in container | PASS, `0002 (head)` |
| Redis without auth | PASS, `NOAUTH Authentication required.`; `ps` shows `redis-server *:6379` as user redis, no password |
| Redis stopped (live) | PASS: login and register 503 + `Retry-After: 5`; search and list 200; readiness 503 `redis: error`; metric `decision=fail_closed` (login, register) / `fail_open` (search) |
| Redis restart / stop+start | PASS after the fix (found a crash loop first: `Permission denied` on the old config file) |
| Worker reconnects after Redis restart | PASS (healthy again) |
| Worker exporter `:9100` | PASS: aggregated `dip_processing_jobs_total`, stage histograms |
| Beat task `jobs.reconcile_stale` | PASS, ran and succeeded; CLI `reconcile-stale-jobs` -> "Marked 0 stale job(s) as failed" |
| Model unavailable (first run, no internet, no cache) | PASS as failure path: 4 attempts, each stopped by the soft limit, then job and document `failed` "Processing failed after several attempts" |
| Logs after the smoke test | PASS: 0 occurrences of JWT secret, Postgres password, Redis password, fake OpenAI key, document text, answer text, bearer tokens, e-mails, "password" |

## 9. Security audit

- **Isolation**: all document/job/chunk/audit queries filter by owner in SQL; chunk
  queries also require `documents.status='completed'`. Cross-user matrix (GET, status,
  DELETE, reprocess, list, search x3 modes, search/ask with a foreign `document_id`)
  returns 404 / empty - PASS in tests and live.
- **Prompt injection / answer integrity**: escaped `<untrusted_sources>` block, data-not-
  instructions system prompt; no retrieval or best similarity < 0.48 -> insufficient
  evidence with `model: null` and no LLM call; unknown `[S#]` stripped (stub's forged
  `[S99]` removed live); LLM failures -> controlled 503; empty reply -> insufficient
  evidence - PASS.
- **HTTP**: nosniff, `X-Frame-Options: DENY`, `Referrer-Policy: no-referrer`, CORP
  same-origin, HSTS in production; explicit CORS origins; JWT with required claims,
  pinned algorithm and issuer, role re-read from the DB; Argon2id - PASS (tests).
- **Logs/metrics**: no secrets or document text (live count above); metric labels are
  route templates and fixed enums - PASS.
- **Secret audit (tracked files at `final` and full history of all refs; file:pattern
  only)**:

| File | Pattern | Assessment |
| --- | --- | --- |
| `.env.example` | `API_KEY=`, `PASSWORD=` (x2), `SECRET_KEY=` | `replace-with-...` placeholders (rejected at startup) |
| `.github/workflows/ci.yml` | `PASSWORD=`, `SECRET_KEY=` | runtime-generated (`openssl rand`, masked) / `ci-only-...` test values |
| `docs/manual-testing.md` | `API_KEY=` | literal placeholder `sk-...` |
| `tests/unit/test_generate_env.py` | `API_KEY=` (x3) | template expressions in test code |
| `tests/unit/test_llm_provider.py`, `tests/unit/test_observability.py` | `sk-` | fake `sk-test...` keys |
| history | same files (commits `7ddde9e`, `62e4af0`, `ffbde0a`, `6b054d3`, `2ec3156`) | same placeholders/fakes |

  No `sk-proj-`, AWS, GitHub, Slack, private-key or JWT-shaped strings anywhere in
  history; `.env`, `env` and `.env.bak` were never committed.

## 10. OpenAI / LLM configuration

`/ask` uses `OPENAI_API_KEY` with `LLM_PROVIDER=openai`, `LLM_MODEL` (default
`gpt-4o-mini`), `LLM_BASE_URL` (default `https://api.openai.com/v1`),
`LLM_TIMEOUT_SECONDS` (30), `LLM_MAX_OUTPUT_TOKENS` (700), `LLM_TEMPERATURE` (0). The
client is created lazily on the first `/ask` that has evidence and cached per
configuration; errors map to `LLMError` -> 503; missing/placeholder key -> 503 "not
configured". Status: code path **PASS** with the stub over real HTTP in Docker; **real
OpenAI NOT VERIFIED** (no real key here; nothing contacted OpenAI from the stack). One
manual Python check inside the container mistakenly instantiated the legacy DIP1 SDK
embedding adapter with the fake key; the request failed at DNS resolution
("Temporary failure in name resolution"), so nothing reached OpenAI. Procedure for
the user: [docs/manual-testing.md](../manual-testing.md#real-openai-test-optional-costs-money),
`scripts/smoke_test.py --real-llm`.

## 11. CI

`.github/workflows/ci.yml`: lint (actionlint, ruff, format, mypy), test (pgvector
service + password Redis, pytest with `--cov-fail-under=90`, Alembic cycle), audit
(pip-audit), docker (build, uid check, import check, `compose config`). Locally run:
actionlint (PASS), every lint/test/audit command (PASS, section 7), docker job steps
(uid 10001, `import app.main`, `compose config --quiet` - PASS). **The workflow has
never run on GitHub** (no remote): NOT VERIFIED.

## 12. Benchmark

Method: `scripts/benchmark.py`, single sequential client on the same host as the
compose stack; ingestion = upload 201 -> status `completed`, polled every 0.1 s, one-page
PDFs (1 chunk), one warm-up; search = client latency of `POST /search` (`top_k` 5),
10 queries cycled, one warm-up per mode; rate limits raised for the run only.

| Measurement | n | p50 | p95 | max |
| --- | --- | --- | --- | --- |
| Ingestion | 20 | 131 ms | 145 ms | 145 ms |
| Semantic search | 50 | 27 ms | 101 ms | 122 ms |
| Keyword search | 50 | 6 ms | 12 ms | 12 ms |
| Hybrid search | 50 | 28 ms | 62 ms | 128 ms |

Before `TORCH_NUM_THREADS` (same stack, n=10/30): ingestion p50 1885 ms, semantic p50
1504 ms, hybrid p50 1475 ms, keyword 6 ms. Corpus 21 documents / 21 chunks, so index
scaling is not represented. Throughput and concurrency: NOT MEASURED.

## 13. Environment: keys missing from the user's `.env`

The user's `.env` has the 24 DIP1 keys. `generate_env.py --merge --dry-run` against a
`.env` with exactly those keys lists **43 missing keys, all optional** (defaults apply;
none is mandatory - the three mandatory secrets are already present):

| Group | Keys |
| --- | --- |
| Embeddings / chunking | `EMBEDDING_PROVIDER`, `EMBEDDING_MODEL`, `EMBEDDING_DIMENSION`, `EMBEDDING_BATCH_SIZE`, `TORCH_NUM_THREADS`, `CHUNK_SIZE`, `CHUNK_OVERLAP`, `MAX_CHUNKS_PER_DOCUMENT`, `HF_HUB_OFFLINE` |
| Retrieval | `TOP_K`, `MAX_TOP_K`, `CANDIDATE_K`, `MAX_QUERY_LENGTH`, `MIN_EVIDENCE_SIMILARITY`, `RERANKING_ENABLED`, `RERANKER_MODEL`, `RERANK_TOP_K` |
| LLM | `LLM_PROVIDER`, `LLM_MODEL`, `LLM_BASE_URL`, `LLM_TIMEOUT_SECONDS`, `LLM_MAX_OUTPUT_TOKENS`, `LLM_TEMPERATURE`, `MAX_CONTEXT_TOKENS` |
| HTTP hardening | `API_DOCS_ENABLED`, `MAX_REQUEST_BODY_BYTES`, `UPLOAD_BODY_OVERHEAD_BYTES`, `SECURITY_HEADERS_ENABLED` |
| Rate limiting | `RATE_LIMIT_ENABLED`, `RATE_LIMIT_BACKEND`, `RATE_LIMIT_REGISTER`, `RATE_LIMIT_LOGIN`, `RATE_LIMIT_LOGIN_PER_EMAIL`, `RATE_LIMIT_UPLOAD`, `RATE_LIMIT_SEARCH`, `RATE_LIMIT_ASK`, `RATE_LIMIT_REPROCESS` |
| Operations | `METRICS_ENABLED`, `WORKER_METRICS_PORT`, `CELERY_TASK_SOFT_TIME_LIMIT`, `CELERY_TASK_TIME_LIMIT`, `STALE_JOB_TIMEOUT_SECONDS`, `STALE_JOB_CHECK_INTERVAL_SECONDS` |

Recommended on the PC: `py -3.12 scripts\generate_env.py --merge --dry-run`, then
`--merge` (writes `.env.bak`, changes no existing value, prints names only).
`OPENAI_API_KEY` must be a real key for `/ask`; `LLM_MODEL` is worth setting explicitly.

## 14. Known limitations

No OCR; DOCX body paragraphs + tables only, no `.doc`, no page numbers; retrieval
quality measured on 18 synthetic queries only (threshold 0.48 from the same set); no
entailment check of citations; fixed-window rate limits; upload rate limit after body
receipt; unauthenticated `/metrics`; no refresh tokens/revocation/lockout; local storage
only; model revision not pinned; Redis password visible via `docker inspect`; LLM client
sends `max_tokens`/`temperature` (some reasoning models reject them); legacy DIP1 OpenAI
SDK adapters still in `app/ai`; no tracing; no image scan; single-machine sequential
benchmark only.

## 15. Files changed in the final phase (vs `6b054d3`)

48 files, +2513 / -590. New: `app/workers/reconcile.py`, `tests/integration/test_stale_jobs.py`,
`scripts/benchmark.py`, `scripts/stub_llm_server.py`, `docker-compose.stub-llm.yml`,
`docs/manual-testing.md`, `docs/history/final-project-report.md`. Modified: `.dockerignore`,
`.env.example`, `.github/workflows/ci.yml`, `Dockerfile`, `docker-compose.yml`,
`README.md`, the three handoffs, `app/ai/{embeddings,factory,reranker}.py`,
`app/api/dependencies/rate_limit.py`, `app/api/routes/health.py`, `app/cli.py`,
`app/core/{config,metrics,rate_limit}.py`, `app/db/repositories/chunks.py`,
`app/services/health_service.py`, `app/workers/{celery_app,processing,tasks}.py`,
`scripts/{generate_env,smoke_test}.py`, 8 test modules, 11 docs.

## 16. Commits on `final` after `6b054d3`

1. `342933f` fix(rate-limit): fail closed for credential endpoints when Redis is down
2. `0182655` fix(worker): terminal failure on retry exhaustion and stale-job reconciler
3. `e8e4284` feat(health): enforce pgvector >= 0.5.0 in readiness
4. `2e55dd0` test(reprocess): prove the row lock serialises concurrent reprocess requests
5. `069e9e3` perf(embeddings): cap PyTorch threads per process (TORCH_NUM_THREADS=2)
6. `acb1d7e` feat(env): generate_env.py --merge adds missing keys to an existing .env
7. `41d108c` build(docker): pin images by digest, keep the Redis password off argv
8. `1a658ff` ci: run on final, pin service images, lint workflows with actionlint
9. `a828dba` test(smoke): cover early 413, rate limits, isolation and a --real-llm mode; add benchmark
10. `2ec3156` docs: rewrite README ...; security, testing, observability, performance, deployment, manual testing
11. `a71e21d` docs: update architecture, processing, retrieval, RAG and portfolio; mark stage handoffs as history
12. the commit adding this report

## 17. NOT VERIFIED

Real OpenAI `/ask`; the Windows routes (Docker Desktop and no-Docker) and the 26-step
PowerShell checklist; GitHub Actions run; real cross-encoder reranker; model download
from Hugging Face inside containers (box DNS; cache was seeded); arm64 on real
hardware (emulation only, see P2); throughput/concurrency/large corpora; retrieval
quality on real documents; every live deployment item (Oracle, DNS/TLS, Vercel, OCI
Object Storage).

## 18. VERIFIED CV EVIDENCE

- Multi-tenant document Q&A backend (FastAPI, PostgreSQL/pgvector, Celery, Redis) with
  owner-scoped hybrid retrieval and citation validation: **364 automated tests, 96%
  coverage**, against real PostgreSQL + pgvector (0.8.7, and 0.6.2 for the fallback).
- Credential endpoints fail closed when the rate-limit store is down; verified live by
  stopping Redis (login/register 503, other endpoints available).
- Background jobs always reach a terminal state: bounded retries, terminal failure,
  stale-job reconciler with `SKIP LOCKED`; observed live (4 attempts -> `failed`).
- Diagnosed PyTorch thread oversubscription: semantic search p50 **1504 ms -> 27 ms**,
  ingestion p50 **1885 ms -> 131 ms** (same machine, sequential).
- Concurrency test proves exactly one of two simultaneous reprocess requests succeeds.
- Hardened Docker deployment: digest-pinned images, non-root, `cap_drop: ALL`, Redis
  password off the command line; clean build 56 s, fresh start 39 s, smoke 41/41.
- Prometheus metrics with bounded labels for API and worker; logs verified free of
  secrets and document text.

## 19. FINAL PROJECT STATUS

| Area | Status | Value |
| --- | --- | --- |
| Lint / format / types | PASS | ruff clean; 170 files formatted; mypy strict 0 issues |
| Test suite | PASS | 364 passed, 0 skipped, 96% |
| pgvector < 0.8 fallback | PASS | 129 DB tests on 0.6.2 |
| Migrations | PASS | fresh upgrade, check, downgrade, upgrade |
| Docker build + compose | PASS | 56 s build, 39 s up, all healthy |
| Smoke test (stub LLM) | PASS | 41/41 |
| Rate limiting incl. Redis outage | PASS | live 401x5 -> 429; outage 503 / 200 |
| Upload limits (early 413, streaming) | PASS | tests + live |
| Reprocess concurrency | PASS | [202, 409] |
| Stale jobs / retry exhaustion | PASS | tests + live failure path |
| Worker metrics exporter | PASS | live |
| Security headers / CORS / JWT / Argon2id | PASS | tests |
| Log hygiene | PASS | 0 secret/content occurrences |
| Secret audit (files + history) | PASS | placeholders and fakes only |
| Dependency audit | PASS | no known vulnerabilities (torch skipped) |
| CI workflow | PARTIAL | actionlint + commands locally; never run on GitHub |
| Benchmark | PARTIAL | sequential single-machine numbers only |
| Real OpenAI `/ask` | NOT VERIFIED | needs the user's key |
| Windows setup / manual checklist | NOT VERIFIED | written, not executed |
| Real reranker | NOT VERIFIED | fake only |
| OCR | NOT IMPLEMENTED | explicit failure message |
| Tracing | NOT IMPLEMENTED | - |
| Production stack (local prod-like) | VERIFIED LOCALLY | E2E 10/10, smoke 13/13, deploy.sh RC 0 |
| Backup / restore | VERIFIED LOCALLY | round trip + live drill |
| arm64 | VERIFIED LOCALLY (QEMU) | build, import, embedding, unit tests |
| Live deployment | CONFIGURED BUT NOT DEPLOYED | docs/deployment-checklist.md |
