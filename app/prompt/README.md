# app/prompt: the assistant's prompts

Everything the language model is told lives here, not in Python code.

| File | Used as | Notes |
| --- | --- | --- |
| `system.md` | system message of every `/ask` LLM call | rules: grounding, citations `[n]`, partial answers, prompt-injection defence, style, language |
| `answer_instructions.md` | appended to the user message after the question and the sources | output contract (JSON with `status`, `answer`, `citations`, `missing_information`); `$source_count` is filled in |
| `response_schema.json` | OpenAI structured outputs (`response_format: json_schema`, strict) | sent when `LLM_STRUCTURED_OUTPUT=true` (default); servers that reject it get a plain request (automatic fallback) |
| `insufficient_evidence.md` | answer text when no grounded answer is produced | shown to users |

`__init__.py` loads the files once per process (cached), strips `<!-- ... -->`
comments, and exposes `PROMPT_VERSION`. Bump the version whenever you change a prompt;
it is logged with every answer and returned in the `/ask` response (`prompt_version`).

The user message itself (question + `<untrusted_sources>` with escaped excerpts) is
assembled in `app/services/rag_prompt.py`; the reply is parsed by
`app/services/answer_parsing.py`.

These files ship in the Docker image (`.dockerignore` re-includes `app/prompt/*.md`).
