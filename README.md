# Document Intelligence & Analysis

A document intelligence system for searching documents and generating cited AI answers
using hybrid retrieval and retrieval-augmented generation (RAG). Users upload PDF, DOCX
or TXT files; a background worker extracts, chunks and embeds them; questions are
answered only from retrieved passages, with numbered citations back to the file and page.

- **Live:** https://doc-intelligence-shahil.vercel.app (temporary demo account available,
  or register with any e-mail address)
- **API:** https://api-140-245-232-103.sslip.io

The backend runs on a single free-tier 1 GB VM, so the first request after a quiet period
can take a few seconds.

![Landing page](docs/screenshots/live-landing.png)

## Features

- **Document processing:** PDF (pypdf), DOCX (python-docx) and TXT extraction with page
  numbers, normalisation and token-aware chunking (400 tokens, 60 overlap) that keeps
  page and character offsets.
- **Hybrid search:** semantic search (pgvector, HNSW cosine index), keyword search
  (PostgreSQL full-text, GIN index), and hybrid search that merges both rankings with
  Reciprocal Rank Fusion (default).
- **Cited RAG answers:** retrieved passages are sent to OpenAI `gpt-4o-mini` as numbered
  sources with structured output. Citations that do not match a retrieved passage are
  removed; an answer without any valid citation is withheld. If no passage clears the
  similarity threshold, the API answers "insufficient evidence" without calling the LLM.
- **Suggested questions:** after processing, one LLM call per document produces 3-5
  suggested questions; generic suggestions are shown if that call fails.
- **Background processing:** a Celery worker runs the pipeline with an explicit job state
  machine, bounded retries for transient errors, clear messages for permanent failures,
  and a scheduled task that re-queues stalled jobs and deletes expired demo accounts.
- **Accounts and isolation:** Argon2id password hashing, short-lived JWTs kept in an
  HttpOnly cookie by the Next.js server, and an owner filter inside every SQL query
  (other users' documents return 404).
- **Demo mode:** temporary isolated accounts limited to 1 PDF of up to 5 MB and 3
  questions, deleted 24 hours after creation.
- **Hardening:** upload validation (extension, MIME type, magic bytes, size), rate limits,
  security headers, JSON logs without secrets or document text.

## Architecture

```mermaid
flowchart LR
    user[Browser] --> vercel["Next.js on Vercel<br/>(pages + BFF route handlers)"]
    vercel -->|"server-side, JWT from HttpOnly cookie"| caddy
    user -->|"direct upload, short-lived upload token"| caddy
    subgraph oracle["Oracle Cloud VM (1 GB RAM)"]
        caddy["Caddy (HTTPS)"] --> api["FastAPI API<br/>ONNX embedding model"]
        api --> pg[("PostgreSQL 16 + pgvector")]
        api --> redis[("Redis")]
        api --> files[("Storage volume")]
        redis -->|task queue| worker["Celery worker + beat"]
        worker -->|"POST /internal/embed"| api
        worker --> pg
        worker --> files
    end
    api -->|"/ask: question + retrieved passages"| openai["OpenAI gpt-4o-mini"]
    worker -->|"suggested questions, once per document"| openai
```

Request path for a question: embed the query (ONNX, 384-d) -> vector search and
full-text search scoped to the user's completed documents -> Reciprocal Rank Fusion ->
similarity threshold -> numbered passages to the LLM -> citation validation -> answer
with sources.

Only the API process loads the embedding model. The worker sends chunk batches to the
private `POST /internal/embed` endpoint (shared-secret header), so there is a single model
copy in memory. Caddy returns 404 for `/internal/*` and `/metrics`, and the OpenAPI
docs are disabled in production. Postgres and Redis are not exposed.

More detail: [docs/architecture.md](docs/architecture.md),
[docs/retrieval.md](docs/retrieval.md), [docs/rag.md](docs/rag.md),
[docs/document-processing.md](docs/document-processing.md),
[docs/security.md](docs/security.md).

## Tech Stack

- **Backend:** Python 3.12, FastAPI, Pydantic v2, SQLAlchemy 2, Alembic, PyJWT, pwdlib
  (Argon2id), pypdf, python-docx, gunicorn/uvicorn, uv.
- **Data / Retrieval:** PostgreSQL 16, pgvector (HNSW), PostgreSQL full-text search (GIN),
  Reciprocal Rank Fusion, Redis 7.
- **AI:** `BAAI/bge-small-en-v1.5` embeddings (384 dimensions) on ONNX Runtime with
  `tokenizers`; OpenAI `gpt-4o-mini` for answers and suggested questions.
- **Background jobs:** Celery 5 (worker with embedded beat on the 1 GB VM).
- **Infrastructure:** Docker Compose, Caddy (automatic HTTPS), Oracle Cloud VM, Vercel.
- **Frontend:** Next.js 16 (App Router), React 19, TypeScript, Tailwind CSS 4.
- **Quality:** pytest, ruff, mypy, ESLint, Playwright.

## Local Development

Requirements: Docker with Compose, Python 3.12 (for the env generator), Node.js 20.9+
and npm. Optional: [uv](https://docs.astral.sh/uv/) to run backend tests outside Docker.

Backend (API on http://localhost:8000):

```bash
git clone https://github.com/shahil5z/document-intelligence-analysis.git
cd document-intelligence-analysis
python3 scripts/generate_env.py          # writes .env with random secrets
docker compose up --build -d             # postgres, redis, migrate, api, worker
curl -s http://localhost:8000/health/ready
```

Without `OPENAI_API_KEY` everything except `/ask` and suggested questions works. To try
`/ask` without a key, add the local stub LLM:

```bash
docker compose -f docker-compose.yml -f docker-compose.stub-llm.yml up -d
```

Frontend (http://localhost:3000):

```bash
cd frontend
cp .env.example .env.local               # NEXT_PUBLIC_API_URL=http://localhost:8000
npm ci
npm run dev
```

Details and Windows commands: [docs/local-development.md](docs/local-development.md).

## Environment Variables

All backend settings are listed with comments in [.env.example](.env.example)
(production template: [.env.production.example](.env.production.example)); the frontend
uses [frontend/.env.example](frontend/.env.example). These files contain no real values.

| Variable | Where | Purpose |
| --- | --- | --- |
| `JWT_SECRET_KEY`, `POSTGRES_PASSWORD`, `REDIS_PASSWORD`, `INTERNAL_EMBED_SECRET` | backend | secrets, generated by `scripts/generate_env.py` |
| `OPENAI_API_KEY` | backend | enables `/ask` and suggested questions |
| `CORS_ALLOWED_ORIGINS` | backend | frontend origin(s) allowed for direct uploads |
| `NEXT_PUBLIC_API_URL` | frontend | public API URL (inlined into the browser bundle; not a secret) |
| `DIP_CLIENT_IP_SECRET` | frontend, server-only | lets the BFF forward the client IP for per-IP rate limits |

See [docs/configuration.md](docs/configuration.md) for every option.

## Testing

Latest run (2026-10-21):

| Suite | Command | Result |
| --- | --- | --- |
| Backend unit, API and integration tests | `uv run pytest` | 533 passed, 11 skipped (S3 tests without an S3 server) |
| Backend lint and types | `uv run ruff check .`, `uv run mypy app tests scripts` | passed |
| Frontend lint / types / build | `npm run lint`, `npm run typecheck`, `npm run build` | passed |
| End-to-end (Playwright, production-like stack, stub LLM) | `scripts/e2e_prod_local.sh` | 22 / 22 passed |

The DB-backed tests need PostgreSQL with pgvector:

```bash
docker run -d --name dip-test-db -e POSTGRES_USER=dip -e POSTGRES_PASSWORD=dip \
  -e POSTGRES_DB=dip_test -p 5433:5432 pgvector/pgvector:pg16
TEST_DATABASE_URL=postgresql+psycopg://dip:dip@localhost:5433/dip_test uv run pytest
```

Redis-backed rate-limit and health tests also run when `TEST_REDIS_URL` points at a Redis
with a password. The Playwright suite starts the production compose stack with a local
Caddy CA and a stub LLM, so it never calls OpenAI; it needs
`127.0.0.1 api.localhost app.localhost` in `/etc/hosts` and
`npx playwright install chromium` in `frontend/`. See [docs/testing.md](docs/testing.md).

## Deployment

- **Frontend:** Vercel project with root directory `frontend/`, connected to this
  repository; pushes to `main` deploy to production. Environment variables:
  `NEXT_PUBLIC_API_URL` (the HTTPS API URL) and `DIP_CLIENT_IP_SECRET` (server-only).
- **Backend:** one Oracle Cloud E2.1.Micro VM (1 GB RAM plus swap) running
  `docker-compose.prod.yml` with the `docker-compose.micro.yml` override: Caddy (HTTPS
  via a public certificate), API (one gunicorn worker, holds the ONNX model), Celery
  worker with embedded beat (concurrency 1), a migrate job, PostgreSQL and Redis. Only
  ports 22, 80 and 443 are open.

Guides: [docs/vercel-deployment.md](docs/vercel-deployment.md),
[docs/oracle-cloud-deployment.md](docs/oracle-cloud-deployment.md),
[docs/production-deployment.md](docs/production-deployment.md),
[docs/deployment-checklist.md](docs/deployment-checklist.md).

## Known Limitations

- Answers are generated by a language model and can be wrong; a citation shows which
  passage was used, it does not prove the claim.
- No OCR: scanned PDFs without a text layer fail. Complex tables and multi-column layouts
  may be extracted imperfectly. DOCX reads body paragraphs and tables; no legacy `.doc`.
- The embedding model is English-focused.
- Single VM with local volume storage (S3-compatible storage is implemented but not used
  in production); no replication or failover. The first embedding after a restart loads
  the model, and the API and embedding share one CPU.
- No refresh tokens or server-side token revocation; tokens expire after 30 minutes.
  Registration has no e-mail verification. Rate limits are fixed-window.
- Retrieval quality was evaluated only on a small synthetic set.
- The Impressum and privacy pages contain placeholders that must be completed by the
  operator.

## Screenshots

| | |
| --- | --- |
| ![Answer with citations](docs/screenshots/live-ask-citations.png) | ![Hybrid search](docs/screenshots/live-search-hybrid.png) |
| ![Dashboard](docs/screenshots/live-dashboard.png) | ![Mobile](docs/screenshots/live-mobile.png) |

## Author

Designed and developed by Shohrab Haque Shahil

## License

[MIT](LICENSE), (c) 2026 Shohrab Haque Shahil.
