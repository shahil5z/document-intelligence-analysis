"""HTTP LLM client against httpx2.MockTransport (no network)."""

import json
import logging
from typing import Any

import httpx2
import pytest

from app.ai.errors import AIProviderConfigurationError, LLMError
from app.ai.factory import create_llm_provider
from app.ai.llm import OpenAICompatibleLLMProvider
from app.core.config import load_settings

KEY = "sk-test-key-that-must-never-be-logged"


def _provider(handler: Any) -> OpenAICompatibleLLMProvider:
    return OpenAICompatibleLLMProvider(
        api_key=KEY,
        model="test-model",
        base_url="https://llm.example.test/v1/",
        timeout_seconds=5,
        max_output_tokens=100,
        temperature=0.0,
        transport=httpx2.MockTransport(handler),
    )


def test_successful_completion_sends_expected_request() -> None:
    seen: list[httpx2.Request] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        seen.append(request)
        return httpx2.Response(
            200,
            json={"choices": [{"message": {"content": "answer [S1]"}}], "usage": {}},
        )

    provider = _provider(handler)
    result = provider.complete([{"role": "user", "content": "hi"}])
    assert result == "answer [S1]"
    request = seen[0]
    assert str(request.url) == "https://llm.example.test/v1/chat/completions"
    assert request.headers["authorization"] == f"Bearer {KEY}"
    body = json.loads(request.content)
    assert body["model"] == "test-model"
    assert body["messages"] == [{"role": "user", "content": "hi"}]
    assert body["max_tokens"] == 100


@pytest.mark.parametrize(
    "handler",
    [
        lambda request: (_ for _ in ()).throw(httpx2.ReadTimeout("slow", request=request)),
        lambda request: (_ for _ in ()).throw(httpx2.ConnectError("down", request=request)),
        lambda _request: httpx2.Response(500, json={"error": {"message": KEY}}),
        lambda _request: httpx2.Response(401, json={"error": "bad key"}),
        lambda _request: httpx2.Response(200, json={"unexpected": True}),
        lambda _request: httpx2.Response(200, content=b"not json"),
    ],
    ids=["timeout", "connect", "500", "401", "shape", "not-json"],
)
def test_failures_raise_generic_llm_error(handler: Any, caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.DEBUG)
    with pytest.raises(LLMError) as excinfo:
        _provider(handler).complete([{"role": "user", "content": "secret question"}])
    assert KEY not in str(excinfo.value)
    assert KEY not in caplog.text
    assert "secret question" not in caplog.text


def _settings(**overrides: Any) -> Any:
    return load_settings(_env_file=None, app_env="test", jwt_secret_key="k" * 40, **overrides)


def test_factory_requires_key_and_respects_none(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    with pytest.raises(AIProviderConfigurationError, match="OPENAI_API_KEY"):
        create_llm_provider(_settings())
    with pytest.raises(AIProviderConfigurationError, match="none"):
        create_llm_provider(_settings(openai_api_key="real-looking", llm_provider="none"))
    provider = create_llm_provider(_settings(openai_api_key="real-looking", llm_model="m"))
    assert provider.model_name == "m"


def test_structured_output_is_requested_and_falls_back_once_when_rejected() -> None:
    seen: list[dict[str, Any]] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        body = json.loads(request.content)
        seen.append(body)
        if "response_format" in body:
            return httpx2.Response(400, json={"error": {"message": "response_format unsupported"}})
        return httpx2.Response(200, json={"choices": [{"message": {"content": "plain [1]"}}]})

    provider = _provider(handler)
    schema = {"type": "object", "properties": {}, "required": [], "additionalProperties": False}
    assert provider.complete([{"role": "user", "content": "q"}], json_schema=schema) == "plain [1]"
    assert seen[0]["response_format"]["json_schema"]["schema"] == schema
    assert "response_format" not in seen[1]
    # Later calls skip the unsupported parameter entirely.
    provider.complete([{"role": "user", "content": "q"}], json_schema=schema)
    assert "response_format" not in seen[2]
    assert len(seen) == 3


def test_bad_request_without_structured_output_is_an_error() -> None:
    def handler(request: httpx2.Request) -> httpx2.Response:
        del request
        return httpx2.Response(400, json={"error": {"message": "bad"}})

    with pytest.raises(LLMError, match="rejected"):
        _provider(handler).complete([{"role": "user", "content": "q"}])


def test_null_content_with_refusal_is_an_empty_reply() -> None:
    def handler(request: httpx2.Request) -> httpx2.Response:
        del request
        return httpx2.Response(
            200,
            json={"choices": [{"message": {"content": None, "refusal": "I can't help."}}]},
        )

    assert _provider(handler).complete([{"role": "user", "content": "q"}]) == ""
