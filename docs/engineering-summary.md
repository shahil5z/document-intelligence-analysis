# Engineering summary: Document Intelligence & Analysis

Technical summary. Each claim below was executed; anything not run is marked
**NOT VERIFIED** and anything not quantified is marked **Not measured**. Full evidence:
[verification report](history/final-project-report.md) (stage history in the [DIP1-3
handoffs](history/)).

## One-line summary

A FastAPI + PostgreSQL/pgvector + Celery backend that accepts user documents, extracts
and chunks their text, embeds it with a local model, and answers questions with
citations that are checked against the passages that were actually retrieved, all
scoped to the document owner inside SQL.

## Problems solved and how

| Problem | Approach | Evidence |
| --- | --- | --- |
| One user must never see another's documents | Owner filter inside every repository query; foreign ids return 404 | API tests + smoke test |
| Retrieval must not leak across tenants | `owner_id` + `status='completed'` predicates inside the semantic and keyword SQL (not post-filtering); foreign `document_id` -> 404 | API tests with two users; compose smoke test (see [DIP2 handoff](history/dip2-handoff.md)) |
| Uploads must not trust the client | allow-lists, magic bytes, streamed size limit, sanitised names, server keys | DIP1 tests |
| Files can be hostile or useless | encrypted / corrupt / scanned / binary / zip-bomb DOCX all fail with a fixed safe message; no parser text reaches the API | extraction unit tests + pipeline integration tests |
| Jobs must be observable and re-runnable | DB job state machine + `stage` column; index step replaces chunks under a row lock; `/reprocess` | integration tests (reprocess, redelivery, deleted during processing) |
| Exact terms and paraphrases both matter | keyword (`tsvector`) + semantic (pgvector HNSW) fused with RRF | 18-query evaluation in docs/retrieval.md |
| LLM must not answer without evidence | cosine threshold calibrated on the eval set; below it, fixed answer and no LLM call | API tests assert the mock LLM is not called |
| Citations must be real | sources numbered `S1..Sn`; any cited id not sent is removed and reported in `warnings` | unit + API tests; compose run with a stub LLM that emits a fake `[S42]` |
| Retrieved text may contain instructions | system prompt rules + escaped `<untrusted_sources>` block | prompt unit tests (escaping, injection text stays inside the block). Robustness against a real model: **Not measured** |
| Abuse of login / upload / LLM calls | fixed-window rate limits in Redis per IP, per email and per user; 429 + `Retry-After`; hashed keys; **fail-closed for credentials** and fail-open elsewhere when Redis is down | unit tests; live compose run (failed logins 401 x5 then 429; Redis stopped: login/register 503, search 200) |
| Oversized requests before parsing | ASGI body-size middleware (Content-Length and streamed) | raw ASGI test (body never read); live: headers-only oversized upload -> 413 |
| Operating it (DIP3) | Prometheus metrics with route-template labels, request ids, liveness/readiness | tests + live run (`/metrics` contained templates, no document ids) |
| Jobs that hang or kill workers | soft time limit -> clear failure; attempt cap on redelivery; final attempt -> terminal `failed`; stale-job reconciler with `SKIP LOCKED` | integration tests; live: model unavailable -> 4 attempts -> `failed` |
| Duplicate reprocess requests | document row lock | concurrency test: exactly one 202 + one 409 (fails without the lock) |
| Slow CPU inference | found 8-thread torch oversubscription; capped threads per process | semantic search p50 1504 ms -> 27 ms, ingestion p50 1885 ms -> 131 ms on the same stack |

## Numbers that exist

- Retrieval evaluation (18 synthetic queries, 6 documents, real `bge-small-en-v1.5`):
  hybrid Recall@5 0.944, MRR@5 0.889; keyword MRR@5 0.917. Small set, so differences
  between modes are within one or two queries. Table: docs/retrieval.md.
- Evidence threshold 0.48: on-topic minimum top-1 similarity 0.507, off-topic maximum
  0.451 on the same set.
  (DIP2 measurement, not repeated in the final phase.)
- Tests (final, Linux, PostgreSQL 16.15 + pgvector 0.8.7, Redis 7.4 with password):
  **364 passed, 0 skipped, 96% line coverage** of `app/`; the 129 database-backed tests
  also pass on pgvector 0.6.2.
- ruff and ruff format clean (170 files), mypy (strict) clean; actionlint clean;
  `pip-audit`: no known vulnerabilities (torch skipped by the tool).
- Docker: clean build 56 s, fresh-volume start ~40 s, smoke test 41/41 checks.
- Sequential latency on one 8-vCPU VM (21 one-chunk documents): ingestion p50 131 ms,
  semantic search p50 27 ms / p95 101 ms, keyword p50 6 ms, hybrid p50 28 ms.
- Throughput, concurrency, index behaviour at scale: **Not measured**.
- Answer quality / faithfulness with a real LLM: **Not measured**.

## Engineering practices shown

- Layered design (routes -> services -> repositories), framework-free processing
  package, provider protocols with fakes for tests (hashing embedder, mock LLM).
- Tests against real PostgreSQL + pgvector through the real Alembic migrations; no
  model downloads or network calls in tests; a test asserts torch / sentence-transformers
  / pypdf are not imported at app startup.
- Migration `0002` hand-written, `alembic check` clean, downgrade/upgrade exercised.
- Small, logically separated commits on the `final` branch.
- Unit tests run with no services; CI workflow with Postgres + Redis services, coverage
  gate, dependency audit and actionlint (linted and its commands run locally; **never run
  on GitHub**).

## Talking points / trade-offs

- **Local embeddings instead of an embedding API**: no per-document cost or data
  egress; costs ~1.5 GB of image (CPU torch) and model load time on first use.
- **Vector dimension fixed in the schema (384)**: the provider verifies the model's
  dimension at load; changing models needs a migration + reprocess.
- **RRF instead of score blending**: cosine and `ts_rank` are not on comparable scales;
  RRF only uses ranks.
- **OR-semantics keyword query**: `plainto_tsquery` is AND-only; rewritten to OR so a
  question with one unknown word still matches; ranking handles the rest.
- **Embedding outside the DB transaction**: the slow step holds no locks; the index step
  locks the document row and replaces chunks atomically, so re-delivery is idempotent.
- **Citation validation is structural, not semantic**: it guarantees the cited passage
  was retrieved, not that it supports the sentence.

## Not done yet (be explicit in interviews)

OCR for scans; entailment checking of citations; real-reranker evaluation (the reranker
path is only tested with a fake); a real-LLM `/ask` run (NOT VERIFIED; procedure in
manual-testing.md); tracing; image scanning; a CI run on GitHub; load testing.

## CV bullets supported by evidence

- Built a multi-tenant document Q&A backend (FastAPI, PostgreSQL/pgvector, Celery,
  Redis) with owner-scoped hybrid retrieval and citation validation; 364 automated tests,
  96% coverage, against real PostgreSQL/pgvector.
- Added production hardening: per-IP/per-user rate limiting, pre-parse request size
  limits, security headers, production config validation and cross-tenant security tests.
- Instrumented the API and worker with Prometheus metrics using bounded label sets and
  request-id correlated JSON logs.
- Made background processing fail safely under timeouts, worker kills and database
  outages (bounded retries, terminal failure, stale-job reconciler), covered by
  integration tests and a live Docker run.
- Cut CPU embedding latency ~50x (semantic search p50 1.5 s -> 27 ms) by diagnosing
  PyTorch thread oversubscription between API and worker processes.

Do not claim yet: "deployed", "CI/CD pipeline running", "load tested", "production
traffic", or latency beyond the single-machine sequential figures above.
