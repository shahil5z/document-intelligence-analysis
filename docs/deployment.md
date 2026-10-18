# Deployment

## Compose (reference deployment)

```bash
uv run python scripts/generate_env.py      # writes .env with random secrets
docker compose build
docker compose up -d
docker compose ps                         # api healthy, worker running
uv run python scripts/smoke_test.py       # end-to-end check
```

Services: `postgres` (pgvector:pg16), `redis` (password required), `migrate` (runs
`alembic upgrade head` once), `api`, `worker`. Postgres and Redis are not published.

Hardening applied in DIP3 (`docker-compose.yml`, `Dockerfile`):
`security_opt: no-new-privileges`, `cap_drop: [ALL]`, `init: true` for migrate/api/worker;
non-root uid 10001; healthcheck on `/health/live`; graceful shutdown
(`--timeout-graceful-shutdown 20`, `stop_grace_period` 30 s / 60 s); worker metrics on
internal port 9100 with a tmpfs `PROMETHEUS_MULTIPROC_DIR`. **NOT VERIFIED - Docker
unavailable**: only static review and YAML parsing were done.

## Production checklist

- `APP_ENV=production`: startup refuses DEBUG, `LOG_LEVEL=DEBUG`, non-https CORS
  origins, http `LLM_BASE_URL` with `LLM_PROVIDER=openai`, `RATE_LIMIT_BACKEND=memory`,
  missing or placeholder secrets.
- Terminate TLS in a reverse proxy; set `FORWARDED_ALLOW_IPS` to the proxy address so
  client IPs (used for per-IP rate limits) are correct.
- Keep `/metrics` and port 9100 on an internal network.
- API docs are off in production unless `API_DOCS_ENABLED=true`.
- Back up the Postgres volume and the storage volume together.
- Seed the model cache and set `HF_HUB_OFFLINE=1`.

## CI

`.github/workflows/ci.yml`: `lint` (ruff check, ruff format --check, mypy), `test`
(pgvector:pg16 service, password-protected Redis, pytest with `--cov-fail-under=90`,
Alembic downgrade/upgrade/check), `audit` (`uv export` + `pip-audit`), `docker` (build,
non-root check, import check, `docker compose config`). The workflow is YAML-validated
but has **never run** (the repository has no remote).

## Not done

Image digest pinning, image vulnerability scanning, read-only root filesystem, secrets
manager integration, Redis password outside the command line, CD/release pipeline,
stuck-job reaper.
