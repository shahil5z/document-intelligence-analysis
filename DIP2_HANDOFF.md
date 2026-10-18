# DIP2 hand-off: document intelligence (extraction, chunking, embeddings, retrieval, `/ask`)

> **Historical stage record.** The numbers and NOT VERIFIED items below describe the
> state at the end of this stage and are kept unchanged as history. The current,
> verified state of the whole system (tests, Docker, CI, security, benchmark) is in
> [FINAL_PROJECT_REPORT.md](FINAL_PROJECT_REPORT.md); where this file disagrees with
> it, the final report and the code win.
>
> Corrections found in the final audit: an empty LLM reply is treated as
> *insufficient evidence* (200), not 503; the scanned-PDF message is "No extractable
> text was found. Scanned documents and images are not supported (OCR is not
> implemented)."; a hard-time-limit kill no longer leaves the job `processing`
> (bounded claims, DIP3; stale-job reconciler, final). The 247 passed / 2 skipped
> result is the DIP2 run; the final run is 364 passed, 0 skipped, 96%.

Branch `dip2`, based on DIP1 commit `2643292` (`main` unchanged). Verification was
run on 2026-10-18 on a Linux dev box (Docker, Python 3.12, uv); the Windows host
had no Docker/uv/PostgreSQL, see "Not verified".

## 1. What was implemented

| Area | Where | Notes |
| --- | --- | --- |
| Extraction | `app/processing/extraction.py` | PDF (pypdf, per page), DOCX (python-docx, paragraphs + tables, uncompressed-size guard), TXT (BOM / UTF-8 / cp1252, binary rejection). Encrypted, corrupt, scanned (no text) and empty files raise `ExtractionError` with a fixed safe message. |
| Normalization | `app/processing/normalization.py` | NFC, control chars, hyphenated line breaks, whitespace, blank-line collapse. |
| Chunking | `app/processing/chunking.py` | Recursive split on paragraph / line / sentence / word boundaries, sized in tokens of the embedding tokenizer (`CHUNK_SIZE` 400, `CHUNK_OVERLAP` 60), page ranges and character offsets per chunk, hard split for oversized tokens, `MAX_CHUNKS_PER_DOCUMENT` limit. |
| Embeddings | `app/ai/embeddings.py` | `BAAI/bge-small-en-v1.5` via sentence-transformers on CPU, 384 dims, normalized, query instruction prefix, batching, lazy thread-safe load, dimension verified against `EMBEDDING_DIMENSION`. |
| Storage of vectors | migration `0002`, `app/db/models/document_chunk.py` | `document_chunks` with `vector(384)` (HNSW, `vector_cosine_ops`, m=16, ef_construction=64), generated `tsvector` (`english`, GIN), unique `(document_id, chunk_index)`, `ON DELETE CASCADE` from documents and users; `document_processing_jobs.stage`. |
| Pipeline | `app/workers/steps.py`, `pipeline.py`, `processing.py`, `tasks.py` | integrity -> extract -> normalize -> chunk -> embed -> index. Stage is written to the job before each step. Embedding runs outside any DB transaction; `IndexStep` locks the document row, skips if it was deleted, and replaces all chunks (DELETE + INSERT) so redelivery and reprocessing are idempotent. |
| Retrieval | `app/db/repositories/chunks.py`, `app/services/retrieval.py`, `search_service.py` | semantic (cosine, `hnsw.ef_search`, `iterative_scan=strict_order`), keyword (`plainto_tsquery` rewritten to OR, `ts_rank(...,1)`), hybrid (RRF, k=60, tie-break by chunk id). Owner, `status='completed'` and optional `document_id` are SQL predicates. Optional cross-encoder rerank (`RERANKING_ENABLED`, default off) with fallback to first-stage order on failure. |
| `/search` | `app/api/routes/search.py` | `query`, `mode`, `top_k` (<= `MAX_TOP_K`), `document_id`. Embedding failure -> 503 with a hint to use `mode=keyword`. |
| `/ask` | `app/services/answer_service.py`, `rag_prompt.py`, `app/ai/llm.py` | hybrid retrieval; if no result has cosine >= `MIN_EVIDENCE_SIMILARITY` (0.48) a fixed "insufficient evidence" answer is returned without calling the LLM; context dedupe + token budget (`MAX_CONTEXT_TOKENS`); system rules + escaped `<untrusted_sources>`; citations `[S1]..` validated against sent sources; invalid ones removed and reported in `warnings`; LLM timeout/error/empty -> 503. LLM client: OpenAI-compatible `/chat/completions` over httpx2. |
| Reprocess | `POST /documents/{id}/reprocess` | completed/failed -> queued (202); queued/processing -> 409. |
| Status | `GET /documents/{id}/status` | adds `job.stage` and `chunk_count`. |
| Evaluation | `scripts/evaluate_retrieval.py`, `scripts/calibrate_evidence_threshold.py`, `tests/fixtures/eval_queries.json`, `tests/fixtures/documents/` | Recall@k, Precision@k, MRR@5 per mode; threshold calibration. |
| Docs | `docs/document-processing.md`, `retrieval.md`, `rag.md`, `SECURITY.md`, `architecture.md`, `portfolio.md`, README | |

Not implemented: OCR (scanned PDFs fail with "The document contains no extractable text
(scanned documents are not supported yet)"); soft delete (see discrepancies).

## 2. Discrepancies between the brief and the DIP1 code

- **No soft delete in DIP1.** `DELETE /documents/{id}` hard-deletes the row, jobs and
  file. Chunks are removed by `ON DELETE CASCADE`; retrieval additionally requires
  `documents.status = 'completed'`. No `deleted_at` filter exists because there is no
  such column.
- **`httpx2`, not `httpx`.** DIP1's lockfile already resolves the httpx successor
  package; the LLM client uses it (`import httpx2`).
- **LLM settings.** DIP1 had `OPENAI_CHAT_MODEL` / `OPENAI_EMBEDDING_MODEL` /
  `OPENAI_TIMEOUT_SECONDS` for SDK adapters in `app/ai/openai_provider.py`. They are
  kept unchanged but not used by `/ask`, which reads `LLM_PROVIDER`, `LLM_MODEL`,
  `LLM_BASE_URL`, `LLM_TIMEOUT_SECONDS`; the key is still `OPENAI_API_KEY`.
- **`build_default_pipeline` (DIP1) kept** as the integrity-only pipeline; the worker
  now uses `build_indexing_pipeline`.
- **`DIP3_HANDOFF.md` already existed**; it was updated, not created.

## 3. Database

Migration `20261018_0002_document_chunks.py` (revision `0002`, down revision `0001`):
creates `document_chunks` + indexes and adds `document_processing_jobs.stage`.
`alembic check` reports no drift; `downgrade 0001` then `upgrade head` ran cleanly on the
test database. In compose the migrate service ran `0001` then `0002` on a fresh volume.

## 4. Configuration

All new settings and defaults are in README "Environment variables" and `.env.example`.
Validators: `CHUNK_OVERLAP < CHUNK_SIZE`, `TOP_K <= MAX_TOP_K`, `CANDIDATE_K >= MAX_TOP_K`,
`LLM_BASE_URL` must be http(s). `OPENAI_API_KEY` is only read when `/ask` needs the LLM;
with no key or `LLM_PROVIDER=none`, `/ask` returns 503 and everything else works.

## Tests executed and real results

| Check | Result |
| --- | --- |
| DIP1 baseline on this branch point | 126 passed, 2 skipped |
| `uv run pytest --cov=app` (final) | **247 passed, 2 skipped**, 94 % line coverage of `app/` (2811 statements, 168 missed) |
| Skipped | the 2 Redis readiness tests (no `TEST_REDIS_URL` set in this run) |
| `ruff check .`, `ruff format --check .` | clean (146 files) |
| `mypy` (strict) | no issues in 132 source files |
| `alembic check` | no new upgrade operations |

Tests use a deterministic hashing embedder (`tests/fakes.py`), a mock LLM and a fake
reranker; no model is downloaded and no network call is made. A test runs a fresh
interpreter and asserts that importing `app.main` and the Celery app does not import
torch, sentence-transformers, transformers, pypdf or docx.

New test files: `tests/unit/test_extraction.py`, `test_normalization.py`,
`test_chunking.py`, `test_embeddings.py`, `test_retrieval_fusion.py`, `test_rag_prompt.py`,
`test_llm_provider.py`, additions to `test_config.py`;
`tests/integration/test_indexing_pipeline.py`; `tests/api/test_search.py`,
`tests/api/test_ask.py`.

### Docker compose run (fresh volumes)

Project `dip2verify`, image built from this branch (1.57 GB, torch `2.14.1+cpu`),
`--env-file` with generated secrets, plus an override adding a local **stub** LLM
(OpenAI-compatible, returns a fixed answer containing a valid `[S1]` and a fake `[S42]`).

- Migrations `0001` and `0002` applied; all services healthy.
- `scripts/smoke_test.py --ask-expect answer`: **SMOKE TEST PASSED** (33 checks, 11.9 s):
  register/login, PDF + TXT upload -> `completed` (`stage=index`, chunks=1 each), search
  in semantic / keyword / hybrid (top hit = the PDF), `/ask` -> 200 with 1 citation,
  off-topic `/ask` -> insufficient evidence, 415 for `.exe`, second user: 404 on
  get/status/delete, empty list, 0 results in all three modes, 404 for foreign
  `document_id`, reprocess -> 202 -> completed, delete -> 204 -> 404, search after
  delete -> 0 results, audit actions recorded.
- Logs: `ask.completed ... invalid_citations_removed: 1` (the fake `[S42]` was stripped);
  `ask.insufficient_evidence ... llm_called: false`.
- Model load in container: 4.8 s (api and worker each, first use). First semantic search
  4.9 s including that load; later searches 2-19 ms on 2 chunks (single observations,
  not a benchmark).
- Secret check: JWT secret, Postgres and Redis passwords and the stub API key occur
  0 times in api/worker logs; document text did not appear in logs.

**First attempt failed** and is kept here because it shows real behaviour: the worker
could not resolve `huggingface.co` from the compose network on this box (host network
quirk, like the iptables one noted in DIP3_HANDOFF). The load raised `OSError`, which the
pipeline treats as transient; the job retried with backoff through 4 attempts, stayed at
`stage=chunk`, and ended `failed` with "Processing failed after several attempts". The
smoke test timed out (300 s). Fix for the run: pre-seed the `model_cache` volume from a
host cache and set `HF_HUB_OFFLINE=1` (now a documented compose variable).

### Retrieval evaluation

`scripts/evaluate_retrieval.py` with the real model on 18 queries / 6 documents
(`CHUNK_SIZE=120`, `CHUNK_OVERLAP=20` so documents have several chunks). Full tables in
[docs/retrieval.md](docs/retrieval.md#evaluation); summary: hybrid Recall@5 0.944,
MRR@5 0.889; semantic MRR@5 0.889; keyword MRR@5 0.917. With the hashing embedder hybrid
clearly beats semantic (MRR 0.880 vs 0.745). The set is small and synthetic; differences
of one query are 0.056 recall.

Threshold calibration (`scripts/calibrate_evidence_threshold.py`): top-1 cosine for
on-topic queries min 0.507, off-topic max 0.451 -> `MIN_EVIDENCE_SIMILARITY=0.48`.

## Not verified

- **Real `/ask` against OpenAI: NOT VERIFIED.** The API key is only on the Windows host,
  which has no Docker; it was not copied to the dev box. The HTTP client is covered by
  unit tests with a mocked transport and by the compose run against the stub.
- **Real cross-encoder reranker: NOT VERIFIED** (only a fake reranker in tests; default off).
- **Tests on the Windows host: NOT VERIFIED** (no uv / Python 3.12 / PostgreSQL there).
- Latency, throughput, memory at scale, HNSW recall vs exact search: **Not measured**.
- Answer faithfulness, prompt-injection robustness with a real model: **Not measured**.

## Known limitations

- No OCR. No entailment check of citations (only that the cited source was sent).
- Keyword search uses the `english` configuration only.
- Embedding model + torch add ~1.3 GB to the image and ~5 s cold start per process;
  model files are downloaded on first use unless the cache volume is seeded.
- Changing the embedding model or dimension requires a migration and reprocessing all
  documents (`embedding_model` is stored per chunk, but nothing checks it yet).
- A worker killed by the Celery **hard** time limit does not update the job; it stays
  `processing` until redelivery (DIP1 behaviour, unchanged).
- `llm.completed` log fields `prompt_tokens` / `completion_tokens` are redacted by the DIP1
  log redactor (key contains "token"); the numbers are therefore not visible in logs.
- Large documents are embedded in one task; there is no per-chunk progress.

## What DIP3 must not break

- Owner + `status='completed'` predicates inside `ChunkRepository._base`.
- The order "embed outside the transaction, then lock + replace chunks" in `IndexStep`.
- Citation validation in `AnswerService` and the escaping in `rag_prompt.build_messages`.
- Lazy imports of torch / sentence-transformers / pypdf / docx (guarded by a test).
- `vector(384)` column and `EMBEDDING_DIMENSION` must change together.
