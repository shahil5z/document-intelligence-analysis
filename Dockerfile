# syntax=docker/dockerfile:1

# ---- build stage: resolve and install locked dependencies into a virtualenv ----
FROM python:3.12-slim AS builder

COPY --from=ghcr.io/astral-sh/uv:0.13.1 /uv /usr/local/bin/uv

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    UV_PROJECT_ENVIRONMENT=/opt/venv

WORKDIR /build
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

# ---- runtime stage: slim image, no build tooling, non-root user ----
FROM python:3.12-slim AS runtime

LABEL org.opencontainers.image.title="document-intelligence-platform" \
      org.opencontainers.image.description="FastAPI + Celery document intelligence backend"

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/opt/venv/bin:$PATH" \
    STORAGE_PATH=/data/storage \
    HF_HOME=/data/models

# /data/models holds the Hugging Face cache (embedding model, downloaded on first use).
RUN groupadd --system --gid 10001 app \
    && useradd --system --uid 10001 --gid app --home-dir /app --shell /usr/sbin/nologin app \
    && mkdir -p /data/storage /data/models \
    && chown -R app:app /data

COPY --from=builder /opt/venv /opt/venv

WORKDIR /app
COPY --chown=app:app alembic.ini ./
COPY --chown=app:app alembic ./alembic
COPY --chown=app:app app ./app

USER app

EXPOSE 8000

HEALTHCHECK --interval=15s --timeout=3s --start-period=10s --retries=3 \
    CMD ["python", "-c", "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/health/live', timeout=2).status == 200 else 1)"]

# --proxy-headers trusts X-Forwarded-For only from FORWARDED_ALLOW_IPS (uvicorn default
# 127.0.0.1). Set it to your reverse proxy's address so per-IP rate limits see real clients.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--no-access-log", "--timeout-graceful-shutdown", "20"]
