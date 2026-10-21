"""Tiny OpenAI-compatible ``/chat/completions`` stub for offline end-to-end runs.

Used by ``docker-compose.stub-llm.yml`` and the production-like E2E stack so ``POST /ask``
runs through the real HTTP client, prompt, parser and citation validator without an API
key or network. Replies imitate the shapes gpt-4o-mini produces (full
``chat.completion`` envelope, ``refusal: null``, ``finish_reason``, detailed usage).

The answer is built from the sources in the request, so it is about the uploaded
document: the first sentence of source 1 cited ``[1]``, the first sentence of source 2
cited ``[2]`` when there is one, plus a forged ``[99]`` the API must strip.
``STUB_LLM_STYLE`` selects the format:

* ``structured`` (default): JSON per the request's ``response_format`` schema when one is
  sent, otherwise the same JSON inside a Markdown code fence (what models often return
  when they are asked for JSON without structured outputs);
* ``fenced``: always fenced JSON;
* ``text``: plain Markdown with ``[1]`` markers;
* ``legacy``: the DIP2 behaviour (static answer with ``[S1]`` and ``[S99]``).

Requests without ``Authorization: Bearer ...`` get 401. With ``STUB_LLM_REJECT_SCHEMA=1``
a request carrying ``response_format`` gets 400 (to exercise the client's fallback).
Nothing is logged except the request line. Standard library only.
"""

import json
import os
import re
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

LEGACY_ANSWER = (
    "Customers may return unused items within 30 days of delivery [S1]. "
    "Refunds take up to a year [S99]."
)
_SOURCE = re.compile(r'<source id="(\d+)"[^>]*>\n(.*?)\n</source>', re.DOTALL)


def _first_sentence(text: str) -> str:
    text = " ".join(text.replace("&lt;", "<").replace("&gt;", ">").replace("&amp;", "&").split())
    match = re.search(r"(.{20,240}?[.!?])(\s|$)", text)
    sentence = match.group(1) if match else text[:200]
    return sentence.rstrip(".!?")


def build_reply(user: str, style: str, structured: bool) -> str:
    if style == "legacy":
        return LEGACY_ANSWER if '<source id="' in user else "INSUFFICIENT_EVIDENCE"
    sources = _SOURCE.findall(user)
    if not sources:
        data: dict[str, Any] = {
            "status": "insufficient",
            "answer": "None of the provided sources address this question.",
            "citations": [],
            "missing_information": "The sources do not cover the question.",
        }
    else:
        parts = [f"### Summary\n\nThe document states: {_first_sentence(sources[0][1])} [1]."]
        cited = [1]
        if len(sources) > 1:
            parts.append(f"\n\n- It also states: {_first_sentence(sources[1][1])} [2].")
            cited.append(2)
        parts.append("\n\nThis is consistent with the policy summary [99].")
        data = {
            "status": "answered",
            "answer": "".join(parts),
            "citations": [*cited, 99],
            "missing_information": "",
        }
    if style == "text":
        return str(data["answer"]) if sources else "INSUFFICIENT_EVIDENCE"
    body = json.dumps(data, ensure_ascii=False)
    if style == "fenced" or not structured:
        return f"```json\n{json.dumps(data, ensure_ascii=False, indent=2)}\n```"
    return body


class _Handler(BaseHTTPRequestHandler):
    def do_POST(self) -> None:
        if not self.path.rstrip("/").endswith("/chat/completions"):
            self._send(404, {"error": {"message": "not found"}})
            return
        if not self.headers.get("Authorization", "").startswith("Bearer "):
            self._send(401, {"error": {"message": "missing key"}})
            return
        length = int(self.headers.get("Content-Length", "0"))
        payload = json.loads(self.rfile.read(length) or b"{}")
        structured = "response_format" in payload
        if structured and os.environ.get("STUB_LLM_REJECT_SCHEMA") == "1":
            self._send(
                400,
                {
                    "error": {
                        "message": "Invalid parameter: 'response_format' is not supported.",
                        "type": "invalid_request_error",
                        "param": "response_format",
                        "code": None,
                    }
                },
            )
            return
        user = next(
            (m["content"] for m in payload.get("messages", []) if m.get("role") == "user"), ""
        )
        style = os.environ.get("STUB_LLM_STYLE", "structured")
        content = build_reply(user, style, structured)
        prompt_tokens = len(user) // 4
        completion_tokens = max(1, len(content) // 4)
        self._send(
            200,
            {
                "id": "chatcmpl-stub0000000000000000000000",
                "object": "chat.completion",
                "created": int(time.time()),
                "model": payload.get("model", "stub"),
                "choices": [
                    {
                        "index": 0,
                        "message": {"role": "assistant", "content": content, "refusal": None},
                        "logprobs": None,
                        "finish_reason": "stop",
                    }
                ],
                "usage": {
                    "prompt_tokens": prompt_tokens,
                    "completion_tokens": completion_tokens,
                    "total_tokens": prompt_tokens + completion_tokens,
                    "prompt_tokens_details": {"cached_tokens": 0, "audio_tokens": 0},
                    "completion_tokens_details": {"reasoning_tokens": 0, "audio_tokens": 0},
                },
                "system_fingerprint": "fp_stub",
            },
        )

    def _send(self, status: int, body: dict[str, object]) -> None:
        data = json.dumps(body).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


def main() -> None:
    port = int(os.environ.get("STUB_LLM_PORT", "8080"))
    ThreadingHTTPServer(("0.0.0.0", port), _Handler).serve_forever()  # noqa: S104


if __name__ == "__main__":
    main()
