# Performance

One small, sequential measurement on one machine. It is **not** a load test and says
nothing about throughput, concurrency or behaviour at scale (NOT MEASURED).

## Method (`scripts/benchmark.py`)

- Single client, no concurrency, against the compose stack on the same host.
- Ingestion: wall time from `POST /documents` returning 201 until
  `GET /documents/{id}/status` reports `completed`, polled every 0.1 s (values are
  rounded up to the polling interval). Each document is a freshly generated one-page
  PDF (1 chunk). One warm-up document first.
- Search: client-observed latency of `POST /search` per mode (`top_k` 5) over a fixed
  list of 10 queries cycled, after one warm-up query per mode. Corpus: the benchmark
  user's documents only.
- Rate limits raised for the run only (`RATE_LIMIT_SEARCH=10000/minute`,
  `RATE_LIMIT_UPLOAD=1000/minute`); everything else default.

```bash
RATE_LIMIT_SEARCH=10000/minute RATE_LIMIT_UPLOAD=1000/minute docker compose up -d --wait api
uv run python scripts/benchmark.py --base-url http://localhost:8000 --documents 20 --queries 50
```

## Result (2026-10-18)

Environment: Linux VM, 8 vCPU (Intel Xeon), 15 GiB RAM, Docker Compose, images built
from this commit, pgvector 0.8.7, `bge-small-en-v1.5` on CPU (torch 2.14.1+cpu), worker
`--concurrency=2`, `TORCH_NUM_THREADS=2`, stub LLM (not involved in these numbers).

| Measurement | n | p50 | p95 | max |
| --- | --- | --- | --- | --- |
| Ingestion, 1-page PDF, upload -> completed | 20 | 131 ms | 145 ms | 145 ms |
| Search, semantic | 50 | 27 ms | 101 ms | 122 ms |
| Search, keyword | 50 | 6 ms | 12 ms | 12 ms |
| Search, hybrid (RRF) | 50 | 28 ms | 62 ms | 128 ms |

Corpus for search: 21 documents, 21 chunks. With so few rows, index behaviour is not
represented; these numbers are mostly model inference + HTTP + one SQL round trip.

## Finding: PyTorch thread oversubscription

The first benchmark run, before `TORCH_NUM_THREADS` existed (torch default: one thread
per core = 8 per process), on the same machine and stack:

| Measurement | p50 | p95 |
| --- | --- | --- |
| Ingestion (n=10) | 1885 ms | 2253 ms |
| Search semantic (n=30) | 1504 ms | 1846 ms |
| Search keyword (n=30) | 6 ms | 11 ms |
| Search hybrid (n=30) | 1475 ms | 2021 ms |

Timing one query embedding inside the API container with `torch.set_num_threads(n)`:
n=1: 17-24 ms, n=2: 10-12 ms, n=4: 9-13 ms (one 184 ms outlier), n=8: 1181-1537 ms.
The default is therefore `TORCH_NUM_THREADS=2`; `0` restores torch's default.

## Known costs

- Query embedding runs on the API process CPU (`bge-small-en-v1.5`, lazy-loaded on first
  search: ~6 s in the container). The first search after start pays the model load.
- The worker embeds in batches outside the database transaction; only the index step
  takes a row lock.
- HNSW (cosine) index for semantic search, GIN index on the generated `tsvector`.
  Hybrid search runs both queries with `CANDIDATE_K` (40) candidates and fuses with RRF.
- pgvector >= 0.8 uses `hnsw.iterative_scan` so owner filtering does not starve results;
  older versions fall back to plain HNSW (warning
  `search.pgvector_iterative_scan_unsupported`); with many tenants on 0.6/0.7, filtered
  semantic search can return fewer than `top_k` results.
- One shared HTTP client per LLM configuration; one Redis round trip per rate-limited
  request.

## Not measured

Concurrent load, throughput, large documents (100+ pages), large corpora (index
recall/latency at 10^5+ chunks), memory under load, `/ask` latency with a real LLM.
