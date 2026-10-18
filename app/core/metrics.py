"""Prometheus metrics (prometheus_client).

Label values are always drawn from small, fixed sets: HTTP method, the *route template*
(``/documents/{document_id}``, never the concrete path), status code, search mode,
pipeline stage and fixed outcome names. User ids, document ids, e-mail addresses,
queries and file names are never used as labels.

Multi-process: the API runs one process per container by default, so the default
registry is enough. Celery's prefork pool runs tasks in child processes; set
``PROMETHEUS_MULTIPROC_DIR`` (an empty, writable directory) for the worker so that
:func:`build_registry` aggregates the children (see docs/observability.md).
"""

import os

from prometheus_client import (
    CONTENT_TYPE_LATEST,
    REGISTRY,
    CollectorRegistry,
    Counter,
    Histogram,
    generate_latest,
)

UNMATCHED_ROUTE = "unmatched"

_LATENCY_BUCKETS = (0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0)
_JOB_BUCKETS = (0.1, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0, 60.0, 120.0, 300.0)

HTTP_REQUESTS = Counter(
    "dip_http_requests_total",
    "HTTP requests by method, route template and status code.",
    ("method", "route", "status"),
)
HTTP_LATENCY = Histogram(
    "dip_http_request_duration_seconds",
    "HTTP request latency by method and route template.",
    ("method", "route"),
    buckets=_LATENCY_BUCKETS,
)
RATE_LIMITED = Counter(
    "dip_rate_limited_total", "Requests rejected with 429, by limit scope.", ("scope",)
)
RATE_LIMITER_ERRORS = Counter(
    "dip_rate_limiter_errors_total",
    "Rate-limiter backend failures by scope and decision (fail_open = allowed, "
    "fail_closed = rejected with 503).",
    ("scope", "decision"),
)
UPLOADS = Counter(
    "dip_document_uploads_total", "Upload attempts that reached the service.", ("outcome",)
)
SEARCH_LATENCY = Histogram(
    "dip_search_duration_seconds",
    "Retrieval latency by search mode.",
    ("mode",),
    buckets=_LATENCY_BUCKETS,
)
ASK_REQUESTS = Counter(
    "dip_ask_requests_total",
    "Question-answering outcomes (answered, insufficient_evidence, llm_unavailable, "
    "not_configured).",
    ("outcome",),
)
DEMO_EVENTS = Counter(
    "dip_demo_events_total",
    "Demo-mode events (created, converted, limit_questions, limit_uploads, expired_deleted).",
    ("event",),
)
LLM_LATENCY = Histogram(
    "dip_llm_request_duration_seconds",
    "LLM call latency by outcome (ok or error).",
    ("outcome",),
    buckets=_LATENCY_BUCKETS,
)
JOBS = Counter(
    "dip_processing_jobs_total",
    "Processing job attempts by outcome (completed, failed, skipped, retry).",
    ("outcome",),
)
JOB_DURATION = Histogram(
    "dip_processing_job_duration_seconds",
    "Wall time of one processing attempt (claim to finish).",
    buckets=_JOB_BUCKETS,
)
STAGE_DURATION = Histogram(
    "dip_pipeline_stage_duration_seconds",
    "Duration of each pipeline stage.",
    ("stage",),
    buckets=_JOB_BUCKETS,
)


def status_label(status_code: int) -> str:
    """Status codes are a small set already; keep them exact (e.g. 404 vs 429 matters)."""
    return str(status_code) if 100 <= status_code <= 599 else "invalid"


def build_registry() -> CollectorRegistry:
    """Default registry, or a multi-process aggregate when PROMETHEUS_MULTIPROC_DIR is set."""
    if os.environ.get("PROMETHEUS_MULTIPROC_DIR"):
        from prometheus_client import multiprocess  # noqa: PLC0415

        registry = CollectorRegistry()
        multiprocess.MultiProcessCollector(registry)  # type: ignore[no-untyped-call]
        return registry
    return REGISTRY


def render_latest() -> tuple[bytes, str]:
    return generate_latest(build_registry()), CONTENT_TYPE_LATEST
