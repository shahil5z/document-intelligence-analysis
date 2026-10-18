"""Post-deploy smoke test for the public API (standard library only).

Usage:
    SMOKE_EMAIL=you@example.com SMOKE_PASSWORD=... \\
        python3 scripts/production_smoke_test.py --base-url https://api.example.com
    python3 scripts/production_smoke_test.py --base-url https://api.example.com   # prompts

Credentials come from SMOKE_EMAIL / SMOKE_PASSWORD or an interactive prompt; nothing is
hard-coded and neither the password nor any token is ever printed. Use a dedicated
smoke-test account (``--register`` creates it on the first run).

Checks: /health/ready, /metrics is not public, login, upload policy, upload of a small
TXT file through the upload-only token, processing to ``completed``, keyword search
finds a unique marker, the upload token is refused elsewhere, delete, and 404 afterwards.
``/ask`` is called only with ``--with-llm`` (it costs real LLM tokens); then a 200 answer
or a 503 "not configured" are reported, ``--require-llm`` makes only 200 pass.
"""

import argparse
import getpass
import json
import os
import secrets
import ssl
import sys
import time
import urllib.error
import urllib.request
import uuid
from typing import Any


class Api:
    def __init__(self, base_url: str, cafile: str | None, timeout: float) -> None:
        self.base_url = base_url.rstrip("/")
        self.context = ssl.create_default_context(cafile=cafile)
        self.timeout = timeout

    def request(
        self,
        method: str,
        path: str,
        *,
        token: str | None = None,
        body: Any = None,
        raw: bytes | None = None,
        content_type: str | None = None,
    ) -> tuple[int, Any]:
        headers = {"Accept": "application/json"}
        data = raw
        if body is not None:
            data = json.dumps(body).encode()
            headers["Content-Type"] = "application/json"
        if content_type:
            headers["Content-Type"] = content_type
        if token:
            headers["Authorization"] = f"Bearer {token}"
        req = urllib.request.Request(  # noqa: S310 (URL is the operator's own API)
            f"{self.base_url}{path}", data=data, method=method, headers=headers
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout, context=self.context) as resp:  # noqa: S310
                text = resp.read().decode() or "null"
                return resp.status, json.loads(text) if text.strip()[:1] in "{[n" else text
        except urllib.error.HTTPError as exc:
            text = exc.read().decode() or "null"
            try:
                return exc.code, json.loads(text)
            except json.JSONDecodeError:
                return exc.code, None


FAILURES: list[str] = []


def check(ok: bool, label: str) -> bool:
    print(f"  [{'PASS' if ok else 'FAIL'}] {label}")
    if not ok:
        FAILURES.append(label)
    return ok


def multipart(filename: str, content: bytes, content_type: str) -> tuple[bytes, str]:
    boundary = uuid.uuid4().hex
    head = (
        f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="{filename}"\r\n'
        f"Content-Type: {content_type}\r\n\r\n"
    ).encode()
    return (
        head + content + f"\r\n--{boundary}--\r\n".encode(),
        f"multipart/form-data; boundary={boundary}",
    )


def main() -> int:  # noqa: PLR0915 (one linear scenario)
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument(
        "--base-url", required=True, help="public API URL, e.g. https://api.example.com"
    )
    parser.add_argument("--cacert", help="CA bundle (e.g. a local test CA); default: system store")
    parser.add_argument(
        "--register", action="store_true", help="create the account if it is missing"
    )
    parser.add_argument(
        "--with-llm", action="store_true", help="also call /ask (uses real LLM tokens)"
    )
    parser.add_argument(
        "--require-llm", action="store_true", help="with --with-llm: only a 200 answer passes"
    )
    parser.add_argument("--timeout", type=float, default=30.0)
    parser.add_argument("--processing-timeout", type=float, default=300.0)
    args = parser.parse_args()

    email = os.environ.get("SMOKE_EMAIL") or input("Smoke-test account e-mail: ").strip()
    password = os.environ.get("SMOKE_PASSWORD") or getpass.getpass("Password: ")
    api = Api(args.base_url, args.cacert, args.timeout)
    print(f"Smoke test against {api.base_url}")

    status, body = api.request("GET", "/health/ready")
    check(
        status == 200 and isinstance(body, dict) and body.get("status") == "ready",
        "GET /health/ready is ok",
    )
    status, _ = api.request("GET", "/metrics")
    check(status == 404, f"/metrics is not public (HTTP {status})")

    if args.register:
        status, _ = api.request(
            "POST", "/auth/register", body={"email": email, "password": password}
        )
        check(status in (201, 409), f"register (HTTP {status}; 409 = already exists)")
    status, body = api.request("POST", "/auth/login", body={"email": email, "password": password})
    if not check(
        status == 200 and isinstance(body, dict) and "access_token" in body,
        f"login (HTTP {status})",
    ):
        return 1
    token = body["access_token"]

    status, policy = api.request("GET", "/documents/upload-policy", token=token)
    check(
        status == 200 and "txt" in policy.get("allowed_extensions", []), "upload policy allows TXT"
    )

    status, body = api.request("POST", "/auth/upload-token", token=token)
    if not check(status == 200 and "upload_token" in body, "upload-only token issued"):
        return 1
    upload_token = body["upload_token"]
    status, _ = api.request("GET", "/documents", token=upload_token)
    check(status == 401, "upload token is refused outside POST /documents")

    marker = f"smoke{secrets.token_hex(6)}"
    content = (
        f"Production smoke test document.\nThe verification marker is {marker}.\n"
        "Customers may return unused items within 30 days of delivery.\n"
    ).encode()
    data, ctype = multipart(f"{marker}.txt", content, "text/plain")
    status, body = api.request(
        "POST", "/documents", token=upload_token, raw=data, content_type=ctype
    )
    if not check(status in (201, 202) and "id" in body, f"upload accepted (HTTP {status})"):
        return 1
    doc_id = body["id"]

    deadline = time.monotonic() + args.processing_timeout
    state = "queued"
    while time.monotonic() < deadline:
        status, body = api.request("GET", f"/documents/{doc_id}/status", token=token)
        state = body.get("status", "?") if isinstance(body, dict) else "?"
        if state in ("completed", "failed"):
            break
        time.sleep(2)
    check(state == "completed", f"processing finished: {state}")

    status, body = api.request(
        "POST", "/search", token=token, body={"query": marker, "mode": "keyword"}
    )
    hits = body.get("results", []) if isinstance(body, dict) else []
    check(
        status == 200 and any(marker in r.get("text", "") for r in hits),
        "keyword search finds the marker",
    )

    if args.with_llm:
        status, body = api.request(
            "POST",
            "/ask",
            token=token,
            body={
                "question": "How many days do customers have to return unused items?",
                "document_id": doc_id,
            },
        )
        if status == 200:
            check(
                bool(body.get("citations")) or body.get("insufficient_evidence"),
                "ask answered (200)",
            )
            print(f"    citations: {len(body.get('citations', []))}, model: {body.get('model')}")
        else:
            message = (
                (body or {}).get("error", {}).get("message", "") if isinstance(body, dict) else ""
            )
            check(not args.require_llm and status == 503, f"ask -> HTTP {status} {message}".strip())

    status, _ = api.request("DELETE", f"/documents/{doc_id}", token=token)
    check(status == 204, f"delete (HTTP {status})")
    status, _ = api.request("GET", f"/documents/{doc_id}", token=token)
    check(status == 404, "deleted document is gone (404)")

    print("RESULT:", "PASS" if not FAILURES else f"FAIL ({len(FAILURES)} check(s))")
    return 0 if not FAILURES else 1


if __name__ == "__main__":
    sys.exit(main())
