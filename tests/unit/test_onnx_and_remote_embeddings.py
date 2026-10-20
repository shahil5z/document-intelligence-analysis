"""ONNX provider, tokenizer counter, remote provider and /internal/embed (no downloads)."""

import io
import json
import math
import sys
import urllib.error
import urllib.request
from collections.abc import Iterator, Sequence
from types import SimpleNamespace
from typing import Any

import numpy as np
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from tokenizers import Tokenizer
from tokenizers.models import WordLevel
from tokenizers.pre_tokenizers import Whitespace

from app.ai import onnx_embeddings
from app.ai.errors import (
    AIProviderConfigurationError,
    EmbeddingError,
    EmbeddingServiceUnavailableError,
)
from app.ai.factory import create_embedding_provider, create_token_counter
from app.ai.onnx_embeddings import OnnxEmbeddingProvider, TokenizerCounter
from app.ai.remote_embeddings import SECRET_HEADER, RemoteEmbeddingProvider
from app.api.dependencies.services import get_embedder
from app.core.config import Settings, SettingsError, get_settings, load_settings
from app.main import create_app
from tests.fakes import HashingEmbeddingProvider

SECRET = "s" * 40
DIM = 4


def _settings(**overrides: Any) -> Settings:
    return load_settings(_env_file=None, app_env="test", jwt_secret_key="k" * 40, **overrides)


def _word_tokenizer() -> Tokenizer:
    words = ["[PAD]", "[UNK]", "[CLS]", "[SEP]", "refund", "window", "is", "30", "days"]
    tokenizer = Tokenizer(WordLevel({w: i for i, w in enumerate(words)}, unk_token="[UNK]"))
    tokenizer.pre_tokenizer = Whitespace()
    return tokenizer


class _FakeSession:
    """Returns hidden states whose CLS row is [len, 1, 0, 0] (unnormalised)."""

    def __init__(self, dimension: int = DIM, inputs: Sequence[str] = ("input_ids",)) -> None:
        self.dimension = dimension
        self.inputs = inputs
        self.feeds: list[dict[str, Any]] = []

    def get_outputs(self) -> list[Any]:
        return [SimpleNamespace(shape=["batch", "seq", self.dimension])]

    def get_inputs(self) -> list[Any]:
        return [SimpleNamespace(name=name) for name in self.inputs]

    def run(self, _outputs: Any, feeds: dict[str, Any]) -> list[Any]:
        self.feeds.append(feeds)
        ids = feeds["input_ids"]
        hidden = np.zeros((ids.shape[0], ids.shape[1], self.dimension), dtype=np.float32)
        hidden[:, 0, 0] = (ids != 0).sum(axis=1)
        hidden[:, 0, 1] = 1.0
        hidden[:, 1:, 2] = 5.0  # non-CLS tokens must be ignored (CLS pooling)
        return [hidden]


@pytest.fixture
def fake_onnx(monkeypatch: pytest.MonkeyPatch) -> _FakeSession:
    session = _FakeSession()
    fake_ort = SimpleNamespace(
        SessionOptions=lambda: SimpleNamespace(intra_op_num_threads=0, inter_op_num_threads=0),
        InferenceSession=lambda *_args, **_kwargs: session,
    )
    monkeypatch.setitem(sys.modules, "onnxruntime", fake_ort)
    monkeypatch.setattr(onnx_embeddings, "load_tokenizer", lambda _name: _word_tokenizer())
    monkeypatch.setattr(onnx_embeddings, "hub_file", lambda _model, filename: f"/cache/{filename}")
    return session


def test_onnx_provider_cls_pooling_normalisation_and_query_prefix(fake_onnx: _FakeSession) -> None:
    provider = OnnxEmbeddingProvider(
        "fake/model", expected_dimension=DIM, batch_size=2, query_instruction="refund "
    )
    loaded_before = provider.loaded
    vectors = provider.embed(["window is", "30 days", "refund"])
    assert (loaded_before, provider.loaded) == (False, True)
    assert len(vectors) == 3
    assert len(fake_onnx.feeds) == 2  # batches of 2
    for vector in vectors:
        assert len(vector) == DIM
        assert math.isclose(sum(v * v for v in vector), 1.0, rel_tol=1e-6)
        assert vector[2] == 0.0  # only the CLS row is pooled
    # 2 tokens -> [2, 1] normalised; padding does not count.
    assert vectors[0][0] == pytest.approx(2 / math.sqrt(5))
    # The query prefix ("refund ") adds one token.
    assert provider.embed_query("window")[0] == pytest.approx(2 / math.sqrt(5))
    assert set(fake_onnx.feeds[0]) == {"input_ids"}  # only inputs the model declares
    assert provider.embed([]) == []
    assert provider.count_tokens("refund window is 30 days") == 5


def test_onnx_dimension_mismatch_is_a_configuration_error(
    fake_onnx: _FakeSession,
) -> None:
    fake_onnx.dimension = 768
    provider = OnnxEmbeddingProvider("fake/model", expected_dimension=384)
    with pytest.raises(AIProviderConfigurationError, match="768-dimensional"):
        provider.embed(["text"])


def test_onnx_inference_failure_is_an_embedding_error(
    fake_onnx: _FakeSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    def boom(*_args: Any) -> None:
        raise RuntimeError("bad input")

    monkeypatch.setattr(fake_onnx, "run", boom)
    provider = OnnxEmbeddingProvider("fake/model", expected_dimension=DIM, num_threads=1)
    with pytest.raises(EmbeddingError, match="inference failed"):
        provider.embed(["text"])


def test_tokenizer_counter_counts_without_special_tokens_or_truncation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tokenizer = _word_tokenizer()
    tokenizer.enable_truncation(max_length=2)
    monkeypatch.setattr(onnx_embeddings, "load_tokenizer", lambda _name: tokenizer)
    counter = TokenizerCounter("fake/model")
    assert counter.count_tokens("refund window is 30 days") == 5
    assert counter.count_tokens("") == 0


def test_hub_file_errors_are_configuration_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    import huggingface_hub  # noqa: PLC0415

    def offline(**_kwargs: Any) -> str:
        raise OSError("offline and not cached")

    monkeypatch.setattr(huggingface_hub, "hf_hub_download", offline)
    with pytest.raises(AIProviderConfigurationError, match=r"tokenizer\.json"):
        onnx_embeddings.hub_file("fake/model", "tokenizer.json")


# --- remote provider -------------------------------------------------------------------


class _Response(io.BytesIO):
    def __enter__(self) -> "_Response":
        return self

    def __exit__(self, *_args: object) -> None:
        self.close()


def _install_urlopen(monkeypatch: pytest.MonkeyPatch, replies: list[Any]) -> list[Any]:
    requests: list[Any] = []

    def fake_urlopen(request: Any, timeout: float) -> _Response:
        requests.append(request)
        reply = replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return _Response(json.dumps(reply).encode())

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    monkeypatch.setattr("app.ai.remote_embeddings.time.sleep", lambda _s: None)
    return requests


def _remote(**kwargs: Any) -> RemoteEmbeddingProvider:
    return RemoteEmbeddingProvider(
        "http://api:8000/internal/embed",
        SECRET,
        model_name="fake/model",
        expected_dimension=DIM,
        **kwargs,
    )


def test_remote_provider_batches_and_sends_the_secret(monkeypatch: pytest.MonkeyPatch) -> None:
    vector = [1.0, 0.0, 0.0, 0.0]
    requests = _install_urlopen(
        monkeypatch,
        [{"vectors": [vector, vector]}, {"vectors": [vector]}, {"vectors": [vector]}],
    )
    provider = _remote(batch_size=2)
    assert provider.model_name == "fake/model"
    assert provider.dimension == DIM
    assert provider.embed(["a", "b", "c"]) == [vector] * 3
    assert provider.embed_query("q") == vector
    bodies = [json.loads(r.data) for r in requests]
    assert bodies == [
        {"texts": ["a", "b"], "kind": "passage"},
        {"texts": ["c"], "kind": "passage"},
        {"texts": ["q"], "kind": "query"},
    ]
    assert all(r.get_header(SECRET_HEADER.capitalize()) == SECRET for r in requests)


def test_remote_provider_retries_then_reports_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    down = urllib.error.URLError("connection refused")
    _install_urlopen(monkeypatch, [down, down, down])
    with pytest.raises(EmbeddingServiceUnavailableError) as info:
        _remote(retries=2).embed(["a"])
    assert isinstance(info.value, OSError)  # transient for the worker

    server_error = urllib.error.HTTPError("u", 503, "busy", {}, None)  # type: ignore[arg-type]
    vector = [0.0, 1.0, 0.0, 0.0]
    _install_urlopen(monkeypatch, [server_error, {"vectors": [vector]}])
    assert _remote(retries=1).embed(["a"]) == [vector]


def test_remote_provider_client_errors_and_bad_payloads(monkeypatch: pytest.MonkeyPatch) -> None:
    forbidden = urllib.error.HTTPError("u", 403, "no", {}, None)  # type: ignore[arg-type]
    _install_urlopen(monkeypatch, [forbidden])
    with pytest.raises(EmbeddingError, match="403"):
        _remote().embed(["a"])
    _install_urlopen(monkeypatch, [{"vectors": []}])
    with pytest.raises(EmbeddingError, match="wrong number"):
        _remote().embed(["a"])
    _install_urlopen(monkeypatch, [{"vectors": [[1.0]]}])
    with pytest.raises(EmbeddingError, match="wrong size"):
        _remote().embed(["a"])


# --- factory and configuration ---------------------------------------------------------


def test_factory_builds_remote_provider_and_token_counter() -> None:
    settings = _settings(
        embedding_provider="remote",
        embedding_remote_url="http://api:8000/internal/embed",
        internal_embed_secret=SECRET,
        embedding_batch_size=200,
        internal_embed_max_batch=64,
    )
    provider = create_embedding_provider(settings)
    assert isinstance(provider, RemoteEmbeddingProvider)
    assert provider._batch_size == 64  # noqa: SLF001
    counter = create_token_counter(settings)
    assert counter is create_token_counter(settings)
    assert isinstance(counter, TokenizerCounter)


def test_factory_rejects_remote_without_url() -> None:
    settings = _settings().model_copy(update={"embedding_provider": "remote"})
    with pytest.raises(AIProviderConfigurationError, match="EMBEDDING_REMOTE_URL"):
        create_embedding_provider(settings)


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"embedding_provider": "remote", "internal_embed_secret": SECRET}, "EMBEDDING_REMOTE_URL"),
        (
            {"embedding_provider": "remote", "embedding_remote_url": "http://api:8000/x"},
            "INTERNAL_EMBED_SECRET is required",
        ),
        (
            {
                "embedding_provider": "remote",
                "embedding_remote_url": "api:8000",
                "internal_embed_secret": SECRET,
            },
            "EMBEDDING_REMOTE_URL must be",
        ),
        ({"internal_embed_secret": "short"}, "INTERNAL_EMBED_SECRET must be"),
        ({"embedding_provider": "sentence-transformers"}, "torch extra"),
        ({"reranking_enabled": True}, "torch extra"),
    ],
)
def test_embedding_settings_are_validated(overrides: dict[str, object], message: str) -> None:
    with pytest.raises(SettingsError, match=message):
        _settings(**overrides)


def test_production_rejects_placeholder_internal_secret() -> None:
    with pytest.raises(SettingsError, match="INTERNAL_EMBED_SECRET still has"):
        load_settings(
            _env_file=None,
            app_env="production",
            jwt_secret_key="k" * 40,
            postgres_password="p" * 20,
            redis_password="r" * 20,
            cors_allowed_origins=["https://app.example.com"],
            internal_embed_secret="<random-secret-at-least-32-characters>",
        )


# --- POST /internal/embed --------------------------------------------------------------


@pytest.fixture
def internal_client() -> Iterator[tuple[TestClient, FastAPI, HashingEmbeddingProvider]]:
    settings = get_settings().model_copy(
        update={
            "internal_embed_secret": load_settings(
                _env_file=None,
                app_env="test",
                jwt_secret_key="k" * 40,
                internal_embed_secret=SECRET,
            ).internal_embed_secret,
            "internal_embed_max_batch": 3,
            "internal_embed_max_text_chars": 50,
        }
    )
    embedder = HashingEmbeddingProvider()
    app = create_app(settings)
    app.dependency_overrides[get_settings] = lambda: settings
    app.dependency_overrides[get_embedder] = lambda: embedder
    with TestClient(app) as client:
        yield client, app, embedder


def test_internal_embed_requires_the_secret(
    internal_client: tuple[TestClient, FastAPI, HashingEmbeddingProvider],
) -> None:
    client, _, _ = internal_client
    body = {"texts": ["refund window"]}
    assert client.post("/internal/embed", json=body).status_code == 401
    wrong = client.post("/internal/embed", json=body, headers={SECRET_HEADER: "x" * 40})
    assert wrong.status_code == 403
    ok = client.post("/internal/embed", json=body, headers={SECRET_HEADER: SECRET})
    assert ok.status_code == 200
    payload = ok.json()
    assert payload["dimension"] == 384
    assert len(payload["vectors"]) == 1
    assert len(payload["vectors"][0]) == 384


def test_internal_embed_query_kind_and_caps(
    internal_client: tuple[TestClient, FastAPI, HashingEmbeddingProvider],
) -> None:
    client, _, embedder = internal_client
    headers = {SECRET_HEADER: SECRET}
    query = client.post(
        "/internal/embed", json={"texts": ["refund"], "kind": "query"}, headers=headers
    )
    assert query.json()["vectors"][0] == embedder.embed_query("refund")
    too_many = client.post("/internal/embed", json={"texts": ["a"] * 4}, headers=headers)
    assert too_many.status_code == 422
    too_long = client.post("/internal/embed", json={"texts": ["a" * 51]}, headers=headers)
    assert too_long.status_code == 422
    empty = client.post("/internal/embed", json={"texts": []}, headers=headers)
    assert empty.status_code == 422
    huge = client.post("/internal/embed", content=b"x" * (2 * 1024 * 1024), headers=headers)
    assert huge.status_code == 413


def test_internal_embed_is_hidden_and_disabled_without_secret() -> None:
    settings = get_settings().model_copy(update={"api_docs_enabled": True})
    app = create_app(settings)
    app.dependency_overrides[get_settings] = lambda: settings
    with TestClient(app) as client:
        response = client.post("/internal/embed", json={"texts": ["a"]})
        assert response.status_code == 404
        assert "/internal/embed" not in client.get("/openapi.json").json()["paths"]


def test_internal_embed_refuses_remote_or_failing_embedder(
    internal_client: tuple[TestClient, FastAPI, HashingEmbeddingProvider],
) -> None:
    client, app, _ = internal_client
    headers = {SECRET_HEADER: SECRET}
    app.dependency_overrides[get_embedder] = lambda: _remote()  # noqa: PLW0108  (no params)
    assert client.post("/internal/embed", json={"texts": ["a"]}, headers=headers).status_code == 503
    app.dependency_overrides[get_embedder] = lambda: HashingEmbeddingProvider(fail=True)
    assert client.post("/internal/embed", json={"texts": ["a"]}, headers=headers).status_code == 503
