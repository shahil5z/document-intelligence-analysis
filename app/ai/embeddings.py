"""Local sentence-transformers embedding provider (default: BAAI/bge-small-en-v1.5).

The model is loaded lazily on first use and cached per process (one copy per worker
process / API process). Vectors are L2-normalised, so cosine similarity equals the dot
product and pgvector's cosine distance is meaningful.
"""

import logging
import threading
import time
from collections.abc import Sequence
from typing import TYPE_CHECKING, Any

from app.ai.errors import AIProviderConfigurationError, EmbeddingError

if TYPE_CHECKING:
    from sentence_transformers import SentenceTransformer

logger = logging.getLogger(__name__)


def apply_torch_threads(num_threads: int) -> None:
    """Cap PyTorch's intra-op thread pool for this process (0 keeps torch's default).

    torch defaults to one thread per CPU core. With several API/worker processes on one
    machine that oversubscribes the CPU: on the 8-vCPU verification box a single
    bge-small query embedding took about 1.5 s with 8 threads and about 10-20 ms with
    1-2 threads. The setting is process-wide, so it is applied before a model loads.
    """
    if num_threads <= 0:
        return
    import torch  # noqa: PLC0415  (lazy: only when a model is actually loaded)

    if torch.get_num_threads() != num_threads:
        torch.set_num_threads(num_threads)


class SentenceTransformerEmbeddingProvider:
    def __init__(
        self,
        model_name: str,
        *,
        expected_dimension: int,
        batch_size: int = 32,
        device: str = "cpu",
        query_instruction: str = "",
        num_threads: int = 0,
    ) -> None:
        self._model_name = model_name
        self._expected_dimension = expected_dimension
        self._batch_size = batch_size
        self._device = device
        self._query_instruction = query_instruction
        self._num_threads = num_threads
        self._model: SentenceTransformer | None = None
        self._lock = threading.Lock()

    @property
    def model_name(self) -> str:
        return self._model_name

    @property
    def dimension(self) -> int:
        return self._expected_dimension

    def _load(self) -> "SentenceTransformer":
        if self._model is not None:
            return self._model
        with self._lock:
            if self._model is None:
                started = time.perf_counter()
                # Lazy import: torch/transformers are heavy and must not slow API startup.
                from sentence_transformers import SentenceTransformer  # noqa: PLC0415

                apply_torch_threads(self._num_threads)
                model = SentenceTransformer(self._model_name, device=self._device)
                getter = (
                    getattr(model, "get_embedding_dimension", None)
                    or model.get_sentence_embedding_dimension
                )
                actual = getter()
                if actual != self._expected_dimension:
                    raise AIProviderConfigurationError(
                        f"Embedding model produces {actual}-dimensional vectors but "
                        f"EMBEDDING_DIMENSION is {self._expected_dimension}; the database "
                        "column must match (new migration required to change it)"
                    )
                logger.info(
                    "embedding.model_loaded",
                    extra={
                        "model": self._model_name,
                        "dimension": actual,
                        "max_seq_length": model.max_seq_length,
                        "torch_threads": self._num_threads or "default",
                        "duration_ms": round((time.perf_counter() - started) * 1000),
                    },
                )
                self._model = model
        return self._model

    def count_tokens(self, text: str) -> int:
        """Exact token count with the model's tokenizer (no special tokens)."""
        tokenizer: Any = self._load().tokenizer
        return len(tokenizer(text, add_special_tokens=False, verbose=False)["input_ids"])

    def _encode(self, texts: Sequence[str]) -> list[list[float]]:
        if not texts:
            return []
        model = self._load()
        try:
            vectors = model.encode(
                list(texts),
                batch_size=self._batch_size,
                normalize_embeddings=True,
                convert_to_numpy=True,
                show_progress_bar=False,
            )
        except (RuntimeError, ValueError) as exc:
            raise EmbeddingError("embedding inference failed") from exc
        result: list[list[float]] = vectors.tolist()
        return result

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        return self._encode(texts)

    def embed_query(self, text: str) -> list[float]:
        return self._encode([self._query_instruction + text])[0]


def embed_in_batches(provider: Any, texts: Sequence[str], batch_size: int) -> list[list[float]]:
    """Embed ``texts`` in fixed-size batches and validate count and dimension."""
    if batch_size < 1:
        raise ValueError("batch_size must be positive")
    vectors: list[list[float]] = []
    for offset in range(0, len(texts), batch_size):
        batch = list(texts[offset : offset + batch_size])
        result = provider.embed(batch)
        if len(result) != len(batch):
            raise EmbeddingError("embedding provider returned the wrong number of vectors")
        for vector in result:
            if len(vector) != provider.dimension:
                raise EmbeddingError("embedding provider returned a vector of the wrong size")
        vectors.extend(result)
    return vectors
