# Retrieval (DIP2)

`POST /search` and the retrieval half of `POST /ask`. Code:
`app/db/repositories/chunks.py` (SQL), `app/services/retrieval.py` (fusion, reranking),
`app/services/search_service.py` (use case), `app/api/routes/search.py`.

## Schema

Migration `0002` (`alembic/versions/20261018_0002_document_chunks.py`):

| Column | Type | Notes |
| --- | --- | --- |
| `id` | uuid PK | |
| `document_id` | uuid FK -> documents ON DELETE CASCADE | deleting a document deletes its chunks |
| `owner_id` | uuid FK -> users ON DELETE CASCADE, indexed | denormalised so every query filters on the chunk row |
| `chunk_index` | int | unique with `document_id` (`uq_document_chunks_document_id`) |
| `content` | text | normalized chunk text |
| `content_tsv` | tsvector, `GENERATED ALWAYS AS (to_tsvector('english', content)) STORED` | cannot drift from `content`; GIN index `ix_document_chunks_content_tsv` |
| `page_start`, `page_end` | int, nullable | null for DOCX/TXT |
| `char_start`, `char_end` | int | offsets into the normalized extracted text |
| `token_count` | int | embedding-tokenizer tokens |
| `embedding` | `vector(384)` | HNSW index `ix_document_chunks_embedding_hnsw` (`vector_cosine_ops`, m=16, ef_construction=64) |
| `embedding_model` | varchar(255) | model that produced the vector |
| `created_at` | timestamptz | |

Also added: `document_processing_jobs.stage` (varchar(32), nullable). `alembic check`
reports no drift between models and migrations; downgrade to `0001` and upgrade again
were run on the test database.

**HNSW vs IVFFlat:** HNSW needs no training data (IVFFlat lists must be built from
existing rows, and an index created on an empty table is poorly balanced) and gives
good recall without tuning; the cost is slower inserts and more memory, acceptable for
per-document batch inserts. **Cosine:** the embeddings are normalised and the model is
trained for cosine similarity. At the current data sizes PostgreSQL may choose a
sequential scan instead of the index (exact results); index behaviour at scale is
**Not measured**.

## Access control in SQL

Every query (semantic and keyword):

```sql
FROM document_chunks c
JOIN documents d ON d.id = c.document_id AND d.owner_id = c.owner_id
WHERE c.owner_id = :caller AND d.owner_id = :caller
  AND d.status = 'completed'
  [AND c.document_id = :document_id]
```

- Other users' chunks can never be returned (filter is in the query, not applied to
  results afterwards).
- Documents that are queued, processing (including reprocessing) or failed are excluded.
- Deletion: DIP1 deletes document rows (there is **no soft delete** in this codebase,
  unlike what the stage brief assumed); chunks cascade, so deleted documents disappear
  from search immediately. Tested.
- `document_id` filter: the service first checks the document belongs to the caller and
  returns 404 otherwise (same rule as the rest of the API).

## Modes

| Mode | Query | Score returned |
| --- | --- | --- |
| `semantic` | `ORDER BY c.embedding <=> :query_vector, c.id LIMIT k` (pgvector cosine distance) | cosine similarity `1 - distance` |
| `keyword` | `c.content_tsv @@ q ORDER BY ts_rank(c.content_tsv, q, 1) DESC, c.id LIMIT k` | `ts_rank` (normalisation 1: divided by 1 + log(length)) |
| `hybrid` (default) | both lists with `CANDIDATE_K` rows each, fused with RRF | RRF score |

Keyword query construction: `plainto_tsquery('english', :q)` is rewritten from AND to OR
(`replace(...::text, ' & ', ' | ')::tsquery`). With AND semantics, a natural-language
question rarely matches any chunk because every stemmed word must be present; with OR,
`ts_rank` rewards chunks matching more terms. Exact identifiers such as
`payments.fallback_enabled` are kept as single lexemes by the parser (tested).

Semantic queries set `hnsw.iterative_scan = strict_order` and `hnsw.ef_search =
max(40, 2*k)` for the transaction: with the owner/status filters, a plain HNSW scan can
return fewer than `k` rows; iterative scans (pgvector >= 0.8; the pinned image runs
0.8.7) keep scanning. On pgvector 0.5-0.7 the setting is unknown: search detects that,
logs `search.pgvector_iterative_scan_unsupported` and runs a plain HNSW scan (verified:
all 129 database-backed tests pass on pgvector 0.6.2). Below 0.5.0 (no HNSW) readiness
fails. Effect of the fallback at scale: not measured.

Latency on the compose stack (21 one-chunk documents, sequential client): semantic p50
27 ms, keyword 6 ms, hybrid 28 ms ([performance.md](performance.md)).

## Hybrid: Reciprocal Rank Fusion

`score(chunk) = sum over lists of 1 / (60 + rank)`; chunks found by both lists are
merged by chunk id (the merged hit keeps the cosine similarity and gains the keyword
score). Why RRF:

- cosine similarity and `ts_rank` are on different, uncalibrated scales; RRF uses only
  ranks, so no weights or normalisation have to be tuned;
- k = 60 (Cormack, Clarke & Buettcher, SIGIR 2009) damps the very top ranks so a single
  list cannot dominate;
- it is deterministic and cheap.

Ties are broken by chunk id (string order) in fusion and by `c.id` in SQL, so results
are deterministic. In keyword-including hybrid queries the cosine similarity is computed
for keyword-only hits too, which `/ask` needs for its evidence threshold.

## Optional reranking

`RERANKING_ENABLED=false` by default. When enabled, the first-stage list (top
`max(top_k, RERANK_TOP_K)`) is rescored by a sentence-transformers `CrossEncoder`
(`RERANKER_MODEL`, default `cross-encoder/ms-marco-MiniLM-L-6-v2`) and re-sorted;
`reranked: true` in the response. If the reranker fails, the first-stage order is
returned and a warning is logged. Tested with a fake reranker only; the real
cross-encoder model was **NOT VERIFIED** (never loaded in tests or the compose run), and
its latency and quality effect are **Not measured**.

## API

`POST /search` (authenticated):

```json
{"query": "refund window", "mode": "hybrid", "top_k": 5, "document_id": null}
```

- `query`: 1..`MAX_QUERY_LENGTH` characters after trimming (422 otherwise).
- `top_k`: 1..`MAX_TOP_K` (default `TOP_K`); 422 outside.
- `mode`: `semantic` | `keyword` | `hybrid`.
- Unknown fields are rejected (422).

Response: `query`, `mode`, `reranked`, `results[]` with `chunk_id`, `document_id`,
`filename`, `chunk_index`, `text`, `page_start`, `page_end`, `char_start`, `char_end`,
`token_count`, `score`, `similarity`, `semantic_rank`, `keyword_rank`. Embedding vectors
are never returned.

Errors: 401 without a token, 404 for a foreign/missing `document_id`, 422 validation,
503 if the embedding model cannot be loaded or run (semantic/hybrid only; keyword search
does not need the model). The first semantic query in a fresh API process loads the
model (several seconds on CPU; one measurement in the compose run is in [history/dip2-handoff.md](history/dip2-handoff.md)).

## Evaluation

`scripts/evaluate_retrieval.py` runs the production path (TXT extraction,
normalization, chunking, embedding, `document_chunks`, `SearchService`) against a test
PostgreSQL database on the synthetic set in `tests/fixtures/documents` (6 documents) and
`tests/fixtures/eval_queries.json` (18 queries, one target passage each: a chunk is
relevant if it comes from the expected document and contains the expected phrase).

Results from the run on the dev box (CHUNK_SIZE 120, CHUNK_OVERLAP 20, k = 1/3/5):

`BAAI/bge-small-en-v1.5` (12 chunks):

| mode | R@1 | R@3 | R@5 | P@1 | P@3 | P@5 | MRR@5 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| semantic | 0.833 | 0.944 | 0.944 | 0.833 | 0.315 | 0.189 | 0.889 |
| keyword | 0.889 | 0.944 | 0.944 | 0.889 | 0.315 | 0.189 | 0.917 |
| hybrid | 0.833 | 0.944 | 0.944 | 0.833 | 0.315 | 0.189 | 0.889 |

Misses within top 5: semantic missed "Does limescale damage void the coverage?";
keyword and hybrid missed "How do I get my money back for a purchase?" (no shared
terms with the target passage; the semantic list found it but RRF ranked keyword-only
hits above it).

Hashing baseline (test embedder, 17 chunks, approximate token counter):

| mode | R@1 | R@3 | R@5 | P@1 | P@3 | P@5 | MRR@5 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| semantic | 0.611 | 0.889 | 0.944 | 0.611 | 0.296 | 0.189 | 0.745 |
| keyword | 0.889 | 0.944 | 0.944 | 0.889 | 0.315 | 0.189 | 0.917 |
| hybrid | 0.833 | 0.944 | 0.944 | 0.833 | 0.315 | 0.189 | 0.880 |

How to read this: 18 hand-written queries over 6 short synthetic documents is far too
small to rank the modes; differences of one query are 0.056. Precision@k is bounded by
the single target passage per query (P@5 cannot exceed about 0.2). The numbers show
that the pipeline works end to end and give a regression baseline, nothing more.
Retrieval quality on real documents: **Not measured**.

Reproduce:

```bash
uv run python scripts/evaluate_retrieval.py \
  --database-url postgresql+psycopg://dip:<pw>@localhost:5432/dip_eval_test \
  --provider sentence-transformers --json eval.json
```
