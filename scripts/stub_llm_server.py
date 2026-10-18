"""Tiny OpenAI-compatible ``/chat/completions`` stub for offline end-to-end runs.

Used by ``docker-compose.stub-llm.yml`` so ``POST /ask`` can be exercised through the real
HTTP client, prompt builder and citation validator without an API key or network.

Behaviour: if the user message contains ``<source id="S1"`` the reply cites ``[S1]``
(valid) and ``[S99]`` (invalid, must be stripped by the API); otherwise it answers with
the insufficient-evidence sentinel. Requests without ``Authorization: Bearer ...`` get
401, like the real API. Nothing is logged except the request line. Standard library only.
"""

import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

ANSWER = (
    "Customers may return unused items within 30 days of delivery [S1]. "
    "Refunds take up to a year [S99]."
)


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
        user = next(
            (m["content"] for m in payload.get("messages", []) if m.get("role") == "user"), ""
        )
        content = ANSWER if '<source id="S1"' in user else "INSUFFICIENT_EVIDENCE"
        self._send(
            200,
            {
                "id": "stub-1",
                "object": "chat.completion",
                "model": payload.get("model", "stub"),
                "choices": [{"index": 0, "message": {"role": "assistant", "content": content}}],
                "usage": {"prompt_tokens": len(user) // 4, "completion_tokens": 20},
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
