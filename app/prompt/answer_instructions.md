<!--
  Appended to the user message after the <question> and <untrusted_sources> blocks.
  It restates the output contract right next to the data, where models pay the most
  attention. $source_count is replaced with the number of sources that were sent.

  The JSON shape below matches response_schema.json, which is also sent as an OpenAI
  structured-output schema when the endpoint supports it (LLM_STRUCTURED_OUTPUT=true).
  Without it, the parser in app/services/answer_parsing.py still accepts plain text with
  [n] markers, fenced JSON and common variations.
-->
Answer the question in <question> using only the $source_count sources above. Cite them by number, like [1] or [2][3].

Reply with a JSON object only:
{"status": "answered" | "partial" | "insufficient", "answer": "<markdown answer with [n] citations>", "citations": [<numbers of the sources you cited>], "missing_information": "<what the sources do not cover, or an empty string>"}

- "answered": the sources fully answer the question.
- "partial": you answered what the sources support; "missing_information" says what is missing.
- "insufficient": none of the sources is relevant; "answer" is one sentence saying so and "citations" is empty.
