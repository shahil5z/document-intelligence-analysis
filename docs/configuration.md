# Configuration reference

All backend settings are read from the environment (`.env` locally).

## Production and frontend

Production keys (`API_DOMAIN`, `CADDY_TLS`, `CORS_ALLOWED_ORIGINS`, storage, capacity,
rate limits, backups) are documented in [.env.production.example](../.env.production.example)
and [production-deployment.md](production-deployment.md#environment). The
frontend reads `NEXT_PUBLIC_API_URL`, `NEXT_PUBLIC_SITE_URL` and the server-only
`DIP_CLIENT_IP_SECRET` ([frontend/.env.example](../frontend/.env.example)).
## Backend

Only three values are **mandatory**; everything else has a safe default. All names are
in [.env.example](../.env.example) with comments. Invalid configuration stops startup with
a message that names the variable, never the value.

| Mandatory | Why |
| --- | --- |
| `JWT_SECRET_KEY` | >= 32 characters; placeholders are rejected |
| `POSTGRES_PASSWORD` | unless `DATABASE_URL` is set (not required when `APP_ENV=test`) |
| `REDIS_PASSWORD` | unless `REDIS_URL` is set (not required when `APP_ENV=test`) |

| Needed for one feature | Default | Notes |
| --- | --- | --- |
| `OPENAI_API_KEY` | unset | only `/ask`. Without it `/ask` returns 503 once evidence is found; upload, processing and `/search` work |

| Optional | Default | Notes |
| --- | --- | --- |
| `APP_NAME` / `APP_ENV` / `DEBUG` / `LOG_LEVEL` / `API_PORT` | `Document Intelligence & Analysis` / `development` / `false` / `INFO` / `8000` | `APP_ENV=production` enables stricter checks |
| `JWT_ALGORITHM` / `JWT_ACCESS_TOKEN_EXPIRE_MINUTES` | `HS256` / `30` | HS256/384/512; 1-1440 minutes |
| `POSTGRES_HOST` / `_PORT` / `_DB` / `_USER`, `DATABASE_URL` | `localhost` / `5432` / `dip` / `dip` | compose sets host/port itself |
| `REDIS_HOST` / `_PORT` / `_DB`, `REDIS_URL`, `CELERY_BROKER_URL`, `CELERY_RESULT_BACKEND` | `localhost` / `6379` / `0` | URLs built from the parts unless set |
| `STORAGE_BACKEND` / `STORAGE_PATH` | `local` / `./storage_data` | only `local` exists |
| `MAX_UPLOAD_SIZE_BYTES` | `10485760` | 413 above this |
| `ALLOWED_EXTENSIONS` / `ALLOWED_CONTENT_TYPES` | pdf,docx,txt / matching MIME types | comma separated |
| `CORS_ALLOWED_ORIGINS` | `http://localhost:3000,http://localhost:5173` | `*` rejected |
| `EMBEDDING_PROVIDER` / `EMBEDDING_MODEL` / `EMBEDDING_DIMENSION` / `EMBEDDING_BATCH_SIZE` | `onnx` / `BAAI/bge-small-en-v1.5` / `384` / `32` | `onnx` = ONNX Runtime, the model's fp32 ONNX export, CLS pooling + L2 norm (no PyTorch); `remote` = delegate to the API's `POST /internal/embed` (worker on small machines: one model copy, in the API); `sentence-transformers` = PyTorch, needs `uv sync --extra torch`. Dimension must match the `vector(384)` column |
| `EMBEDDING_ONNX_FILE` | `onnx/model.onnx` | ONNX file inside the model repository |
| `EMBEDDING_REMOTE_URL` / `EMBEDDING_REMOTE_TIMEOUT_SECONDS` | unset / `60` | `remote` only, e.g. `http://api:8000/internal/embed`; connection failures are transient (job retried, search 503) |
| `INTERNAL_EMBED_SECRET` | unset | >= 32 chars; enables `POST /internal/embed` (404 when unset), sent by the worker as `X-Internal-Secret`, compared in constant time; required with `EMBEDDING_PROVIDER=remote`. Not in the OpenAPI docs; Caddy answers 404 for `/internal/*` |
| `INTERNAL_EMBED_MAX_BATCH` / `INTERNAL_EMBED_MAX_TEXT_CHARS` | `64` / `8000` | per-request caps (the body is also capped by `MAX_REQUEST_BODY_BYTES`) |
| `TORCH_NUM_THREADS` | `2` | inference threads per process (ONNX Runtime intra-op or PyTorch); `0` = one per core (much slower when processes share the CPU, see [docs/performance.md](performance.md)) |
| `CHUNK_SIZE` / `CHUNK_OVERLAP` / `MAX_CHUNKS_PER_DOCUMENT` | `400` / `60` / `1000` | tokens of the embedding tokenizer |
| `HF_HUB_OFFLINE` | `0` | `1` = use only the cached model |
| `TOP_K` / `MAX_TOP_K` / `CANDIDATE_K` / `MAX_QUERY_LENGTH` | `5` / `20` / `40` / `1000` | |
| `MIN_EVIDENCE_SIMILARITY` | `0.48` | if the best passage is below it, `/ask` answers "insufficient evidence" without calling the LLM |
| `ASK_TOP_K` / `ASK_CONTEXT_MIN_SIMILARITY` | `8` / `0.40` | passages sent to the LLM once the gate passed, and the floor for including them ([docs/rag.md](rag.md)) |
| `ASK_SCOPED_MIN_SIMILARITY` | `0.20` | gate for questions scoped to one document or about a whole document ("summarize this document"); the LLM decides |
| `LLM_STRUCTURED_OUTPUT` | `true` | JSON-schema structured output; one automatic retry without it if the endpoint rejects the schema |
| `RERANKING_ENABLED` / `RERANKER_MODEL` / `RERANK_TOP_K` | `false` / `cross-encoder/ms-marco-MiniLM-L-6-v2` / `20` | optional cross-encoder; needs `uv sync --extra torch` |
| `LLM_PROVIDER` / `LLM_MODEL` / `LLM_BASE_URL` | `openai` / `gpt-4o-mini` / `https://api.openai.com/v1` | any OpenAI-compatible endpoint; `none` disables `/ask` |
| `LLM_TIMEOUT_SECONDS` / `LLM_MAX_OUTPUT_TOKENS` / `LLM_TEMPERATURE` / `MAX_CONTEXT_TOKENS` | `30` / `900` / `0` / `4000` | |
| `API_DOCS_ENABLED` | empty (on; off in production) | `/docs`, `/redoc`, `/openapi.json` |
| `MAX_REQUEST_BODY_BYTES` / `UPLOAD_BODY_OVERHEAD_BYTES` | `1048576` / `65536` | enforced before the body is parsed |
| `SECURITY_HEADERS_ENABLED` | `true` | HSTS only in production |
| `RATE_LIMIT_ENABLED` / `RATE_LIMIT_BACKEND` | `true` / `redis` | `memory` is per process, rejected in production |
| `RATE_LIMIT_REGISTER` / `_LOGIN` / `_LOGIN_PER_EMAIL` / `_UPLOAD` / `_SEARCH` / `_ASK` / `_REPROCESS` | `5/minute` / `10/minute` / `5/minute` / `10/minute` / `60/minute` / `10/minute` / `10/minute` | `N/second\|minute\|hour\|day` |
| `RATE_LIMIT_REGISTER_DAILY` / `_UPLOAD_DAILY` / `_UPLOAD_TOKEN` / `_ASK_DAILY` | `20/day` / `100/day` / `30/minute` / `200/day` | second, longer window for public demos |
| `RATE_LIMIT_DEMO` / `RATE_LIMIT_DEMO_GLOBAL` | `3/day` per IP / `200/day` total | demo sessions; fail closed if Redis is down |
| `DEMO_ENABLED` / `DEMO_MAX_QUESTIONS` / `DEMO_MAX_UPLOADS` / `DEMO_MAX_UPLOAD_BYTES` / `DEMO_ALLOWED_EXTENSIONS` / `DEMO_TTL_HOURS` / `DEMO_CLEANUP_INTERVAL_SECONDS` | `true` / `3` / `1` / `5242880` / `pdf` / `24` / `900` | [docs/demo-mode.md](demo-mode.md) |
| `CLIENT_IP_HEADER_SECRET` | unset | >= 24 chars; the API trusts `X-DIP-Client-IP` from the BFF only with this shared secret (set the same value as `DIP_CLIENT_IP_SECRET` on Vercel). Strongly recommended in production, otherwise per-IP limits count Vercel's egress IPs |
| `METRICS_ENABLED` / `WORKER_METRICS_PORT` | `true` / empty | compose sets the worker port to 9100 |
| `CELERY_TASK_SOFT_TIME_LIMIT` / `CELERY_TASK_TIME_LIMIT` | `240` / `300` | seconds; soft < hard |
| `STALE_JOB_TIMEOUT_SECONDS` / `STALE_JOB_CHECK_INTERVAL_SECONDS` | `900` / `300` | reconciler; timeout must exceed the hard limit; interval `0` = not scheduled |
| `TEST_DATABASE_URL` / `TEST_REDIS_URL` | - | test suite only |

Further tunables without `.env.example` entries: `DB_POOL_SIZE`, `DB_MAX_OVERFLOW`,
`CELERY_TASK_MAX_RETRIES`, `CELERY_RETRY_BACKOFF_SECONDS`, `UPLOAD_CHUNK_SIZE_BYTES`,
`JWT_ISSUER`, `EMBEDDING_DEVICE`, `EMBEDDING_QUERY_INSTRUCTION`,
`MAX_DOCX_UNCOMPRESSED_BYTES`, and the DIP1 SDK-adapter settings `OPENAI_CHAT_MODEL`,
`OPENAI_EMBEDDING_MODEL`, `OPENAI_TIMEOUT_SECONDS` (legacy; not used by `/ask` or the
pipeline, which read `LLM_*` and `EMBEDDING_*`).

S3 / OCI storage: `STORAGE_BACKEND=s3|oci` with `STORAGE_S3_BUCKET`,
`STORAGE_S3_ENDPOINT_URL`, `STORAGE_S3_REGION`, `STORAGE_S3_ACCESS_KEY_ID`,
`STORAGE_S3_SECRET_ACCESS_KEY`, `STORAGE_S3_PREFIX`.
