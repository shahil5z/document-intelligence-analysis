# Portfolio notes: Document Intelligence Platform (DIP1 + DIP2)

Interview-oriented summary. Each claim below was executed; anything not run is marked
**NOT VERIFIED** and anything not quantified is marked **Not measured**. Full evidence:
[DIP1_HANDOFF.md](../DIP1_HANDOFF.md), [DIP2_HANDOFF.md](../DIP2_HANDOFF.md).

## One-line summary

A FastAPI + PostgreSQL/pgvector + Celery backend that accepts user documents, extracts
and chunks their text, embeds it with a local model, and answers questions with
citations that are checked against the passages that were actually retrieved, all
scoped to the document owner inside SQL.

## Problems solved and how

| Problem | Approach | Evidence |
| --- | --- | --- |
| One user must never see another's documents | Owner filter inside every repository query; foreign ids return 404 | API tests + smoke test |
| Retrieval must not leak across tenants | `owner_id` + `status='completed'` predicates inside the semantic and keyword SQL (not post-filtering); foreign `document_id` -> 404 | API tests with two users; compose smoke test (see DIP2_HANDOFF) |
| Uploads must not trust the client | allow-lists, magic bytes, streamed size limit, sanitised names, server keys | DIP1 tests |
| Files can be hostile or useless | encrypted / corrupt / scanned / binary / zip-bomb DOCX all fail with a fixed safe message; no parser text reaches the API | extraction unit tests + pipeline integration tests |
| Jobs must be observable and re-runnable | DB job state machine + `stage` column; index step replaces chunks under a row lock; `/reprocess` | integration tests (reprocess, redelivery, deleted during processing) |
| Exact terms and paraphrases both matter | keyword (`tsvector`) + semantic (pgvector HNSW) fused with RRF | 18-query evaluation in docs/retrieval.md |
| LLM must not answer without evidence | cosine threshold calibrated on the eval set; below it, fixed answer and no LLM call | API tests assert the mock LLM is not called |
| Citations must be real | sources numbered `S1..Sn`; any cited id not sent is removed and reported in `warnings` | unit + API tests; compose run with a stub LLM that emits a fake `[S42]` |
| Retrieved text may contain instructions | system prompt rules + escaped `<untrusted_sources>` block | prompt unit tests (escaping, injection text stays inside the block). Robustness against a real model: **Not measured** |

## Numbers that exist

- Retrieval evaluation (18 synthetic queries, 6 documents, real `bge-small-en-v1.5`):
  hybrid Recall@5 0.944, MRR@5 0.889; keyword MRR@5 0.917. Small set, so differences
  between modes are within one or two queries. Table: docs/retrieval.md.
- Evidence threshold 0.48: on-topic minimum top-1 similarity 0.507, off-topic maximum
  0.451 on the same set.
- Latency, throughput, index size at scale: **Not measured**.
- Answer quality / faithfulness with a real LLM: **Not measured**.

## Engineering practices shown

- Layered design (routes -> services -> repositories), framework-free processing
  package, provider protocols with fakes for tests (hashing embedder, mock LLM).
- Tests against real PostgreSQL + pgvector through the real Alembic migrations; no
  model downloads or network calls in tests; a test asserts torch / sentence-transformers
  / pypdf are not imported at app startup.
- Migration `0002` hand-written, `alembic check` clean, downgrade/upgrade exercised.
- Small, logically separated commits on a feature branch.

## Talking points / trade-offs

- **Local embeddings instead of an embedding API**: no per-document cost or data
  egress; costs ~1.5 GB of image (CPU torch) and model load time on first use.
- **Vector dimension fixed in the schema (384)**: the provider verifies the model's
  dimension at load; changing models needs a migration + reprocess.
- **RRF instead of score blending**: cosine and `ts_rank` are not on comparable scales;
  RRF only uses ranks.
- **OR-semantics keyword query**: `plainto_tsquery` is AND-only; rewritten to OR so a
  question with one unknown word still matches; ranking handles the rest.
- **Embedding outside the DB transaction**: the slow step holds no locks; the index step
  locks the document row and replaces chunks atomically, so re-delivery is idempotent.
- **Citation validation is structural, not semantic**: it guarantees the cited passage
  was retrieved, not that it supports the sentence.

## Not done yet (be explicit in interviews)

OCR for scans; entailment checking of citations; real-reranker evaluation (the reranker
path is only tested with a fake); a real-LLM `/ask` run (see DIP2_HANDOFF for status);
CI/CD, rate limiting, metrics/tracing, image scanning (DIP3).
