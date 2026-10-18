"""Logging and metrics details that are easy to regress."""

import json
import logging
from typing import Any

import httpx2
import pytest

from app.ai.llm import OpenAICompatibleLLMProvider
from app.core.logging import JsonFormatter
from app.core.metrics import UNMATCHED_ROUTE, build_registry, status_label
from app.core.middleware import route_template
from app.db.repositories.chunks import parse_extension_version, supports_iterative_scan

KEY = "sk-test-key-that-must-never-be-logged"


def test_llm_usage_numbers_survive_log_redaction(caplog: pytest.LogCaptureFixture) -> None:
    def handler(request: httpx2.Request) -> httpx2.Response:
        del request
        return httpx2.Response(
            200,
            json={
                "choices": [{"message": {"content": "ok [S1]"}}],
                "usage": {"prompt_tokens": 120, "completion_tokens": 7},
            },
        )

    provider = OpenAICompatibleLLMProvider(
        api_key=KEY,
        model="m",
        base_url="https://llm.example.test/v1",
        timeout_seconds=5,
        max_output_tokens=50,
        temperature=0.0,
        transport=httpx2.MockTransport(handler),
    )
    with caplog.at_level(logging.INFO, logger="app.ai.llm"):
        assert provider.complete([{"role": "user", "content": "hi"}]) == "ok [S1]"
    provider.close()
    record = next(r for r in caplog.records if r.getMessage() == "llm.completed")
    payload = json.loads(JsonFormatter().format(record))
    assert payload["usage_prompt"] == 120
    assert payload["usage_completion"] == 7
    assert KEY not in json.dumps(payload)


def test_json_formatter_still_redacts_sensitive_keys() -> None:
    record = logging.LogRecord("t", logging.INFO, __file__, 1, "evt", None, None)
    record.__dict__.update({"password": "p", "access_token": "t", "nested": {"secret": "s"}})
    payload = json.loads(JsonFormatter().format(record))
    assert payload["password"] == "[REDACTED]"
    assert payload["access_token"] == "[REDACTED]"
    assert payload["nested"] == {"secret": "[REDACTED]"}


def test_route_template_falls_back_to_unmatched() -> None:
    class _Route:
        path = "/documents/{document_id}"

    scope: dict[str, Any] = {"route": _Route()}
    assert route_template(scope) == "/documents/{document_id}"
    assert route_template({}) == UNMATCHED_ROUTE


def test_status_label_is_bounded() -> None:
    assert status_label(404) == "404"
    assert status_label(999) == "invalid"


def test_registry_uses_multiprocess_collector_when_configured(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Any
) -> None:
    from prometheus_client import REGISTRY  # noqa: PLC0415

    assert build_registry() is REGISTRY
    monkeypatch.setenv("PROMETHEUS_MULTIPROC_DIR", str(tmp_path))
    assert build_registry() is not REGISTRY


@pytest.mark.parametrize(
    ("version", "parsed", "supported"),
    [
        ("0.8.0", (0, 8, 0), True),
        ("0.8.1", (0, 8, 1), True),
        ("1.0", (1, 0), True),
        ("0.7.4", (0, 7, 4), False),
        ("0.6.2", (0, 6, 2), False),
        (None, (), False),
        ("", (), False),
    ],
)
def test_pgvector_iterative_scan_detection(
    version: str | None, parsed: tuple[int, ...], supported: bool
) -> None:
    assert parse_extension_version(version) == parsed
    assert supports_iterative_scan(version) is supported
