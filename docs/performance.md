# Performance

Nothing in this file is a benchmark. Latency, throughput, memory and index size at scale
are **Not measured**.

## Known costs

- Query embedding runs on the API process CPU (`bge-small-en-v1.5`, lazy-loaded on first
  search). The first search after start pays the model load.
- The worker embeds in batches outside the database transaction; only the index step
  takes a row lock.
- HNSW (cosine) index for semantic search, GIN index on the generated `tsvector`.
  Hybrid search runs both queries with `CANDIDATE_K` (40) candidates and fuses with RRF.
- pgvector >= 0.8 uses `hnsw.iterative_scan` so owner filtering does not starve results;
  older versions fall back to plain HNSW (detected at runtime, warning
  `search.pgvector_iterative_scan_unsupported`). With many tenants on 0.6/0.7, filtered
  semantic search can return fewer than `top_k` results.
- DIP3 reuses one HTTP client for the LLM (`app/ai/factory.py`, LRU cache) instead of
  creating one per `/ask` request.
- Rate limiting adds one Redis round trip (pipelined `INCR` + `EXPIRE`) per limited request.

## How to measure (not done)

1. Seed N documents with `scripts/smoke_test.py`-style uploads against a compose stack.
2. Use the `dip_search_duration_seconds`, `dip_http_request_duration_seconds` and
   `dip_pipeline_stage_duration_seconds` histograms while running a load tool
   (e.g. `k6` or `locust`) with rate limits raised.
3. Record hardware, document count, chunk count and percentiles here.
