"""Embedding helpers and providers without downloading models."""

import math
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from app.ai.embeddings import SentenceTransformerEmbeddingProvider, embed_in_batches
from app.ai.errors import AIProviderConfigurationError, EmbeddingError
from app.ai.factory import create_embedding_provider
from app.core.config import load_settings
from tests.fakes import HashingEmbeddingProvider

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def test_fake_provider_is_deterministic_normalised_and_sized() -> None:
    provider = HashingEmbeddingProvider()
    first, second = provider.embed(["refund window policy", "refund window policy"])
    assert first == second
    assert len(first) == provider.dimension == 384
    assert math.isclose(sum(v * v for v in first), 1.0, rel_tol=1e-9)


def _dot(a: list[float], b: list[float]) -> float:
    return sum(x * y for x, y in zip(a, b, strict=True))


def test_fake_provider_similarity_reflects_shared_words() -> None:
    provider = HashingEmbeddingProvider()
    query = provider.embed_query("refund window")
    related, unrelated = provider.embed(["the refund window is 30 days", "lunch at noon"])
    assert _dot(query, related) > 0.4
    assert _dot(query, unrelated) < 0.1


@pytest.mark.parametrize(("count", "batch", "expected"), [(10, 4, [4, 4, 2]), (3, 32, [3])])
def test_embed_in_batches(count: int, batch: int, expected: list[int]) -> None:
    provider = HashingEmbeddingProvider()
    vectors = embed_in_batches(provider, [f"text {i}" for i in range(count)], batch)
    assert len(vectors) == count
    assert provider.calls == expected


def test_embed_in_batches_validates_dimension_and_count() -> None:
    class _Wrong:
        model_name = "wrong"
        dimension = 384

        def __init__(self, size: int, drop: bool = False) -> None:
            self.size, self.drop = size, drop

        def embed(self, texts: list[str]) -> list[list[float]]:
            vectors = [[0.0] * self.size for _ in texts]
            return vectors[1:] if self.drop else vectors

        def embed_query(self, text: str) -> list[float]:
            return self.embed([text])[0]

    with pytest.raises(EmbeddingError, match="wrong size"):
        embed_in_batches(_Wrong(10), ["a"], 8)
    with pytest.raises(EmbeddingError, match="wrong number"):
        embed_in_batches(_Wrong(384, drop=True), ["a", "b"], 8)
    with pytest.raises(ValueError, match="batch_size"):
        embed_in_batches(HashingEmbeddingProvider(), ["a"], 0)


def test_embedding_failure_is_raised() -> None:
    with pytest.raises(EmbeddingError):
        embed_in_batches(HashingEmbeddingProvider(fail=True), ["a"], 8)


class _FakeSentenceTransformer:
    def __init__(self, dimension: int) -> None:
        self._dimension = dimension
        self.max_seq_length = 512
        self.encoded: list[list[str]] = []
        self.tokenizer = lambda text, **_: {"input_ids": text.split()}

    def get_embedding_dimension(self) -> int:
        return self._dimension

    def encode(self, texts: list[str], **kwargs: Any) -> Any:
        self.encoded.append(texts)
        assert kwargs["normalize_embeddings"] is True
        rows = [[1.0] + [0.0] * (self._dimension - 1) for _ in texts]
        return SimpleNamespace(tolist=lambda: rows)


def _provider_with(model: _FakeSentenceTransformer) -> SentenceTransformerEmbeddingProvider:
    provider = SentenceTransformerEmbeddingProvider(
        "fake-model", expected_dimension=384, batch_size=8, query_instruction="query: "
    )
    provider._model = model  # type: ignore[assignment]  # noqa: SLF001
    return provider


def test_sentence_transformer_provider_uses_query_instruction() -> None:
    model = _FakeSentenceTransformer(384)
    provider = _provider_with(model)
    assert len(provider.embed_query("refunds")) == 384
    assert provider.embed(["doc one", "doc two"])[1][0] == 1.0
    assert provider.embed([]) == []
    assert model.encoded == [["query: refunds"], ["doc one", "doc two"]]
    assert provider.count_tokens("three word text") == 3


def test_dimension_mismatch_is_a_configuration_error(monkeypatch: pytest.MonkeyPatch) -> None:
    import sentence_transformers  # noqa: PLC0415

    monkeypatch.setattr(
        sentence_transformers,
        "SentenceTransformer",
        lambda *_args, **_kwargs: _FakeSentenceTransformer(768),
    )
    provider = SentenceTransformerEmbeddingProvider("fake", expected_dimension=384)
    with pytest.raises(AIProviderConfigurationError, match="768-dimensional"):
        provider.embed(["text"])


def test_torch_threads_are_applied_before_the_model_loads(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import sentence_transformers  # noqa: PLC0415
    import torch  # noqa: PLC0415

    calls: list[int] = []
    monkeypatch.setattr(torch, "get_num_threads", lambda: 8)
    monkeypatch.setattr(torch, "set_num_threads", calls.append)

    def fake_model(*_args: Any, **_kwargs: Any) -> _FakeSentenceTransformer:
        assert calls == [2], "threads must be capped before the model is built"
        return _FakeSentenceTransformer(384)

    monkeypatch.setattr(sentence_transformers, "SentenceTransformer", fake_model)
    provider = SentenceTransformerEmbeddingProvider("fake", expected_dimension=384, num_threads=2)
    provider.embed(["text"])
    assert calls == [2]

    calls.clear()
    untouched = SentenceTransformerEmbeddingProvider("fake", expected_dimension=384)
    monkeypatch.setattr(
        sentence_transformers,
        "SentenceTransformer",
        lambda *_a, **_k: _FakeSentenceTransformer(384),
    )
    untouched.embed(["text"])
    assert calls == [], "TORCH_NUM_THREADS=0 keeps torch's default"


def test_factory_returns_cached_lazy_provider() -> None:
    settings = load_settings(_env_file=None, app_env="test", jwt_secret_key="k" * 40)
    first = create_embedding_provider(settings)
    assert first is create_embedding_provider(settings)
    assert first.model_name == "BAAI/bge-small-en-v1.5"
    assert first.dimension == 384
    assert first._model is None  # noqa: SLF001  (nothing loaded until first use)


def test_app_and_worker_start_without_importing_torch() -> None:
    code = (
        "import sys, app.main, app.workers.tasks; "
        "print(any(m in sys.modules for m in ('torch', 'sentence_transformers', 'pypdf')))"
    )
    result = subprocess.run(  # noqa: S603  (fixed interpreter and arguments)
        [sys.executable, "-c", code],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    assert result.stdout.strip() == "False"
