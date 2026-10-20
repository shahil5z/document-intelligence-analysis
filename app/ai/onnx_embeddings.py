"""ONNX Runtime embedding provider and tokenizer-only token counter (no PyTorch).

Runs the model's own ONNX export (default: BAAI/bge-small-en-v1.5 ``onnx/model.onnx``,
fp32, the same weights as the PyTorch checkpoint) with the model's ``tokenizer.json``.
Pooling and normalisation reproduce the sentence-transformers pipeline of that model:
CLS-token pooling, then L2 normalisation, so cosine similarity equals the dot product
and the vectors fit the existing ``vector(384)`` column and HNSW cosine index.

Files are fetched with ``huggingface_hub`` into ``HF_HOME`` on first use (or read from
the cache only with ``HF_HUB_OFFLINE=1``). Nothing loads at import time.
"""

import logging
import threading
import time
from collections.abc import Sequence
from typing import TYPE_CHECKING, Any

from app.ai.errors import AIProviderConfigurationError, EmbeddingError

if TYPE_CHECKING:
    import onnxruntime
    from tokenizers import Tokenizer

logger = logging.getLogger(__name__)

TOKENIZER_FILE = "tokenizer.json"


def hub_file(model_name: str, filename: str) -> str:
    """Local path of ``filename`` from the model repository (downloaded once, cached)."""
    from huggingface_hub import hf_hub_download  # noqa: PLC0415  (lazy)

    try:
        return hf_hub_download(repo_id=model_name, filename=filename)
    except Exception as exc:  # network, offline cache miss, unknown file
        raise AIProviderConfigurationError(
            f"Could not obtain {filename} for embedding model {model_name} "
            f"({type(exc).__name__}); check network access or the HF_HOME cache"
        ) from exc


def load_tokenizer(model_name: str) -> "Tokenizer":
    from tokenizers import Tokenizer  # noqa: PLC0415  (lazy)

    return Tokenizer.from_file(hub_file(model_name, TOKENIZER_FILE))


class TokenizerCounter:
    """Exact token counts with the embedding model's tokenizer, without loading the model.

    Matches ``SentenceTransformer.tokenizer(text, add_special_tokens=False)``: no special
    tokens, no truncation, no padding. Used by the chunker in the worker.
    """

    def __init__(self, model_name: str) -> None:
        self._model_name = model_name
        self._tokenizer: Tokenizer | None = None
        self._lock = threading.Lock()

    def _load(self) -> "Tokenizer":
        if self._tokenizer is None:
            with self._lock:
                if self._tokenizer is None:
                    tokenizer = load_tokenizer(self._model_name)
                    tokenizer.no_truncation()
                    tokenizer.no_padding()
                    self._tokenizer = tokenizer
        return self._tokenizer

    def count_tokens(self, text: str) -> int:
        return len(self._load().encode(text, add_special_tokens=False).ids)


class OnnxEmbeddingProvider:
    def __init__(
        self,
        model_name: str,
        *,
        expected_dimension: int,
        onnx_file: str = "onnx/model.onnx",
        batch_size: int = 32,
        max_seq_length: int = 512,
        query_instruction: str = "",
        num_threads: int = 0,
    ) -> None:
        self._model_name = model_name
        self._expected_dimension = expected_dimension
        self._onnx_file = onnx_file
        self._batch_size = batch_size
        self._max_seq_length = max_seq_length
        self._query_instruction = query_instruction
        self._num_threads = num_threads
        self._session: onnxruntime.InferenceSession | None = None
        self._tokenizer: Tokenizer | None = None
        self._counter = TokenizerCounter(model_name)
        self._input_names: frozenset[str] = frozenset()
        self._lock = threading.Lock()

    @property
    def model_name(self) -> str:
        return self._model_name

    @property
    def dimension(self) -> int:
        return self._expected_dimension

    @property
    def loaded(self) -> bool:
        return self._session is not None

    def _load(self) -> tuple["onnxruntime.InferenceSession", "Tokenizer"]:
        if self._session is None or self._tokenizer is None:
            with self._lock:
                if self._session is None or self._tokenizer is None:
                    self._session, self._tokenizer = self._build()
        return self._session, self._tokenizer

    def _build(self) -> tuple["onnxruntime.InferenceSession", "Tokenizer"]:
        started = time.perf_counter()
        import onnxruntime as ort  # noqa: PLC0415  (lazy: keep it off the startup path)

        tokenizer = load_tokenizer(self._model_name)
        tokenizer.enable_truncation(max_length=self._max_seq_length)
        tokenizer.enable_padding()
        options = ort.SessionOptions()
        if self._num_threads > 0:
            options.intra_op_num_threads = self._num_threads
        options.inter_op_num_threads = 1
        session = ort.InferenceSession(
            hub_file(self._model_name, self._onnx_file),
            sess_options=options,
            providers=["CPUExecutionProvider"],
        )
        actual = session.get_outputs()[0].shape[-1]
        if actual != self._expected_dimension:
            raise AIProviderConfigurationError(
                f"Embedding model produces {actual}-dimensional vectors but "
                f"EMBEDDING_DIMENSION is {self._expected_dimension}; the database "
                "column must match (new migration required to change it)"
            )
        self._input_names = frozenset(item.name for item in session.get_inputs())
        logger.info(
            "embedding.model_loaded",
            extra={
                "model": self._model_name,
                "backend": "onnxruntime",
                "dimension": actual,
                "max_seq_length": self._max_seq_length,
                "threads": self._num_threads or "default",
                "duration_ms": round((time.perf_counter() - started) * 1000),
            },
        )
        return session, tokenizer

    def count_tokens(self, text: str) -> int:
        return self._counter.count_tokens(text)

    def _run(self, texts: Sequence[str]) -> list[list[float]]:
        import numpy as np  # noqa: PLC0415

        session, tokenizer = self._load()
        encodings = tokenizer.encode_batch(list(texts))
        feeds: dict[str, Any] = {
            "input_ids": np.array([e.ids for e in encodings], dtype=np.int64),
            "attention_mask": np.array([e.attention_mask for e in encodings], dtype=np.int64),
            "token_type_ids": np.array([e.type_ids for e in encodings], dtype=np.int64),
        }
        feeds = {name: value for name, value in feeds.items() if name in self._input_names}
        try:
            hidden = session.run(None, feeds)[0]
        except Exception as exc:  # onnxruntime raises its own exception types
            raise EmbeddingError("embedding inference failed") from exc
        cls = hidden[:, 0, :]
        norms = np.linalg.norm(cls, axis=1, keepdims=True)
        vectors = cls / np.clip(norms, 1e-12, None)
        result: list[list[float]] = vectors.astype(np.float32).tolist()
        return result

    def _encode(self, texts: Sequence[str]) -> list[list[float]]:
        vectors: list[list[float]] = []
        for offset in range(0, len(texts), self._batch_size):
            vectors.extend(self._run(texts[offset : offset + self._batch_size]))
        return vectors

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        return self._encode(texts) if texts else []

    def embed_query(self, text: str) -> list[float]:
        return self._encode([self._query_instruction + text])[0]
