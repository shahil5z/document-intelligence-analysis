"""One-command check that /ask answers with citations against the REAL configured LLM.

Usage (with the stack running and OPENAI_API_KEY set in .env):

    python scripts/check_ask_real.py                       # generated sample PDF
    python scripts/check_ask_real.py --pdf my.pdf -q "What does section 3 say?"

Registers a throwaway user, uploads the PDF, waits for indexing, then asks a
document-level question, a specific question (or your ``-q`` questions) and one
off-topic question. For each it prints the outcome (answered / partial /
insufficient), the insufficient reason (below_threshold, model_declined,
parse_failed, no_valid_citations), citation numbers, best retrieval context size and
the prompt version, plus the first characters of the answer. Exit code 1 when an
on-topic question was not answered with at least one valid citation.

This sends a handful of short requests (a few thousand tokens in total) to the paid
LLM configured in the API's environment. Standard library only.
"""

import argparse
import re
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from smoke_test import (  # type: ignore[import-not-found]
    Client,
    build_pdf,
    wait_for_terminal,
)

SAMPLE_LINES = (
    "Northwind Traders customer service policy, version 2026.",
    "Customers may return unused items within 30 days of delivery for a full refund.",
    "Refunds are issued to the original payment method within 7 business days.",
    "Damaged goods must be reported within 48 hours together with a photo.",
    "Support is available Monday to Friday from 9:00 to 17:00 CET by e-mail.",
    "Gift cards are not refundable and do not expire.",
)
DEFAULT_QUESTIONS = (
    "What is this document about?",
    "How many days do customers have to return items, and how are refunds paid?",
)
OFF_TOPIC = "What is the boiling point of mercury?"


def outcome(body: dict[str, object]) -> str:
    if body.get("insufficient_evidence"):
        return "insufficient"
    return "partial" if body.get("partial") else "answered"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--base-url", default="http://localhost:8000")
    parser.add_argument("--pdf", type=Path, help="PDF to upload (default: generated sample)")
    parser.add_argument("-q", "--question", action="append", help="on-topic question (repeat)")
    parser.add_argument("--answer-chars", type=int, default=160, help="answer preview length")
    args = parser.parse_args()

    client = Client(args.base_url)
    email = f"askcheck-{uuid.uuid4().hex[:8]}@example.com"
    password = uuid.uuid4().hex + "Aa1!"
    status, _, body = client.request(
        "POST", "/auth/register", json_body={"email": email, "password": password}
    )
    if status != 201:
        print(f"FAIL register -> {status} {body}")
        return 1
    status, _, body = client.request(
        "POST", "/auth/login", json_body={"email": email, "password": password}
    )
    if status != 200:
        print(f"FAIL login -> {status}")
        return 1
    client.token = body["access_token"]

    content = args.pdf.read_bytes() if args.pdf else build_pdf(*SAMPLE_LINES)
    status, body = client.upload(
        args.pdf.name if args.pdf else "ask-check.pdf", content, "application/pdf"
    )
    if status != 201:
        print(f"FAIL upload -> {status} {body}")
        return 1
    final = wait_for_terminal(client, body["id"])
    if final["status"] != "completed":
        print(f"FAIL document processing -> {final['status']}")
        return 1
    print(f"indexed: chunks={final['chunk_count']}")

    failures = 0
    questions = [(q, True) for q in (args.question or DEFAULT_QUESTIONS)] + [(OFF_TOPIC, False)]
    for question, on_topic in questions:
        status, _, body = client.request("POST", "/ask", json_body={"question": question})
        if status != 200:
            message = body["error"]["message"] if body and "error" in body else body
            print(f"FAIL /ask -> {status} {message}")
            failures += 1
            continue
        markers = sorted({int(n) for n in re.findall(r"\[(\d+)\]", body["answer"])})
        numbers = [c["number"] for c in body["citations"]]
        result = outcome(body)
        ok = (result != "insufficient" and bool(numbers)) if on_topic else True
        failures += 0 if ok else 1
        print(
            f"{'PASS' if ok else 'FAIL'} {'on-topic ' if on_topic else 'off-topic'} "
            f"outcome={result} reason={body.get('insufficient_reason')} "
            f"citations={numbers} markers={markers} sources={body['sources_considered']} "
            f"model={body['model']} prompt={body.get('prompt_version')} "
            f"warnings={body['warnings']}"
        )
        print(f"     q: {question}")
        print(f"     a: {body['answer'][: args.answer_chars]!r}")
    print("RESULT", "PASS" if failures == 0 else f"FAIL ({failures})")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
