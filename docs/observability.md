# Observability

## Logs

JSON lines on stdout (`app/core/logging.py`): `timestamp`, `level`, `logger`, `event`,
`request_id`, plus `user_id` / `document_id` and event fields. Keys containing
password/token/secret/authorization are redacted. LLM usage is logged as
`usage_prompt` / `usage_completion` (DIP3 rename: the previous `prompt_tokens` keys were
redacted by the `token` rule). The access log includes the route template.

## Request ids

`X-Request-ID` is accepted if it matches `^[A-Za-z0-9-]{8,64}$`, otherwise generated;
returned on every response (also exposed through CORS), included in error bodies, and
passed to the Celery task so worker logs share it.

## Health

| Endpoint | Meaning |
| --- | --- |
| `GET /health/live` | process is up; no I/O (Docker healthcheck) |
| `GET /health/ready` | `SELECT 1` on PostgreSQL and `PING` on Redis; 503 with per-check status if either fails |

## Metrics

`GET /metrics` on the API (excluded from OpenAPI; disable with `METRICS_ENABLED=false`).
The worker serves the same format on `WORKER_METRICS_PORT` (compose: 9100, not
published) using `prometheus_client` multiprocess mode (`PROMETHEUS_MULTIPROC_DIR`, a
tmpfs in compose). Do not expose either endpoint publicly; scrape over the internal network.

| Metric | Type | Labels |
| --- | --- | --- |
| `dip_http_requests_total` | counter | `method`, `route` (template or `unmatched`), `status` |
| `dip_http_request_duration_seconds` | histogram | `method`, `route` |
| `dip_rate_limited_total` | counter | `scope` |
| `dip_rate_limiter_errors_total` | counter | - |
| `dip_document_uploads_total` | counter | `outcome` (`accepted`, `rejected_<status>`) |
| `dip_search_duration_seconds` | histogram | `mode` |
| `dip_ask_requests_total` | counter | `outcome` |
| `dip_llm_request_duration_seconds` | histogram | `outcome` |
| `dip_processing_jobs_total` | counter | `outcome` |
| `dip_processing_job_duration_seconds` | histogram | - |
| `dip_pipeline_stage_duration_seconds` | histogram | `stage` |

Labels never contain user ids, document ids, emails or raw paths (tested in
`tests/unit/test_http_hardening.py` and run against a live local server).

Example alerts (not deployed anywhere):
`rate(dip_http_requests_total{status=~"5.."}[5m]) > 0.05 * rate(dip_http_requests_total[5m])`,
`increase(dip_processing_jobs_total{outcome="failed"}[15m]) > 10`,
`increase(dip_rate_limiter_errors_total[5m]) > 0`.

## Verification status

- API metrics, request ids, health endpoints: tested, and run against a local uvicorn
  (PostgreSQL up, Redis down: `/health/ready` returned 503 with database `ok`).
- Worker exporter: **NOT VERIFIED** (Celery prefork does not run on Windows; no Docker).
- Tracing: **not implemented**.
