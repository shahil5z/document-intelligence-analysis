"""Small, honest latency measurement against a running stack (not a load test).

Usage:  python scripts/benchmark.py [--base-url http://localhost:8000] [--documents 10]
                                    [--queries 30]

What it measures, sequentially with a single client (no concurrency):

* ingestion: wall time from ``POST /documents`` returning 201 until the status endpoint
  reports ``completed`` (polled every 0.1 s, so values are rounded up to ~0.1 s), for
  ``--documents`` freshly generated one-page PDFs (~1 chunk each) after one warm-up
  document that absorbs the embedding-model load;
* search: client-observed latency of ``POST /search`` per mode over ``--queries``
  queries after one warm-up query per mode.

Prints p50 / p95 / max in milliseconds plus the document and chunk counts. Rate limits
must allow the request volume (e.g. RATE_LIMIT_SEARCH=10000/minute,
RATE_LIMIT_UPLOAD=1000/minute for the run). Standard library only; reuses the smoke
test's HTTP client and PDF generator. The benchmark user's documents are deleted at the end.
"""

import argparse
import platform
import secrets
import statistics
import sys
import time
import uuid
from pathlib import Path

# Allow "python scripts/benchmark.py" from the repository root without installing anything.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.smoke_test import Client, build_pdf

QUERIES = (
    "How long do customers have to return items?",
    "refund payment method business days",
    "warranty claims for damaged goods",
    "shipping costs for international orders",
    "who approves expense reports",
)


def _percentile(values: list[float], pct: float) -> float:
    ordered = sorted(values)
    index = max(0, min(len(ordered) - 1, round(pct / 100 * len(ordered) + 0.5) - 1))
    return ordered[index]


def _summary(name: str, values_ms: list[float]) -> str:
    return (
        f"{name:<22} n={len(values_ms):<3} p50={statistics.median(values_ms):8.1f} ms  "
        f"p95={_percentile(values_ms, 95):8.1f} ms  max={max(values_ms):8.1f} ms"
    )


def _ingest(client: Client, index: int) -> tuple[str, float]:
    pdf = build_pdf(
        f"Policy document {index} {uuid.uuid4().hex[:8]}.",
        "Customers may return unused items within 30 days of delivery for a full refund.",
        "Refunds are issued to the original payment method within 7 business days.",
        "Warranty claims for damaged goods are handled by the support team.",
    )
    started = time.perf_counter()
    status, body = client.upload(f"bench-{index}.pdf", pdf, "application/pdf")
    if status != 201:
        raise SystemExit(f"upload failed: {status} {body}")
    document_id = body["id"]
    while True:
        _, _, state = client.request("GET", f"/documents/{document_id}/status")
        if state["status"] in {"completed", "failed"}:
            break
        if time.perf_counter() - started > 600:
            raise SystemExit("document did not finish within 600 s")
        time.sleep(0.1)
    if state["status"] != "completed":
        raise SystemExit(f"document failed: {state['job']}")
    return document_id, (time.perf_counter() - started) * 1000


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://localhost:8000")
    parser.add_argument("--documents", type=int, default=10)
    parser.add_argument("--queries", type=int, default=30)
    args = parser.parse_args()

    client = Client(args.base_url)
    email = f"bench-{uuid.uuid4().hex[:8]}@example.com"
    password = secrets.token_urlsafe(18)
    client.request("POST", "/auth/register", json_body={"email": email, "password": password})
    _, _, body = client.request(
        "POST", "/auth/login", json_body={"email": email, "password": password}
    )
    client.token = body["access_token"]

    print(f"client: Python {platform.python_version()} on {platform.platform()}")
    warmup_id, warmup_ms = _ingest(client, 0)
    print(f"warm-up ingestion (includes worker model load if cold): {warmup_ms:.0f} ms")
    documents = [warmup_id]
    ingest_ms: list[float] = []
    for index in range(1, args.documents + 1):
        document_id, elapsed = _ingest(client, index)
        documents.append(document_id)
        ingest_ms.append(elapsed)

    chunks = 0
    for document_id in documents:
        _, _, state = client.request("GET", f"/documents/{document_id}/status")
        chunks += int(state["chunk_count"])
    print(f"corpus for search: {len(documents)} documents, {chunks} chunks (benchmark user)")
    print(_summary("ingestion (PDF, 1 pg)", ingest_ms))

    for mode in ("semantic", "keyword", "hybrid"):
        client.request("POST", "/search", json_body={"query": "warm up", "mode": mode})
        latencies: list[float] = []
        for index in range(args.queries):
            query = QUERIES[index % len(QUERIES)]
            started = time.perf_counter()
            status, _, body = client.request(
                "POST", "/search", json_body={"query": query, "mode": mode, "top_k": 5}
            )
            latencies.append((time.perf_counter() - started) * 1000)
            if status != 200:
                raise SystemExit(f"search failed: {status} {body}")
        print(_summary(f"search {mode}", latencies))

    for document_id in documents:
        client.request("DELETE", f"/documents/{document_id}")


if __name__ == "__main__":
    main()
