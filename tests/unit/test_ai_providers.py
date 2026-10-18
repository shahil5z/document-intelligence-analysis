"""AI provider factory and adapters, verified without network access or a real key."""

import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from app.ai import AIProviderConfigurationError, get_embedding_provider, get_llm_provider
from app.ai.factory import build_openai_client
from app.ai.openai_provider import OpenAIChatProvider, OpenAIEmbeddingProvider
from app.core.config import Settings, load_settings

FAKE_KEY = "fake-openai-key-for-tests-only"
PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _settings(**overrides: Any) -> Settings:
    return load_settings(_env_file=None, app_env="test", jwt_secret_key="k" * 40, **overrides)


@pytest.mark.parametrize("key", [None, "", "replace-with-your-openai-api-key"])
def test_missing_or_placeholder_key_raises_clear_error(
    monkeypatch: pytest.MonkeyPatch, key: str | None
) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    settings = _settings(openai_api_key=key)
    for factory in (get_llm_provider, get_embedding_provider):
        with pytest.raises(AIProviderConfigurationError, match="OPENAI_API_KEY is not configured"):
            factory(settings)


def test_factory_builds_client_from_settings_without_network() -> None:
    settings = _settings(openai_api_key=FAKE_KEY, openai_timeout_seconds=12.5)
    client = build_openai_client(settings)
    assert client.api_key == FAKE_KEY
    assert client.timeout == 12.5
    assert isinstance(get_llm_provider(settings), OpenAIChatProvider)
    assert isinstance(get_embedding_provider(settings), OpenAIEmbeddingProvider)


class _FakeClient:
    """Duck-typed stand-in for openai.OpenAI recording the requests it receives."""

    def __init__(self) -> None:
        self.requests: list[dict[str, Any]] = []
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._chat))
        self.embeddings = SimpleNamespace(create=self._embed)

    def _chat(self, **kwargs: Any) -> Any:
        self.requests.append(kwargs)
        message = SimpleNamespace(content="fake answer")
        return SimpleNamespace(choices=[SimpleNamespace(message=message)])

    def _embed(self, **kwargs: Any) -> Any:
        self.requests.append(kwargs)
        data = [
            SimpleNamespace(index=i, embedding=[float(i), 0.5]) for i in range(len(kwargs["input"]))
        ]
        return SimpleNamespace(data=list(reversed(data)))


def test_chat_provider_maps_messages() -> None:
    client = _FakeClient()
    provider = OpenAIChatProvider(client, "chat-model")  # type: ignore[arg-type]
    answer = provider.complete(
        [{"role": "system", "content": "be brief"}, {"role": "user", "content": "hi"}]
    )
    assert answer == "fake answer"
    assert client.requests == [
        {
            "model": "chat-model",
            "messages": [
                {"role": "system", "content": "be brief"},
                {"role": "user", "content": "hi"},
            ],
        }
    ]


def test_embedding_provider_preserves_input_order() -> None:
    client = _FakeClient()
    provider = OpenAIEmbeddingProvider(client, "embed-model")  # type: ignore[arg-type]
    assert provider.embed(["a", "b", "c"]) == [[0.0, 0.5], [1.0, 0.5], [2.0, 0.5]]
    assert provider.embed([]) == []
    assert client.requests == [{"model": "embed-model", "input": ["a", "b", "c"]}]


def test_app_and_worker_start_without_importing_openai() -> None:
    code = "import sys, app.main, app.workers.tasks; print('openai' in sys.modules)"
    result = subprocess.run(  # noqa: S603  (fixed interpreter and arguments)
        [sys.executable, "-c", code],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    assert result.stdout.strip() == "False"
