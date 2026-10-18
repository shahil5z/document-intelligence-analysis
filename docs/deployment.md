# Deployment

This page covers the development/reference compose file (`docker-compose.yml`) and
image maintenance. The production setup (gunicorn, separate beat, Caddy, ops scripts,
CI/CD) is in [production-deployment.md](production-deployment.md); Oracle and Vercel
specifics in [oracle-cloud-deployment.md](oracle-cloud-deployment.md) and
[vercel-deployment.md](vercel-deployment.md).

## Compose (reference deployment)

```bash
python scripts/generate_env.py            # or --merge for an existing .env
docker compose build
docker compose up -d --wait               # postgres, redis, api, worker healthy; migrate exited 0
uv run python scripts/smoke_test.py
```

Services: `postgres` (pgvector:pg16), `redis` (password required), `migrate` (runs
`alembic upgrade head` once), `api`, `worker` (Celery worker with embedded beat).
Postgres, Redis and the worker exporter are not published to the host.

Hardening: `security_opt: no-new-privileges`, `cap_drop: [ALL]`, `init: true` for
migrate/api/worker; non-root uid 10001; healthchecks (`/health/live`, `celery inspect
ping`, `redis-cli ping` via `REDISCLI_AUTH`, `pg_isready`); graceful shutdown; worker
metrics on internal port 9100 with a tmpfs `PROMETHEUS_MULTIPROC_DIR`; Redis password
in a 0600 config file instead of the command line.

Verified on 2026-10-18 (Linux, Docker Compose): `build --no-cache` 56 s, `up -d --wait`
on fresh volumes ~40 s, all services healthy, smoke test 41/41 checks passed, Redis
stop/start recovers (API readiness and worker reconnect), see
[FINAL_PROJECT_REPORT.md](../FINAL_PROJECT_REPORT.md#8-docker-verification).

## Image digests

All base images are pinned by multi-arch index digest; the tag stays in the reference
for readability:

| Image | Tag | Where |
| --- | --- | --- |
| `python` | `3.12-slim@sha256:a6e34c59...` | Dockerfile (builder + runtime) |
| `ghcr.io/astral-sh/uv` | `0.13.1@sha256:4a1f3666...` | Dockerfile |
| `pgvector/pgvector` | `pg16@sha256:7b822b0a...` | compose, CI |
| `redis` | `7-alpine@sha256:858f009f...` | compose, CI |
| `caddy` | `2-alpine@sha256:d8542f48...` (2.11.7) | `docker-compose.prod.yml` |

To bump: resolve the new index digest, replace it everywhere, rebuild and rerun tests
and the smoke test.

```bash
docker buildx imagetools inspect pgvector/pgvector:pg16      # the top-level "Digest:" line
rg -n 'pgvector/pgvector:pg16@sha256' Dockerfile docker-compose.yml .github/workflows/ci.yml
```

Use the index (multi-arch) digest, not a platform manifest digest, so the same
reference works on amd64 and arm64 (Docker Desktop on Apple silicon / Windows ARM).

## pgvector version

Readiness requires pgvector >= 0.5.0 (HNSW). 0.8.0+ is recommended: filtered semantic
search uses `hnsw.iterative_scan`. On 0.5-0.7 search falls back to a plain HNSW scan
(warning logged; may return fewer than `top_k` results with many tenants). The pinned
`pgvector/pgvector:pg16` image ships 0.8.7. Verified: test suite on 0.6.2 and 0.8.7.

## Offline model cache

The worker and API download `BAAI/bge-small-en-v1.5` (~130 MB) into the `model_cache`
volume (`HF_HOME=/data/models`) on first use. Without internet access (or to stop
network access in production) seed the volume and set `HF_HUB_OFFLINE=1`:

```bash
docker compose up --no-start
docker run --rm --user 0 -v <project>_model_cache:/data/models -v ~/.cache/huggingface:/src:ro \
  --entrypoint sh document-intelligence-platform:local -c 'cp -a /src/. /data/models/ && chown -R 10001:10001 /data/models'
docker compose up -d --wait
```

If the model cannot be loaded, processing fails after bounded retries with
"Processing failed after several attempts" (observed live: 4 attempts, each stopped by
the 240 s soft time limit, then `failed`). Reprocess after fixing the cache.

## Stale-job reconciler

The worker runs Celery beat embedded (`-B`) and schedules `jobs.reconcile_stale` every
`STALE_JOB_CHECK_INTERVAL_SECONDS` (300). It fails jobs still `processing`/`retrying`
after `STALE_JOB_TIMEOUT_SECONDS` (900, must exceed `CELERY_TASK_TIME_LIMIT`). It is
idempotent and uses `SKIP LOCKED`, so several worker replicas each running beat is safe
(just redundant). Manual run: `docker compose exec api python -m app.cli
reconcile-stale-jobs`.

## Production checklist

- `APP_ENV=production`: startup refuses DEBUG, `LOG_LEVEL=DEBUG`, non-https CORS
  origins, http `LLM_BASE_URL`, `RATE_LIMIT_BACKEND=memory`, missing or placeholder
  secrets.
- Terminate TLS in a reverse proxy; set `FORWARDED_ALLOW_IPS` to the proxy address so
  client IPs (per-IP rate limits) are correct.
- Keep `/metrics` and port 9100 internal. API docs are off in production unless
  `API_DOCS_ENABLED=true`.
- Back up the Postgres volume and the storage volume together.
- Seed the model cache and set `HF_HUB_OFFLINE=1`.
- Size `TORCH_NUM_THREADS` x processes to the CPU count.

## CI

`.github/workflows/ci.yml` (push to `main`, `dip2`, `final`; pull requests): `lint`
(actionlint, ruff, ruff format --check, mypy), `test` (pgvector service, password Redis,
pytest `--cov-fail-under=90`, Alembic downgrade/upgrade/check), `audit` (`uv export` +
`pip-audit`), `docker` (build, non-root check, import check, `docker compose config`).
The jobs' commands were run locally (see the report); **the workflow itself has never
run on GitHub** (no remote).

## Not done

Image vulnerability scanning, read-only root filesystem, secrets manager, release
versioning (CD over SSH exists: `deploy.yml`, never run on GitHub), horizontal scaling of storage (local volume only), model revision pinning.
