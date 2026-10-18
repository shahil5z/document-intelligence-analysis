# Local development

Two pieces run locally: the backend stack (`docker compose up`, unchanged from the
earlier stages) and the Next.js frontend (`npm run dev`). Commands are given for
**Windows PowerShell 7 with Docker Desktop** (WSL 2 backend) first, then bash.

Status: the bash/Linux commands were run on the build machine. The PowerShell commands
are written for Windows but were **not executed on Windows** (NOT VERIFIED there).

## Requirements

- Docker Desktop (WSL 2 backend), Git, Python 3.12 (`py -3.12`) for `generate_env.py`.
- Node.js 20.9+ (22 LTS recommended) and npm for the frontend.
- Optional: [uv](https://docs.astral.sh/uv/) to run the backend tests outside Docker.

## 1. Backend

```powershell
git clone <repo-url> dip; cd dip; git checkout final
py -3.12 scripts\generate_env.py              # new .env with random secrets (names printed, never values)
# existing .env from an earlier stage:  py -3.12 scripts\generate_env.py --merge --dry-run ; then --merge
docker compose up --build -d
docker compose ps                              # postgres, redis, api, worker healthy; migrate exited 0
Invoke-RestMethod http://localhost:8000/health/ready
```

```bash
python3 scripts/generate_env.py && docker compose up --build -d && curl -s localhost:8000/health/ready
```

The API is on `http://localhost:8000` (`API_PORT`), Swagger at `/docs`. Without
`OPENAI_API_KEY` everything except `/ask` works; `/ask` answers 503 "not configured"
once it has found evidence. For a key-free `/ask` add the local stub:
`docker compose -f docker-compose.yml -f docker-compose.stub-llm.yml up -d`.

## 2. Frontend

```powershell
cd frontend
Copy-Item .env.example .env.local              # NEXT_PUBLIC_API_URL=http://localhost:8000
npm ci
npm run dev                                    # http://localhost:3000
```

```bash
cd frontend && cp .env.example .env.local && npm ci && npm run dev
```

Open <http://localhost:3000>, register, upload a PDF/DOCX/TXT, wait for "Completed",
then try Search and Ask. The backend's default `CORS_ALLOWED_ORIGINS` already contains
`http://localhost:3000` (needed for the direct upload).

On plain `http://localhost` the session cookie is not marked `Secure` (browsers would
drop it); on HTTPS it always is.

## 3. Checks

```powershell
# backend (needs uv; the DB-backed tests need a PostgreSQL with pgvector)
uv run ruff check . ; uv run ruff format --check . ; uv run mypy app tests scripts
docker run -d --name dip-test-db -e POSTGRES_USER=dip -e POSTGRES_PASSWORD=dip -e POSTGRES_DB=dip_test -p 5433:5432 pgvector/pgvector:pg16
$env:TEST_DATABASE_URL = "postgresql+psycopg://dip:dip@localhost:5433/dip_test"
uv run pytest --cov=app

# frontend
cd frontend; npm run lint; npm run typecheck; npm run build
```

## 4. Production-like run on your machine (optional)

`scripts/e2e_prod_local.sh` (bash; Linux, macOS or WSL) starts `docker-compose.prod.yml`
with a local Caddy CA on ports 8080/8443, builds the frontend against
`https://api.localhost:8443`, runs it with `next start` and executes the Playwright
suite:

```bash
# once: npx playwright install --with-deps chromium   (in frontend/)
grep -q api.localhost /etc/hosts || echo '127.0.0.1 api.localhost app.localhost' | sudo tee -a /etc/hosts
scripts/e2e_prod_local.sh            # build, start, test (stack keeps running)
scripts/e2e_prod_local.sh --down     # remove the stack and its volumes
```

Environment knobs: `DOCKER_CMD="sudo docker"` if your user is not in the docker group;
`SEED_HF_CACHE=~/.cache/huggingface` to copy a local model cache into the stack
(`HF_HUB_OFFLINE=1`) when containers cannot reach huggingface.co.

## 5. Stopping

```powershell
docker compose down          # keep data
docker compose down -v       # also delete the database, files and model cache volumes
```

## Troubleshooting

| Symptom | Fix |
| --- | --- |
| Frontend shows "The server could not be reached" | backend not running, or `NEXT_PUBLIC_API_URL` wrong; restart `npm run dev` after editing `.env.local` |
| Upload fails with a network/CORS error | add the frontend origin to `CORS_ALLOWED_ORIGINS` in `.env`, then `docker compose up -d` |
| First document takes long | the embedding model (~130 MB) is downloaded on first use |
| Port 8000 in use | set `API_PORT` in `.env` and `NEXT_PUBLIC_API_URL` accordingly |
