"""End-to-end smoke test against a running stack (API + worker + Postgres + Redis).

Usage:  python scripts/smoke_test.py [--base-url http://localhost:8000]

Uses only the standard library. Registers a throwaway user, uploads a generated PDF
and a TXT file, waits for the real worker to extract, chunk, embed and index them, runs
/search in all three modes (including a cross-user isolation check), /ask, reprocessing,
then deletes and checks the document is no longer searchable.

/ask needs a configured LLM (OPENAI_API_KEY). By default both an answer (200) and
"LLM unavailable" (503) are accepted; use --ask-expect answer|unavailable to be strict.
"""

import argparse
import json
import secrets
import sys
import time
import urllib.error
import urllib.request
import uuid
from typing import Any


def build_pdf(*lines: str) -> bytes:
    """A minimal but well-formed single-page PDF with a correct xref table."""
    text_ops = " ".join(f"({line}) Tj T*" for line in lines)
    stream = f"BT /F1 12 Tf 16 TL 72 720 Td {text_ops} ET".encode()
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
        b"/Resources << /Font << /F1 5 0 R >> >> /Contents 4 0 R >>",
        b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for number, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += b"%d 0 obj\n" % number + body + b"\nendobj\n"
    xref = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objects) + 1)
    out += b"".join(b"%010d 00000 n \n" % offset for offset in offsets)
    out += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (
        len(objects) + 1,
        xref,
    )
    return bytes(out)


class Client:
    def __init__(self, base_url: str) -> None:
        self.base_url = base_url.rstrip("/")
        self.token: str | None = None

    def request(
        self,
        method: str,
        path: str,
        *,
        json_body: Any = None,
        body: bytes | None = None,
        content_type: str | None = None,
    ) -> tuple[int, dict[str, str], Any]:
        headers = {"X-Request-ID": f"smoke-{uuid.uuid4()}"}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        data = body
        if json_body is not None:
            data = json.dumps(json_body).encode()
            headers["Content-Type"] = "application/json"
        elif content_type:
            headers["Content-Type"] = content_type
        req = urllib.request.Request(  # noqa: S310  (URL comes from the operator)
            self.base_url + path, data=data, headers=headers, method=method
        )
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:  # noqa: S310
                raw = resp.read()
                return (
                    resp.status,
                    {k.lower(): v for k, v in resp.headers.items()},
                    json.loads(raw) if raw else None,
                )
        except urllib.error.HTTPError as err:
            raw = err.read()
            return (
                err.code,
                {k.lower(): v for k, v in err.headers.items()},
                json.loads(raw) if raw else None,
            )

    def upload(self, filename: str, content: bytes, mime: str) -> tuple[int, Any]:
        boundary = secrets.token_hex(16)
        body = (
            (
                f'--{boundary}\r\nContent-Disposition: form-data; name="file"; '
                f'filename="{filename}"\r\nContent-Type: {mime}\r\n\r\n'
            ).encode()
            + content
            + f"\r\n--{boundary}--\r\n".encode()
        )
        status, _, payload = self.request(
            "POST",
            "/documents",
            body=body,
            content_type=f"multipart/form-data; boundary={boundary}",
        )
        return status, payload


def check(condition: bool, message: str) -> None:
    print(("PASS " if condition else "FAIL ") + message)
    if not condition:
        sys.exit(1)


# The first document may wait for the embedding model download (~130 MB).
def wait_for_terminal(client: Client, document_id: str, timeout: float = 300.0) -> Any:
    deadline = time.monotonic() + timeout
    seen: list[str] = []
    while time.monotonic() < deadline:
        _, _, status = client.request("GET", f"/documents/{document_id}/status")
        if not seen or seen[-1] != status["status"]:
            seen.append(status["status"])
        if status["status"] in {"completed", "failed"}:
            print(f"     observed statuses: {' -> '.join(seen)}")
            return status
        time.sleep(0.5)
    raise SystemExit(f"FAIL document {document_id} did not finish within {timeout}s")


def main() -> None:  # noqa: PLR0915  (one linear end-to-end scenario)
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://localhost:8000")
    parser.add_argument("--ask-expect", choices=["any", "answer", "unavailable"], default="any")
    args = parser.parse_args()
    client = Client(args.base_url)

    status, headers, body = client.request("GET", "/health")
    check(status == 200 and "x-request-id" in headers, f"GET /health -> {status}")
    status, _, body = client.request("GET", "/health/live")
    check(status == 200 and body == {"status": "ok"}, f"GET /health/live -> {status}")
    status, _, body = client.request("GET", "/health/ready")
    check(status == 200 and body["status"] == "ready", f"GET /health/ready -> {status} {body}")

    email = f"smoke-{uuid.uuid4().hex[:8]}@example.com"
    password = secrets.token_urlsafe(18)
    status, _, body = client.request(
        "POST", "/auth/register", json_body={"email": email, "password": password}
    )
    check(status == 201 and body["role"] == "user", f"POST /auth/register -> {status}")
    status, _, body = client.request(
        "POST", "/auth/login", json_body={"email": email, "password": password}
    )
    check(status == 200 and "access_token" in body, f"POST /auth/login -> {status}")
    client.token = body["access_token"]
    status, _, body = client.request("GET", "/auth/me")
    check(status == 200 and body["email"] == email, f"GET /auth/me -> {status}")

    marker = uuid.uuid4().hex[:8]
    pdf = build_pdf(
        "Northwind refund policy.",
        "Customers may return unused items within 30 days of delivery for a full refund.",
        "Refunds are issued to the original payment method within 7 business days.",
        f"Reference code {marker}.",
    )
    documents = []
    for filename, content, mime in [
        ("smoke.pdf", pdf, "application/pdf"),
        (
            "smoke.txt",
            f"Cafeteria notice {uuid.uuid4()}. Lunch is served at noon on weekdays.\n".encode(),
            "text/plain",
        ),
    ]:
        status, body = client.upload(filename, content, mime)
        check(
            status == 201 and body["status"] == "queued",
            f"POST /documents {filename} -> {status} {body}",
        )
        final = wait_for_terminal(client, body["id"])
        job = final["job"]
        check(
            final["status"] == "completed"
            and job["status"] == "completed"
            and job["attempts"] == 1
            and job["stage"] == "index"
            and final["chunk_count"] >= 1,
            f"worker processed {filename}: document={final['status']} job={job['status']} "
            f"stage={job['stage']} chunks={final['chunk_count']}",
        )
        documents.append(body["id"])

    for mode, query in (
        ("semantic", "How long do I have to send something back?"),
        ("keyword", marker),
        ("hybrid", "refund window in days"),
    ):
        status, _, body = client.request(
            "POST", "/search", json_body={"query": query, "mode": mode, "top_k": 3}
        )
        top = body["results"][0] if status == 200 and body["results"] else {}
        check(
            status == 200
            and top.get("document_id") == documents[0]
            and top.get("page_start") == 1
            and "embedding" not in top,
            f"POST /search mode={mode} -> {status}, top={top.get('filename')} "
            f"score={top.get('score')}",
        )

    status, _, body = client.request(
        "POST", "/ask", json_body={"question": "How many days do customers have to return items?"}
    )
    if status == 200:
        cited = {c["document_id"] for c in body["citations"]}
        ok = (not body["insufficient_evidence"]) and cited <= set(documents) and bool(cited)
        check(
            ok and args.ask_expect != "unavailable",
            f"POST /ask -> 200 model={body['model']} citations={len(body['citations'])} "
            f"answer={body['answer'][:120]!r}",
        )
    else:
        check(
            status == 503 and args.ask_expect != "answer",
            f"POST /ask -> {status} {body['error']['message'] if body else ''}",
        )
    status, _, body = client.request(
        "POST", "/ask", json_body={"question": "What is the boiling point of mercury?"}
    )
    check(
        status == 200 and body["insufficient_evidence"] is True and body["model"] is None,
        f"POST /ask off-topic -> {status} insufficient={body.get('insufficient_evidence')}",
    )

    status, body = client.upload("smoke.exe", b"MZ\x90\x00", "application/octet-stream")
    check(status == 415, f"POST /documents smoke.exe -> {status}")

    status, _, body = client.request("GET", "/documents?page=1&page_size=1")
    check(
        status == 200 and body["total"] == 2 and len(body["items"]) == 1,
        f"GET /documents -> total={body['total']}",
    )

    intruder = Client(args.base_url)
    other_email = f"smoke-other-{uuid.uuid4().hex[:8]}@example.com"
    intruder.request(
        "POST", "/auth/register", json_body={"email": other_email, "password": password}
    )
    _, _, body = intruder.request(
        "POST", "/auth/login", json_body={"email": other_email, "password": password}
    )
    intruder.token = body["access_token"]
    for path in (f"/documents/{documents[0]}", f"/documents/{documents[0]}/status"):
        status, _, _ = intruder.request("GET", path)
        check(status == 404, f"other user GET {path} -> {status}")
    status, _, _ = intruder.request("DELETE", f"/documents/{documents[0]}")
    check(status == 404, f"other user DELETE /documents/{documents[0]} -> {status}")
    status, _, body = intruder.request("GET", "/documents")
    check(
        status == 200 and body["total"] == 0, f"other user GET /documents -> total={body['total']}"
    )
    for mode in ("semantic", "keyword", "hybrid"):
        status, _, body = intruder.request(
            "POST", "/search", json_body={"query": f"refund {marker}", "mode": mode}
        )
        check(
            status == 200 and body["results"] == [],
            f"other user POST /search mode={mode} -> {len(body['results'])} results",
        )
    status, _, body = intruder.request(
        "POST", "/search", json_body={"query": "refund", "document_id": documents[0]}
    )
    check(status == 404, f"other user POST /search document_id=<foreign> -> {status}")

    status, _, body = client.request("POST", f"/documents/{documents[1]}/reprocess")
    check(status == 202 and body["status"] == "queued", f"POST reprocess -> {status}")
    final = wait_for_terminal(client, documents[1])
    check(final["status"] == "completed", f"reprocessed document -> {final['status']}")

    for document_id in documents:
        status, _, _ = client.request("DELETE", f"/documents/{document_id}")
        check(status == 204, f"DELETE /documents/{document_id} -> {status}")
        status, _, _ = client.request("GET", f"/documents/{document_id}")
        check(status == 404, f"GET deleted document -> {status}")
    status, _, body = client.request(
        "POST", "/search", json_body={"query": f"refund {marker}", "mode": "hybrid"}
    )
    check(
        status == 200 and body["results"] == [],
        f"POST /search after delete -> {len(body['results'])} results",
    )

    status, _, body = client.request("GET", "/audit-logs/me")
    actions = sorted({item["action"] for item in body["items"]})
    check(status == 200 and "document.deleted" in actions, f"GET /audit-logs/me -> {actions}")
    print("SMOKE TEST PASSED")


if __name__ == "__main__":
    main()
