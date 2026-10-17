"""End-to-end smoke test against a running stack (API + worker + Postgres + Redis).

Usage:  python scripts/smoke_test.py [--base-url http://localhost:8000]

Uses only the standard library. Registers a throwaway user, uploads a generated PDF
and a TXT file, waits for the real worker to finish processing, lists and deletes.
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


def build_pdf(text: str) -> bytes:
    """A minimal but well-formed single-page PDF with a correct xref table."""
    stream = f"BT /F1 18 Tf 72 720 Td ({text}) Tj ET".encode()
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


def wait_for_terminal(client: Client, document_id: str, timeout: float = 30.0) -> Any:
    deadline = time.monotonic() + timeout
    seen: list[str] = []
    while time.monotonic() < deadline:
        _, _, status = client.request("GET", f"/documents/{document_id}/status")
        if not seen or seen[-1] != status["status"]:
            seen.append(status["status"])
        if status["status"] in {"completed", "failed"}:
            print(f"     observed statuses: {' -> '.join(seen)}")
            return status
        time.sleep(0.25)
    raise SystemExit(f"FAIL document {document_id} did not finish within {timeout}s")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://localhost:8000")
    args = parser.parse_args()
    client = Client(args.base_url)

    status, headers, body = client.request("GET", "/health")
    check(status == 200 and "x-request-id" in headers, f"GET /health -> {status}")
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

    documents = []
    for filename, content, mime in [
        ("smoke.pdf", build_pdf(f"Smoke test {uuid.uuid4()}"), "application/pdf"),
        ("smoke.txt", f"plain text smoke test {uuid.uuid4()}\n".encode(), "text/plain"),
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
            and job["attempts"] == 1,
            f"worker processed {filename}: document={final['status']} job={job['status']}",
        )
        documents.append(body["id"])

    status, body = client.upload("smoke.exe", b"MZ\x90\x00", "application/octet-stream")
    check(status == 415, f"POST /documents smoke.exe -> {status}")

    status, _, body = client.request("GET", "/documents?page=1&page_size=1")
    check(
        status == 200 and body["total"] == 2 and len(body["items"]) == 1,
        f"GET /documents -> total={body['total']}",
    )

    for document_id in documents:
        status, _, _ = client.request("DELETE", f"/documents/{document_id}")
        check(status == 204, f"DELETE /documents/{document_id} -> {status}")
        status, _, _ = client.request("GET", f"/documents/{document_id}")
        check(status == 404, f"GET deleted document -> {status}")

    status, _, body = client.request("GET", "/audit-logs/me")
    actions = sorted({item["action"] for item in body["items"]})
    check(status == 200 and "document.deleted" in actions, f"GET /audit-logs/me -> {actions}")
    print("SMOKE TEST PASSED")


if __name__ == "__main__":
    main()
