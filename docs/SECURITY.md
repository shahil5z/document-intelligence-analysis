# Security notes (DIP1 + DIP2)

DIP1 controls (auth, upload validation, storage guard, secrets handling, Redis AUTH,
CORS, non-root containers) are described in [architecture.md](architecture.md#security-boundaries).
This page covers what DIP2 adds and what is still open.

## Tenant isolation in retrieval

- `document_chunks.owner_id` is set from the document's owner by the worker; search
  queries filter `c.owner_id = :caller` **and** join `documents` with
  `d.owner_id = :caller AND d.status = 'completed'` inside the SQL statement. Results are
  never filtered in Python after the fact.
- `document_id` filters are checked for ownership first (404 for foreign ids).
- `/ask` uses the same retrieval, so another user's text can never reach the prompt.
- Deleting a document cascades to its chunks; deleted or in-progress documents are not
  searchable. Tested at the API level and in the compose smoke test.

## Prompt injection

Threat: an uploaded document contains instructions ("ignore previous instructions",
fake tags, fake citations). Mitigations:

1. Retrieved text goes only into the user message inside `<untrusted_sources>`, never
   into the system message.
2. `&`, `<`, `>` in excerpts and in the question are escaped, so text cannot close the
   wrapper or forge a `<source>` element.
3. The system prompt tells the model that excerpts are data and not instructions.
4. Output validation: citation labels not in the sent context are removed; citation
   metadata comes from database rows, not from model output.
5. The LLM has no tools and the response triggers no actions; the worst outcome of a
   successful injection is a wrong or misleading answer to the uploader of that
   document (who can only inject into their own retrieval scope).

Limits: instructions in the excerpts can still influence the answer text; this is
mitigated, not solved. No classifier or second-pass checker exists. Tested with a
document containing an injection payload and a mock model that emits a fake citation.

## Secrets

- `OPENAI_API_KEY` stays a `SecretStr`; it is read only when `/ask` needs the LLM and is
  passed only in the `Authorization` header. It is not logged, not returned and not
  included in exceptions (tested with a fake key and captured logs).
- `.env` and `.env.*` (except `.env.example`) and a root file named `env` are
  git-ignored. DIP2 work never read `.env`; only variable names were used.
- No network calls at startup, in health checks or in the test suite (embedding model
  and LLM are lazy; tests inject fakes; a subprocess test asserts that importing the API
  and worker loads neither the OpenAI SDK nor torch/sentence-transformers/pypdf).

## Untrusted files

- Parsers run in the worker, not in the API process.
- PDF: `pypdf` in non-strict mode; exceptions are caught and reported generically.
  Encrypted PDFs are rejected unless they open with an empty password.
- DOCX: total uncompressed size is checked before parsing
  (`MAX_DOCX_UNCOMPRESSED_BYTES`, default 100 MB) as a zip-bomb guard.
- TXT: binary content (NUL bytes) is rejected.
- `MAX_CHUNKS_PER_DOCUMENT` bounds the work and storage per document.
- Not done: sandboxing the parsers (separate process with memory/CPU limits), malware
  scanning, PDF sanitisation. A crafted PDF could still make `pypdf` slow; the Celery
  time limits (240 s soft / 300 s hard) are the only bound.

## Model supply chain

- The embedding model is downloaded from Hugging Face on first use into `HF_HOME`
  (compose volume `model_cache`). The model revision is not pinned; set
  `HF_HUB_OFFLINE=1` after seeding the cache to stop network access. Pinning a revision
  hash and verifying it is listed for DIP3.
- `sentence-transformers` loads safetensors weights for `BAAI/bge-small-en-v1.5`
  (observed in the box download); the code does not enforce safetensors-only loading.

## Abuse / cost

- `/ask` can trigger one LLM call per request; there is no rate limiting or per-user
  quota yet (DIP3). `MAX_QUERY_LENGTH`, `MAX_TOP_K`, `MAX_CONTEXT_TOKENS` and
  `LLM_MAX_OUTPUT_TOKENS` bound the size of each call.
- Search embeds the query on the API process CPU; heavy query load competes with
  request handling (**Not measured**).
