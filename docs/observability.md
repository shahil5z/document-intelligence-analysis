# Observability

## Logs

JSON lines on stdout (`app/core/logging.py`): `timestamp`, `level`, `logger`, `event`,
`request_id`, plus `user_id` / `document_id` and event fields. Keys containing
password/token/secret/authorization are redacted. LLM usage is logged as
`usage_prompt` / `usage_completion`. The access log includes the route template.
Document text, queries' text, answers and secrets are never logged (queries are logged
as `query_length` only).

Verified on the final compose run: after a full smoke test the combined logs of all
services contained 0 occurrences of the JWT secret, the PostgreSQL password, the Redis
password, the (fake) OpenAI key, the uploaded document text, the generated answer,
`Bearer ey...` tokens, user e-mail addresses or the word `password`
([verification report](history/final-project-report.md#9-security-audit)).

Events worth alerting on:

| Event | Meaning |
| --- | --- |
| `rate_limit.backend_unavailable` (`scope`, `decision`, `error_type`) | Redis unreachable for the rate limiter; `fail_closed` for login/register, `fail_open` elsewhere |
| `job.retries_exhausted` / `job.failed_after_retries` | last attempt failed with a transient error; job marked failed |
| `job.terminal_state_not_persisted` | the database was still down on the last attempt; the reconciler will fail the job later |
| `job.stale_failed` | reconciler failed a job stuck in processing/retrying |
| `health.pgvector_without_iterative_scan` | pgvector < 0.8: search uses plain HNSW scans |
| `search.pgvector_iterative_scan_unsupported` | the same, logged by the search path |

## Request ids

`X-Request-ID` is accepted if it matches `^[A-Za-z0-9-]{8,64}$`, otherwise generated;
returned on every response (also exposed through CORS), included in error bodies, and
passed to the Celery task so worker logs share it.

## Health

| Endpoint | Meaning |
| --- | --- |
| `GET /health`, `GET /health/live` | process is up; no I/O (Docker healthcheck) |
| `GET /health/ready` | `SELECT 1` on PostgreSQL, pgvector installed and >= 0.5.0, `PING` on Redis; 503 with per-check status if any fails |

## Metrics

`GET /metrics` on the API (excluded from OpenAPI; disable with `METRICS_ENABLED=false`).
The worker serves the same format on `WORKER_METRICS_PORT` (compose: 9100, not
published) using `prometheus_client` multiprocess mode (`PROMETHEUS_MULTIPROC_DIR`, a
tmpfs in compose). Neither endpoint is authenticated: scrape over the internal network.

| Metric | Type | Labels (bounded values) |
| --- | --- | --- |
| `dip_http_requests_total` | counter | `method`, `route` (template or `unmatched`), `status` |
| `dip_http_request_duration_seconds` | histogram | `method`, `route` |
| `dip_rate_limited_total` | counter | `scope` (register, login, login_per_email, upload, search, ask, reprocess) |
| `dip_rate_limiter_errors_total` | counter | `scope`, `decision` (`fail_open`, `fail_closed`) |
| `dip_document_uploads_total` | counter | `outcome` (`accepted`, `rejected_<status>`) |
| `dip_search_duration_seconds` | histogram | `mode` |
| `dip_ask_requests_total` | counter | `outcome` (`answered`, `insufficient_evidence`, `llm_unavailable`, `not_configured`) |
| `dip_llm_request_duration_seconds` | histogram | `outcome` |
| `dip_processing_jobs_total` | counter | `outcome` (`completed`, `failed`, `skipped`, `retry`, `stale_failed`) |
| `dip_processing_job_duration_seconds` | histogram | - |
| `dip_pipeline_stage_duration_seconds` | histogram | `stage` |

Labels never contain user ids, document ids, e-mails or raw paths. Tested in
`tests/unit/test_http_hardening.py` and checked by `scripts/smoke_test.py` against the
live compose stack.

Example alerts (not deployed anywhere):
`rate(dip_http_requests_total{status=~"5.."}[5m]) > 0.05 * rate(dip_http_requests_total[5m])`,
`increase(dip_processing_jobs_total{outcome=~"failed|stale_failed"}[15m]) > 10`,
`increase(dip_rate_limiter_errors_total[5m]) > 0`.

## Verification status

| Item | Status |
| --- | --- |
| API metrics, request ids, health endpoints | PASS (tests + live compose run) |
| `/health/ready` with pgvector 0.6.2 and 0.8.x, and with Redis stopped (503, `redis: error`) | PASS (live) |
| Worker exporter on 9100 (aggregated multiprocess counters, stage histograms) | PASS (live compose run, queried from inside the network) |
| `dip_rate_limiter_errors_total{decision="fail_closed"/"fail_open"}` with Redis stopped | PASS (live) |
| Tracing (OpenTelemetry) | NOT IMPLEMENTED |
| Prometheus server / dashboards / alert rules | NOT IMPLEMENTED |
