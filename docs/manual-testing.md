# Manual test checklist (Windows, PowerShell 7)

A sequential, copy-paste walkthrough of the whole system on a Windows PC with Docker
Desktop. Every step lists the command and the expected result. Run the steps **in
order in one PowerShell 7 window** (`pwsh`), from the repository root; later steps use
variables (`$base`, `$h`, `$doc`, ...) set by earlier ones.

Why PowerShell 7: `Invoke-RestMethod -SkipHttpErrorCheck -StatusCodeVariable` (used to
show 4xx/5xx status codes without exceptions) does not exist in Windows PowerShell 5.1.
Uploads use `curl.exe` (shipped with Windows 10/11) because it lets us set the part's
content type, which the API validates.

Default rate limits apply (`RATE_LIMIT_REGISTER=5/minute` per IP,
`RATE_LIMIT_LOGIN_PER_EMAIL=5/minute`). If you repeat steps quickly and get `429`, wait
a minute.

Status of this checklist: the commands were written for Windows and **have not been
executed on Windows** by the author of this file; the equivalent flow ran on Linux via
`scripts/smoke_test.py` (see [verification report](history/final-project-report.md)).

---

### 1. Prerequisites

```powershell
docker version            # Docker Desktop running, WSL 2 backend
docker compose version    # v2.x
py -3.12 --version        # Python 3.12 (only for the helper scripts; stdlib only)
$PSVersionTable.PSVersion # 7.x
```

Expected: all four print versions without errors.

### 2. Configure `.env`

New checkout (no `.env` yet):

```powershell
py -3.12 scripts\generate_env.py                          # random JWT/Postgres/Redis secrets
py -3.12 scripts\generate_env.py --force --openai-key-file env   # optional: import key from a file named env
```

Existing `.env` from an earlier stage (adds only the missing keys, never changes values):

```powershell
py -3.12 scripts\generate_env.py --merge --dry-run   # lists missing key names only
py -3.12 scripts\generate_env.py --merge             # appends them; old file kept as .env.bak
```

Expected: only key *names* are printed (e.g. `added RATE_LIMIT_BACKEND`), never values.
A second `--merge` prints `... nothing to do`. `.env` and `.env.bak` are git-ignored
(`git status` shows neither).

### 3. Start Docker

```powershell
docker compose up --build -d
docker compose ps
```

Expected: `postgres`, `redis`, `api`, `worker` are `Up ... (healthy)`; `migrate` is
`Exited (0)`. The first build downloads the Python dependencies (the default image uses ONNX Runtime, not PyTorch).

### 4. Migrations

```powershell
docker compose logs migrate
docker compose exec api alembic current
```

Expected: the log shows `Running upgrade  -> 0001` and `0001 -> 0002`;
`alembic current` prints `0002 (head)`.

### 5. API is up

```powershell
$base = "http://localhost:8000"
Invoke-RestMethod "$base/health/live"
Start-Process "$base/docs"     # Swagger UI in the browser
```

Expected: `status : ok`; Swagger UI opens.

### 6. Register

```powershell
$email = "alice-$(Get-Random)@example.com"
$password = "alice-" + [guid]::NewGuid().ToString("N")
$body = @{ email = $email; password = $password } | ConvertTo-Json
Invoke-RestMethod -Method Post "$base/auth/register" -ContentType "application/json" -Body $body
```

Expected: an object with `id`, `email`, `role : user`, `is_active : True`.

### 7. Login

```powershell
$login = Invoke-RestMethod -Method Post "$base/auth/login" -ContentType "application/json" -Body $body
$h = @{ Authorization = "Bearer $($login.access_token)" }
Invoke-RestMethod "$base/auth/me" -Headers $h
```

Expected: `token_type : bearer`, `expires_in : 1800`; `/auth/me` returns your email.

### 8. Upload a PDF

```powershell
py -3.12 -c "from scripts.smoke_test import build_pdf; open('sample.pdf','wb').write(build_pdf('Northwind refund policy.','Customers may return unused items within 30 days of delivery for a full refund.','Refunds are issued to the original payment method within 7 business days.'))"
$up = curl.exe -s -X POST "$base/documents" -H "Authorization: Bearer $($login.access_token)" -F "file=@sample.pdf;type=application/pdf" | ConvertFrom-Json
$up
$doc = $up.id
```

Expected: `status : queued`, `job_status : queued`, an `id`. (Uploading the same file
again returns `409 conflict`.)

### 9. Status

```powershell
Invoke-RestMethod "$base/documents/$doc/status" -Headers $h | ConvertTo-Json -Depth 5
```

Expected: `status` is `queued` or `processing`; `job.stage` shows the current step
(`integrity_check`, `extract`, `normalize`, `chunk`, `embed`, `index`).

### 10. Wait for completion

```powershell
do { Start-Sleep 2; $s = Invoke-RestMethod "$base/documents/$doc/status" -Headers $h; $s.status } until ($s.status -in 'completed','failed')
$s | ConvertTo-Json -Depth 5
```

Expected: `completed`, `job.status : completed`, `job.stage : index`, `chunk_count : 1`.
The first document can take a minute while the worker downloads the embedding model
(~130 MB). If it ends `failed` with "Processing failed after several attempts", the
worker could not reach huggingface.co: see [deployment.md](deployment.md#offline-model-cache).

### 11. Semantic search

```powershell
$q = @{ query = "How long do I have to send something back?"; mode = "semantic"; top_k = 3 } | ConvertTo-Json
(Invoke-RestMethod -Method Post "$base/search" -Headers $h -ContentType "application/json" -Body $q).results | Select-Object filename, page_start, score
```

Expected: `sample.pdf`, `page_start 1`, a cosine score (roughly 0.5-0.8).

### 12. Keyword search

```powershell
$q = @{ query = "refund payment method"; mode = "keyword" } | ConvertTo-Json
(Invoke-RestMethod -Method Post "$base/search" -Headers $h -ContentType "application/json" -Body $q).results | Select-Object filename, score
```

Expected: `sample.pdf` with a `ts_rank` score.

### 13. Hybrid search

```powershell
$q = @{ query = "refund window in days"; mode = "hybrid" } | ConvertTo-Json
Invoke-RestMethod -Method Post "$base/search" -Headers $h -ContentType "application/json" -Body $q | ConvertTo-Json -Depth 5
```

Expected: `mode : hybrid`, top result `sample.pdf` (score is an RRF value such as 0.03).

### 14. Ask

```powershell
$a = @{ question = "How many days do customers have to return items?" } | ConvertTo-Json
$ans = Invoke-RestMethod -Method Post "$base/ask" -Headers $h -ContentType "application/json" -Body $a -SkipHttpErrorCheck -StatusCodeVariable sc
$sc; $ans | ConvertTo-Json -Depth 6
```

Expected **without** a real `OPENAI_API_KEY` (placeholder): `503` with
`"Question answering is not configured; /search still works"`.
With a real key (see "Real OpenAI test" below): `200`, an answer mentioning 30 days with
`[S1]`, `insufficient_evidence : false`, `model : gpt-4o-mini`.

### 15. Verify citations (only with a real or stub LLM)

```powershell
[regex]::Matches($ans.answer, '\[(S\d+)\]') | ForEach-Object { $_.Groups[1].Value } | Sort-Object -Unique
$ans.citations | Select-Object source_id, document_id, filename, page_start
$ans.warnings
```

Expected: every label in the answer appears as a `source_id` in `citations`; each citation's
`document_id` equals `$doc`; `warnings` is empty or `invalid_citations_removed` (an
invented label was stripped).

### 16. Unrelated question

```powershell
$a = @{ question = "What is the boiling point of mercury?" } | ConvertTo-Json
Invoke-RestMethod -Method Post "$base/ask" -Headers $h -ContentType "application/json" -Body $a | ConvertTo-Json
```

Expected: `200`, `insufficient_evidence : True`, `model : null` (the LLM was not called;
this works without a key), `citations : []`.

### 17. Reprocess

```powershell
Invoke-RestMethod -Method Post "$base/documents/$doc/reprocess" -Headers $h -SkipHttpErrorCheck -StatusCodeVariable sc; $sc
Invoke-RestMethod -Method Post "$base/documents/$doc/reprocess" -Headers $h -SkipHttpErrorCheck -StatusCodeVariable sc; $sc
do { Start-Sleep 2; $s = Invoke-RestMethod "$base/documents/$doc/status" -Headers $h } until ($s.status -in 'completed','failed'); $s.status
```

Expected: `202` then `409` (already queued/processing; `202` only if the worker
finished in between), then `completed` with `job.attempts : 1` for the new job.

### 18. Second user

```powershell
$email2 = "bob-$(Get-Random)@example.com"
$body2 = @{ email = $email2; password = $password } | ConvertTo-Json
Invoke-RestMethod -Method Post "$base/auth/register" -ContentType "application/json" -Body $body2 | Out-Null
$h2 = @{ Authorization = "Bearer $((Invoke-RestMethod -Method Post "$base/auth/login" -ContentType 'application/json' -Body $body2).access_token)" }
```

Expected: no output, no error.

### 19. Isolation

```powershell
foreach ($r in @(
  @{ m = 'Get';    u = "$base/documents/$doc" },
  @{ m = 'Get';    u = "$base/documents/$doc/status" },
  @{ m = 'Post';   u = "$base/documents/$doc/reprocess" },
  @{ m = 'Delete'; u = "$base/documents/$doc" })) {
  Invoke-RestMethod -Method $r.m $r.u -Headers $h2 -SkipHttpErrorCheck -StatusCodeVariable sc | Out-Null; "$($r.m) $($r.u) -> $sc"
}
(Invoke-RestMethod "$base/documents" -Headers $h2).total
$q = @{ query = "refund"; mode = "hybrid" } | ConvertTo-Json
(Invoke-RestMethod -Method Post "$base/search" -Headers $h2 -ContentType "application/json" -Body $q).results.Count
$q = @{ query = "refund"; document_id = $doc } | ConvertTo-Json
Invoke-RestMethod -Method Post "$base/search" -Headers $h2 -ContentType "application/json" -Body $q -SkipHttpErrorCheck -StatusCodeVariable sc | Out-Null; $sc
```

Expected: four lines ending `-> 404`; total `0`; `0` results; `404` for the foreign
`document_id`. Alice's document is still there afterwards
(`Invoke-RestMethod "$base/documents/$doc" -Headers $h` works).

### 20. Invalid file

```powershell
Set-Content -Path evil.exe -Value "MZ not really a program"
curl.exe -s -o NUL -w "%{http_code}`n" -X POST "$base/documents" -H "Authorization: Bearer $($login.access_token)" -F "file=@evil.exe;type=application/octet-stream"
```

Expected: `415`.

### 21. Oversized upload

```powershell
[IO.File]::WriteAllBytes("$PWD\big.txt", [byte[]]::new(11MB))
curl.exe -s -w "`n%{http_code}`n" -X POST "$base/documents" -H "Authorization: Bearer $($login.access_token)" -F "file=@big.txt;type=text/plain"
Remove-Item big.txt
```

Expected: `413` with `"code":"payload_too_large"`. The API rejects it from the
`Content-Length` header before reading the body (curl may report that the server
closed the connection early; the status code is still 413).

### 22. Rate limiting

```powershell
$victim = @{ email = "victim-$(Get-Random)@example.com"; password = "wrong-password-123" } | ConvertTo-Json
1..6 | ForEach-Object { Invoke-RestMethod -Method Post "$base/auth/login" -ContentType "application/json" -Body $victim -SkipHttpErrorCheck -StatusCodeVariable sc | Out-Null; $sc }
```

Expected: `401` five times, then `429` (`RATE_LIMIT_LOGIN_PER_EMAIL=5/minute`); the 429
response has a `Retry-After` header. If Redis is stopped (`docker compose stop redis`),
login and register answer `503` (fail closed) while search keeps working (fail open);
start it again with `docker compose start redis`.

### 23. Health

```powershell
Invoke-RestMethod "$base/health"; Invoke-RestMethod "$base/health/live"
```

Expected: `status : ok` twice.

### 24. Readiness

```powershell
Invoke-RestMethod "$base/health/ready" | ConvertTo-Json -Depth 4
docker compose exec redis sh -c "env -u REDISCLI_AUTH redis-cli ping"
```

Expected: `status : ready` with `database`, `pgvector` and `redis` all `ok`; the
unauthenticated `PING` prints `NOAUTH Authentication required.`

### 25. Metrics

```powershell
(Invoke-WebRequest "$base/metrics").Content -split "`n" | Select-String 'dip_http_requests_total\{' | Select-Object -First 8
(Invoke-WebRequest "$base/metrics").Content.Contains($doc)
```

Expected: lines such as
`dip_http_requests_total{method="GET",route="/documents/{document_id}/status",status="200"}`;
the second command prints `False` (no document ids in labels).

### 26. Inspect logs for secrets

```powershell
$envMap = @{}
Get-Content .env | Where-Object { $_ -match '^[A-Z0-9_]+=' } | ForEach-Object { $k, $v = $_ -split '=', 2; $envMap[$k] = $v }
$logs = (docker compose logs --no-color api worker 2>&1) | Out-String
foreach ($k in 'JWT_SECRET_KEY', 'POSTGRES_PASSWORD', 'REDIS_PASSWORD', 'OPENAI_API_KEY') {
  $v = $envMap[$k]; if ($v -and $v.Length -ge 8) { "{0}: {1} occurrence(s)" -f $k, ([regex]::Matches($logs, [regex]::Escape($v))).Count }
}
"user password: {0}" -f ([regex]::Matches($logs, [regex]::Escape($password))).Count
"access token: {0}" -f ([regex]::Matches($logs, [regex]::Escape($login.access_token))).Count
"document text: {0}" -f ([regex]::Matches($logs, 'original payment method')).Count
```

Expected: every count is `0`. Values are compared in memory and never printed.

Clean up: `Remove-Item sample.pdf, evil.exe`; `docker compose down` (keeps data) or
`docker compose down -v` (deletes all volumes, including documents and the model cache).

---

## Real OpenAI test (optional, costs money)

Safe procedure; the key never appears on screen or in git:

1. Put the key into `.env` without echoing it: keep it in a file named `env` (one line
   `OPENAI_API_KEY=sk-...`, git-ignored) and, if `.env` still has the placeholder,
   edit `.env` in an editor and paste it (do not `echo` it in the shell, PowerShell
   history would keep it). `generate_env.py --merge --openai-key-file env` only adds the
   key when `.env` has no `OPENAI_API_KEY` line at all; it never replaces an existing value.
2. Optional settings in `.env`: `LLM_MODEL` (default `gpt-4o-mini`), `LLM_BASE_URL`
   (default `https://api.openai.com/v1`), `LLM_TIMEOUT_SECONDS` (default 30),
   `LLM_MAX_OUTPUT_TOKENS` (700), `LLM_TEMPERATURE` (0). The client sends `max_tokens`
   and `temperature`; models that reject those parameters (some reasoning models) will
   answer `503` - use a chat model such as `gpt-4o-mini`.
3. Recreate the API so it reads the new value: `docker compose up -d api`.
4. Repeat steps 14-16. Expected: 200 with a cited answer for the policy question,
   `insufficient_evidence : True` and no LLM call for the unrelated question.
5. Or run the whole scenario: `py -3.12 scripts\smoke_test.py --real-llm` (two `/ask`
   calls of a few hundred tokens each).
6. Run step 26 again: `OPENAI_API_KEY: 0 occurrence(s)`.
7. Failure modes are controlled: a wrong key gives `503` with "The answer service is
   temporarily unavailable; /search still works" and a log line `llm.http_error` with
   `status_code: 401` (no key, prompt or response body is logged).

No paid request was made while preparing this project; the real-OpenAI path is
**NOT VERIFIED** (see [history/final-project-report.md](history/final-project-report.md)).

---

## Web UI walkthrough (frontend)

Prerequisite: the backend from steps 1-5 is running and the frontend runs locally
(`cd frontend; Copy-Item .env.example .env.local; npm ci; npm run dev`), or use the
deployed Vercel URL. Use two different browser profiles (or a private window) for the
second user. Status: the same flow is automated in `frontend/e2e/full-flow.spec.ts`
(10 Playwright tests, passed against the local production-like stack); clicking
through it by hand on Windows is NOT VERIFIED.

| # | Action | Expected |
| --- | --- | --- |
| U1 | Open `/` | landing page with "Try the demo" / "Create free account"; footer links work |
| U2 | Open `/dashboard` while signed out | redirected to `/login?next=/dashboard` |
| U3 | Register with a new e-mail and a password of 12+ characters | redirected to the dashboard; e-mail shown in the header |
| U4 | DevTools > Application > Cookies | `dip_session` is `HttpOnly`, `SameSite=Lax` (and `Secure` on HTTPS); Local/Session Storage contain no token |
| U5 | Upload > choose a PDF (< 10 MB) | progress bar, then a link to the document; status goes Queued -> Processing -> Completed |
| U6 | Upload a `.png` or a file > 10 MB | friendly error, nothing uploaded |
| U7 | Documents | list with status badges, filter box, pagination when > 1 page |
| U8 | Open the document | metadata, latest job and stage, chunk count; Reprocess and Delete buttons |
| U9 | Search > hybrid / semantic / keyword for a phrase in the document | ranked passages with document name, page numbers and score |
| U10 | Ask a question answered by the document | without an OpenAI key: "AI answers are not configured" message; with a key or the stub LLM: an answer with `[S1]` citations listing the passages |
| U11 | Ask an unrelated question | "Not enough evidence" card, no LLM call, no citations |
| U12 | Second user: open the first user's document URL `/documents/<id>` | "not found" (never the other user's data); their search finds nothing of the first user's |
| U13 | Reprocess the document twice quickly | the second request shows a "Conflict" error (the document is already being processed) |
| U14 | Delete the document (confirm dialog) | removed from the list; its URL now shows "not found" |
| U15 | Settings > Sign out | back on the landing page; `/dashboard` redirects to login again |
| U16 | Mobile width (DevTools device toolbar) | navigation collapses into a menu; pages remain usable |

## UX round: demo mode, theme, Ask (frontend)

Run the frontend (`cd frontend; npm run dev`) against the local API, or use
`scripts/e2e_prod_local.sh`, which automates all of this with Playwright
(`e2e/demo.spec.ts`, `e2e/theme.spec.ts`, `e2e/full-flow.spec.ts`).

1. Open http://localhost:3000 in a fresh private window: the page is **dark** with no
   white flash. The header shows the logo, "Document Intelligence & Analysis" in the tab
   title, and a sun icon (switch to light).
2. Click the toggle, reload: it stays light. Open `/login`: still light. Toggle back.
3. With the Dark Reader extension on, the console shows no hydration warning
   (the page sends `darkreader-lock` and `color-scheme`).
4. "Try the demo": you land on `/upload?demo=1` with the banner
   "Demo: 3 of 3 questions left". Upload a small PDF: the stepper goes
   Uploading → Processing → Ready, a toast says "Document ready", then
   "Ask questions about this document".
5. Ask a question: the answer has `[1]` chips; clicking one highlights and expands the
   source card. "Copy" copies the answer and sources. The banner counts down.
6. After 3 questions, a 4th opens "Create a free account to continue". Uploading a second
   file opens it too. Fill email + password: the account is converted, the banner
   disappears and the document is still there.
7. Hit a rate limit (e.g. set `RATE_LIMIT_ASK=2/minute` and ask 3 times): the message is
   "You've reached the rate limit for this action. Please try again in N seconds."
8. Resize to 375px wide: bottom navigation, hamburger menu, no horizontal scrolling.
9. `/impressum` and `/privacy` render with highlighted placeholders.

## Production checks (after deploying)

| # | Command | Expected |
| --- | --- | --- |
| P1 | `scripts/health_check.sh --url https://<API_DOMAIN>` (on the VM) | every line `ok`, "all checks passed" |
| P2 | `Invoke-WebRequest https://<API_DOMAIN>/metrics -SkipHttpErrorCheck` | `404` |
| P3 | `py -3.12 scripts\production_smoke_test.py --base-url https://<API_DOMAIN> --register` (with `$env:SMOKE_EMAIL`, `$env:SMOKE_PASSWORD`) | `RESULT: PASS` |
| P4 | Browser on the Vercel URL: U3, U5, U9, U10 | same as above; no CORS errors in the console |
| P5 | `scripts/restore_postgres.sh --file <latest dump> --into dip_restore_check` | counts equal the live database |
