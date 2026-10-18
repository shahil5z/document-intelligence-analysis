"""Gunicorn settings for the production API (docker-compose.prod.yml).

Run with ``gunicorn -c python:app.gunicorn_conf app.main:app``. Every value can be
overridden through the environment so the same image fits different machine sizes:

* ``WEB_CONCURRENCY`` - worker processes (default 2). Each worker loads its own copy of
  the embedding model (~0.5 GB RSS with torch), so on a 2 OCPU / 12 GB VM two workers
  leave room for the Celery worker, PostgreSQL and Redis.
* ``GUNICORN_TIMEOUT`` - seconds before a silent worker is restarted (default 120: an
  /ask call may wait up to LLM_TIMEOUT_SECONDS for the LLM plus retrieval time).
* ``FORWARDED_ALLOW_IPS`` - proxies whose X-Forwarded-For is trusted (default ``*``: the
  API port is only reachable from the internal compose network, i.e. from Caddy).

With ``PROMETHEUS_MULTIPROC_DIR`` set, /metrics aggregates all workers; the directory
must be empty at start (a tmpfs in the compose file) and dead workers are marked here.
"""

import os

from prometheus_client import multiprocess


def _int_env(name: str, default: int) -> int:
    raw = os.environ.get(name, "").strip()
    return int(raw) if raw else default


bind = os.environ.get("GUNICORN_BIND", "0.0.0.0:8000")
workers = _int_env("WEB_CONCURRENCY", 2)
worker_class = "uvicorn_worker.UvicornWorker"
timeout = _int_env("GUNICORN_TIMEOUT", 120)
graceful_timeout = _int_env("GUNICORN_GRACEFUL_TIMEOUT", 25)
keepalive = _int_env("GUNICORN_KEEPALIVE", 5)
# Recycle workers now and then to cap slow memory growth (jitter avoids restarting all at once).
max_requests = _int_env("GUNICORN_MAX_REQUESTS", 2000)
max_requests_jitter = _int_env("GUNICORN_MAX_REQUESTS_JITTER", 200)
forwarded_allow_ips = os.environ.get("FORWARDED_ALLOW_IPS", "*")
# The application logs one structured line per request; gunicorn's access log would
# duplicate it (and could record query strings).
accesslog = None
errorlog = "-"
loglevel = os.environ.get("GUNICORN_LOG_LEVEL", "info")
worker_tmp_dir = "/dev/shm"  # noqa: S108 (heartbeat files; avoids disk-backed /tmp stalls)


def child_exit(_server: object, worker: object) -> None:
    """Drop a dead worker's live gauges from the multi-process metrics aggregate."""
    if os.environ.get("PROMETHEUS_MULTIPROC_DIR"):
        multiprocess.mark_process_dead(worker.pid)  # type: ignore[attr-defined,no-untyped-call]
